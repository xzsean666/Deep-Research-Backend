import httpx

from app.services.search.provider import SearchResult

# Reddit's unauthenticated JSON endpoints 403/429 a default HTTP client's
# User-Agent string — a descriptive one is required, not just polite.
_DEFAULT_USER_AGENT = "DeepResearchBackend/1.0"


class RedditSearchProvider:
    """The only file that knows Reddit's search.json response shape.

    Uses Reddit's public, unauthenticated search — no API key required in
    principle. In practice (confirmed live, both against reddit.com and
    old.reddit.com), Reddit now 403s most anonymous JSON requests
    regardless of User-Agent — this is a platform-wide lockdown, not
    something fixable client-side short of registering an app and using
    OAuth. Left disabled by default (SEARCH_REDDIT_ENABLED=false); a 403
    degrades to an empty result via CompositeSearchProvider's per-source
    error handling, so enabling it is harmless but currently low-value.

    Template for future extra sources: same constructor shape (base_url +
    optional injected client), same `search(query, limit) -> list[SearchResult]`
    method.
    """

    def __init__(
        self,
        base_url: str = "https://www.reddit.com",
        user_agent: str = _DEFAULT_USER_AGENT,
        proxy: str | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(
            timeout=10, headers={"User-Agent": user_agent}, proxy=proxy
        )

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        response = await self._client.get(
            f"{self._base_url}/search.json",
            params={"q": query, "limit": limit, "sort": "relevance"},
        )
        response.raise_for_status()
        payload = response.json()
        children = payload.get("data", {}).get("children", [])

        results = []
        for rank, child in enumerate(children[:limit], start=1):
            data = child.get("data", {})
            permalink = data.get("permalink")
            url = f"https://www.reddit.com{permalink}" if permalink else data.get("url")
            if not url:
                continue
            results.append(
                SearchResult(
                    url=url,
                    title=data.get("title"),
                    snippet=data.get("selftext") or None,
                    rank=rank,
                )
            )
        return results
