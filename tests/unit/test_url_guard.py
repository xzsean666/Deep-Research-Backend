import asyncio
import socket

import pytest

from app.services.crawl.errors import CrawlBlockedError
from app.services.crawl.url_guard import guard_url


def _fake_resolution(ip: str):
    async def fake_getaddrinfo(host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    return fake_getaddrinfo


async def test_rejects_non_http_scheme():
    with pytest.raises(CrawlBlockedError):
        await guard_url("ftp://example.com/file")


async def test_rejects_missing_hostname():
    with pytest.raises(CrawlBlockedError):
        await guard_url("http:///no-host")


async def test_rejects_loopback(monkeypatch):
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", _fake_resolution("127.0.0.1"))
    with pytest.raises(CrawlBlockedError):
        await guard_url("http://internal.example.com/")


async def test_rejects_private_range(monkeypatch):
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", _fake_resolution("10.0.0.5"))
    with pytest.raises(CrawlBlockedError):
        await guard_url("http://internal.example.com/")


async def test_rejects_cloud_metadata_address(monkeypatch):
    monkeypatch.setattr(
        asyncio.get_running_loop(), "getaddrinfo", _fake_resolution("169.254.169.254")
    )
    with pytest.raises(CrawlBlockedError):
        await guard_url("http://metadata.example.com/")


async def test_allows_public_address(monkeypatch):
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", _fake_resolution("93.184.216.34"))
    await guard_url("http://example.com/")  # must not raise
