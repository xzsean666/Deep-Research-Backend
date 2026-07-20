from app.config import Settings


def get_outbound_proxy_url(settings: Settings) -> str | None:
    """Resolve settings.outbound_proxy_url to what an httpx client making the
    request directly (search providers) should connect to.

    http(s):// and socks5:// pass through unchanged. vless:// isn't a proxy
    scheme any HTTP client understands, so it's redirected to the `xray`
    compose service (docker/xray/) which speaks vless and exposes a plain
    SOCKS5 proxy — see settings.outbound_proxy_xray_url.
    """
    raw = settings.outbound_proxy_url
    if not raw:
        return None
    if raw.startswith("vless://"):
        return settings.outbound_proxy_xray_url
    return raw


def get_crawl4ai_proxy_url(settings: Settings) -> None:
    """What should be sent to Crawl4AI as its proxy_config — always None.

    Crawl4AI's own hardened server refuses proxy_config from any network
    request, for any value (http/socks5/vless alike) — see
    UNTRUSTED_FORBIDDEN_FIELDS in vendor/crawl4ai/crawl4ai/async_configs.py,
    a real SSRF/secret-exfiltration guard, not a bug. Forwarding it (as
    Crawl4AICrawlProvider originally did) just gets every crawl rejected
    with 400. For OUTBOUND_PROXY_URL=vless://..., Crawl4AI's own container
    instead transparently redirects all outbound TCP through the `xray`
    service at the OS network level (docker/crawl4ai/Dockerfile.cn +
    docker-entrypoint-proxy.sh, used via docker-compose.cn.yml) — it never
    needs to be told about a proxy at all. http(s):///socks5:// values have
    no equivalent trusted server-side path yet, so they're a documented gap
    (OUTBOUND_PROXY_URL still applies to the search providers either way —
    see get_outbound_proxy_url).
    """
    return None


__all__ = ["get_outbound_proxy_url", "get_crawl4ai_proxy_url"]
