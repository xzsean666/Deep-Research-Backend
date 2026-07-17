"""Contract test for Crawl4AICrawlProvider — see ARCHITECTURE.md §10.3.

Asserts a Crawl4AI-shaped JSON response maps correctly to CrawlResult. Run
this first after bumping the vendored Crawl4AI commit (BUILD.md §10.2).

Uses httpx.MockTransport rather than a live Crawl4AI instance. The exact
response shape (particularly whether `markdown` is a plain string or an
object with `raw_markdown`) has changed across Crawl4AI versions — that
volatility is exactly why it's isolated to crawl4ai_provider.py.
"""

import httpx
import pytest

from app.services.crawl.crawl4ai_provider import Crawl4AICrawlProvider
from app.services.crawl.errors import CrawlBlockedError, CrawlFetchError

_FIXTURE_SUCCESS = {
    "results": [
        {
            "url": "https://example.com/article",
            "success": True,
            "markdown": {"raw_markdown": "# Title\n\nBody text."},
            "metadata": {"title": "Example Article"},
        }
    ]
}

_FIXTURE_FAILURE = {
    "results": [{"url": "https://example.com/gone", "success": False, "error_message": "404"}]
}


def _transport(payload: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/crawl"
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


async def test_maps_successful_crawl_to_crawl_result():
    client = httpx.AsyncClient(transport=_transport(_FIXTURE_SUCCESS))
    provider = Crawl4AICrawlProvider(
        base_url="http://crawl4ai.test",
        fetch_timeout_seconds=5,
        max_response_bytes=5_000_000,
        client=client,
        api_token="test-token",
    )

    result = await provider.crawl("https://example.com/article")

    assert result.markdown == "# Title\n\nBody text."
    assert result.title == "Example Article"


async def test_sends_bearer_token_crawl4ai_requires_it_to_bind_non_loopback():
    """Crawl4AI's entrypoint refuses to bind beyond 127.0.0.1 without
    CRAWL4AI_API_TOKEN, and then enforces that same token as a Bearer auth
    header on every request (vendor/crawl4ai/deploy/docker/entrypoint.sh,
    auth_gate.py) — discovered by an actual failed deployment. Without this
    header, every real crawl fails with a connection error, not a clean 401.
    """
    seen_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json=_FIXTURE_SUCCESS)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = Crawl4AICrawlProvider(
        base_url="http://crawl4ai.test",
        fetch_timeout_seconds=5,
        max_response_bytes=5_000_000,
        client=client,
        api_token="secret-token",
    )

    await provider.crawl("https://example.com/article")

    assert seen_headers.get("authorization") == "Bearer secret-token"


async def test_raises_on_provider_reported_failure():
    client = httpx.AsyncClient(transport=_transport(_FIXTURE_FAILURE))
    provider = Crawl4AICrawlProvider(
        base_url="http://crawl4ai.test",
        fetch_timeout_seconds=5,
        max_response_bytes=5_000_000,
        client=client,
        api_token="test-token",
    )

    with pytest.raises(CrawlFetchError):
        await provider.crawl("https://example.com/gone")


async def test_truncates_markdown_over_max_bytes():
    big_markdown = "x" * 100
    client = httpx.AsyncClient(
        transport=_transport(
            {"results": [{"url": "u", "success": True, "markdown": big_markdown, "metadata": {}}]}
        )
    )
    provider = Crawl4AICrawlProvider(
        base_url="http://crawl4ai.test",
        fetch_timeout_seconds=5,
        max_response_bytes=10,
        client=client,
        api_token="test-token",
    )

    result = await provider.crawl("https://example.com/big")

    assert len(result.markdown.encode("utf-8")) <= 10


async def test_guard_rejects_private_target_before_calling_provider():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not reach crawl4ai for a blocked URL")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = Crawl4AICrawlProvider(
        base_url="http://crawl4ai.test",
        fetch_timeout_seconds=5,
        max_response_bytes=10,
        client=client,
        api_token="test-token",
    )

    with pytest.raises(CrawlBlockedError):
        await provider.crawl("ftp://example.com/file")
