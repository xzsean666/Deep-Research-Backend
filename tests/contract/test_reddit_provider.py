"""Contract test for RedditSearchProvider.

Uses a recorded fixture response via httpx.MockTransport rather than a live
Reddit endpoint, so it runs in any environment; it still exercises the exact
parsing code the real HTTP call goes through.
"""

import httpx

from app.services.search.reddit_provider import RedditSearchProvider

# Trimmed shape of a real Reddit `/search.json` response.
_FIXTURE_RESPONSE = {
    "data": {
        "children": [
            {
                "data": {
                    "permalink": "/r/politics/comments/abc123/some_thread/",
                    "title": "Some thread about the election",
                    "selftext": "Body text of the self post",
                }
            },
            {
                "data": {
                    "permalink": "/r/worldnews/comments/def456/a_link_post/",
                    "title": "A link post with no selftext",
                    "selftext": "",
                    "url": "https://news.example.com/article",
                }
            },
            {
                # No permalink and no url — must be skipped, not emitted with url=None.
                "data": {
                    "title": "Malformed entry",
                    "selftext": "",
                }
            },
        ]
    }
}


def _mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search.json"
        assert request.url.params["q"] == "example query"
        assert request.headers["user-agent"] == "TestAgent/1.0"
        return httpx.Response(200, json=_FIXTURE_RESPONSE)

    return httpx.MockTransport(handler)


async def test_maps_reddit_response_to_search_result():
    client = httpx.AsyncClient(transport=_mock_transport(), headers={"User-Agent": "TestAgent/1.0"})
    provider = RedditSearchProvider(base_url="https://reddit.test", user_agent="TestAgent/1.0", client=client)

    results = await provider.search("example query", limit=5)

    assert len(results) == 2
    assert results[0].url == "https://www.reddit.com/r/politics/comments/abc123/some_thread/"
    assert results[0].title == "Some thread about the election"
    assert results[0].snippet == "Body text of the self post"
    assert results[0].rank == 1
    assert results[1].snippet is None
    assert results[1].rank == 2


async def test_respects_limit():
    client = httpx.AsyncClient(transport=_mock_transport(), headers={"User-Agent": "TestAgent/1.0"})
    provider = RedditSearchProvider(base_url="https://reddit.test", user_agent="TestAgent/1.0", client=client)

    results = await provider.search("example query", limit=1)

    assert len(results) == 1


async def test_skips_entries_without_a_url():
    client = httpx.AsyncClient(transport=_mock_transport(), headers={"User-Agent": "TestAgent/1.0"})
    provider = RedditSearchProvider(base_url="https://reddit.test", user_agent="TestAgent/1.0", client=client)

    results = await provider.search("example query", limit=5)

    assert all(r.title != "Malformed entry" for r in results)


def test_passes_proxy_to_default_client(monkeypatch):
    seen_kwargs = {}

    class _FakeAsyncClient:
        def __init__(self, **kwargs):
            seen_kwargs.update(kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    RedditSearchProvider(proxy="http://proxy.test:8080")

    assert seen_kwargs["proxy"] == "http://proxy.test:8080"
