import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from app.services.crawl.errors import CrawlBlockedError

_ALLOWED_SCHEMES = frozenset({"http", "https"})


def _is_disallowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # is_link_local also covers 169.254.0.0/16, which is where cloud
    # metadata endpoints (e.g. 169.254.169.254) live — the classic SSRF target.
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def guard_url(url: str) -> None:
    """Raise CrawlBlockedError if `url` must not be fetched.

    Call this before the initial fetch AND before following each redirect
    hop — a URL that passes the guard can still redirect to a private
    address, so re-validating per hop is not optional (ARCHITECTURE.md §7).
    """
    parts = urlsplit(url)
    if parts.scheme not in _ALLOWED_SCHEMES:
        raise CrawlBlockedError(url, f"scheme '{parts.scheme}' is not allowed")

    hostname = parts.hostname
    if not hostname:
        raise CrawlBlockedError(url, "URL has no hostname")

    loop = asyncio.get_running_loop()
    try:
        addr_infos = await loop.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise CrawlBlockedError(url, f"DNS resolution failed: {exc}") from exc

    for _family, _type, _proto, _canonname, sockaddr in addr_infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if _is_disallowed_ip(ip):
            raise CrawlBlockedError(url, f"resolves to disallowed address {ip}")
