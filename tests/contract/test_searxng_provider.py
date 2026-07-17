"""Contract test for SearXNGSearchProvider — see ARCHITECTURE.md §10.3.

Asserts a SearXNG-shaped JSON response maps correctly to SearchResult. Run
this first after bumping the vendored SearXNG commit (BUILD.md §10.2) — a
failure here means the JSON response shape changed and searxng_provider.py
needs updating, before anything else.

Uses a recorded fixture response via httpx.MockTransport rather than a live
SearXNG instance, so it runs in any environment; it still exercises the
exact parsing code the real HTTP call goes through.
"""

import httpx

from app.services.search.searxng_provider import SearXNGSearchProvider

# Trimmed shape of a real SearXNG `?format=json` response (searxng/searxng,
# docs: https://docs.searxng.org/dev/search_api.html).
_FIXTURE_RESPONSE = {
    "query": "fastapi async",
    "results": [
        {
            "url": "https://fastapi.tiangolo.com/async/",
            "title": "Concurrency and async / await",
            "content": "FastAPI async guide...",
            "engine": "google",
        },
        {
            "url": "https://example.com/other",
            "title": "Other result",
            "content": "Some other content",
            "engine": "bing",
        },
    ],
}


def _mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search"
        assert request.url.params["format"] == "json"
        return httpx.Response(200, json=_FIXTURE_RESPONSE)

    return httpx.MockTransport(handler)


async def test_maps_searxng_response_to_search_result():
    client = httpx.AsyncClient(transport=_mock_transport())
    provider = SearXNGSearchProvider(base_url="http://searxng.test", client=client)

    results = await provider.search("fastapi async", limit=5)

    assert len(results) == 2
    assert results[0].url == "https://fastapi.tiangolo.com/async/"
    assert results[0].title == "Concurrency and async / await"
    assert results[0].snippet == "FastAPI async guide..."
    assert results[0].rank == 1
    assert results[1].rank == 2


async def test_respects_limit():
    client = httpx.AsyncClient(transport=_mock_transport())
    provider = SearXNGSearchProvider(base_url="http://searxng.test", client=client)

    results = await provider.search("fastapi async", limit=1)

    assert len(results) == 1
