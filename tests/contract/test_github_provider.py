"""Contract test for GitHubSearchProvider.

Uses a recorded fixture response via httpx.MockTransport rather than a live
GitHub endpoint, so it runs in any environment; it still exercises the exact
parsing code the real HTTP call goes through.
"""

import httpx

from app.services.search.github_provider import GitHubSearchProvider, _build_headers

# Trimmed shape of a real GitHub `/search/repositories` response.
_FIXTURE_RESPONSE = {
    "items": [
        {
            "full_name": "example-org/solidity-audit-toolkit",
            "html_url": "https://github.com/example-org/solidity-audit-toolkit",
            "description": "A toolkit for auditing Solidity smart contracts",
        },
        {
            "full_name": "another-org/no-description-repo",
            "html_url": "https://github.com/another-org/no-description-repo",
            "description": None,
        },
        {
            # Missing html_url — must be skipped, not emitted with url=None.
            "full_name": "broken/no-url",
            "description": "malformed entry",
        },
    ]
}


def _mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search/repositories"
        assert request.url.params["q"] == "solidity audit"
        return httpx.Response(200, json=_FIXTURE_RESPONSE)

    return httpx.MockTransport(handler)


async def test_maps_github_response_to_search_result():
    client = httpx.AsyncClient(transport=_mock_transport())
    provider = GitHubSearchProvider(base_url="https://api.github.test", client=client)

    results = await provider.search("solidity audit", limit=5)

    assert len(results) == 2
    assert results[0].url == "https://github.com/example-org/solidity-audit-toolkit"
    assert results[0].title == "example-org/solidity-audit-toolkit"
    assert results[0].snippet == "A toolkit for auditing Solidity smart contracts"
    assert results[0].rank == 1
    assert results[1].snippet is None


async def test_respects_limit():
    client = httpx.AsyncClient(transport=_mock_transport())
    provider = GitHubSearchProvider(base_url="https://api.github.test", client=client)

    results = await provider.search("solidity audit", limit=1)

    assert len(results) == 1


async def test_skips_entries_without_a_url():
    client = httpx.AsyncClient(transport=_mock_transport())
    provider = GitHubSearchProvider(base_url="https://api.github.test", client=client)

    results = await provider.search("solidity audit", limit=5)

    assert all(r.title != "broken/no-url" for r in results)


def test_sets_authorization_header_when_token_configured():
    headers = _build_headers(token="secret123", user_agent="ua")

    assert headers["Authorization"] == "Bearer secret123"


def test_omits_authorization_header_when_no_token():
    headers = _build_headers(token="", user_agent="ua")

    assert "Authorization" not in headers
