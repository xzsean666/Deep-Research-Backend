import httpx

from app.services.search.provider import SearchResult

_DEFAULT_USER_AGENT = "DeepResearchBackend/1.0"


def _build_headers(token: str, user_agent: str) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": user_agent,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class GitHubSearchProvider:
    """The only file that knows GitHub's repository search response shape.

    GitHub's official REST search API — reliable and structured, unlike
    Reddit/X's scraping-based alternatives. Works unauthenticated (10
    req/min GitHub-enforced limit); an optional token raises that to 30
    req/min via the standard `Authorization: Bearer` header. Confirmed
    live: returns 0 results for queries with no code/repo relevance
    (correct behavior, not a bug) and real hits for code-relevant ones.
    """

    def __init__(
        self,
        base_url: str = "https://api.github.com",
        token: str = "",
        user_agent: str = _DEFAULT_USER_AGENT,
        client: httpx.AsyncClient | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(
            timeout=10, headers=_build_headers(token, user_agent)
        )

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        response = await self._client.get(
            f"{self._base_url}/search/repositories",
            params={"q": query, "per_page": limit},
        )
        response.raise_for_status()
        items = response.json().get("items", [])

        return [
            SearchResult(
                url=item.get("html_url"),
                title=item.get("full_name"),
                snippet=item.get("description"),
                rank=rank,
            )
            for rank, item in enumerate(items[:limit], start=1)
            if item.get("html_url")
        ]
