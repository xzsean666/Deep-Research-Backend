import httpx

from app.services.search.provider import SearchResult


class SearXNGSearchProvider:
    """The only file that knows SearXNG's JSON response shape.

    See ARCHITECTURE.md §10 — nothing outside this module may import it by
    name; callers depend on the SearchProvider protocol instead.
    """

    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None):
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=10)

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        response = await self._client.get(
            f"{self._base_url}/search", params={"q": query, "format": "json"}
        )
        response.raise_for_status()
        payload = response.json()

        return [
            SearchResult(
                url=item["url"],
                title=item.get("title"),
                snippet=item.get("content"),
                rank=rank,
            )
            for rank, item in enumerate(payload.get("results", [])[:limit], start=1)
        ]
