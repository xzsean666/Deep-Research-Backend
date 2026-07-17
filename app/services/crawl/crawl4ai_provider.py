import httpx

from app.services.crawl.errors import CrawlFetchError
from app.services.crawl.provider import CrawlResult
from app.services.crawl.url_guard import guard_url


class Crawl4AICrawlProvider:
    """The only file that knows Crawl4AI's request/response shape.

    See ARCHITECTURE.md §10 — nothing outside this module may import it by
    name; callers depend on the CrawlProvider protocol instead.

    KNOWN GAP: Crawl4AI performs the actual HTTP fetch — including
    following redirects — inside its own service. This adapter guards the
    initial URL (§7) before submitting it, but cannot re-validate each
    redirect hop Crawl4AI follows internally, so ARCHITECTURE.md §7's
    "re-validate on every redirect hop" is not fully enforced yet. Closing
    this needs either Crawl4AI-side network policy config or fetching
    directly instead of delegating — tracked in docs/nextsession.md.
    """

    def __init__(
        self,
        base_url: str,
        *,
        fetch_timeout_seconds: float,
        max_response_bytes: int,
        client: httpx.AsyncClient | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._max_response_bytes = max_response_bytes
        self._client = client or httpx.AsyncClient(timeout=fetch_timeout_seconds)

    async def crawl(self, url: str) -> CrawlResult:
        await guard_url(url)

        response = await self._client.post(f"{self._base_url}/crawl", json={"urls": [url]})
        response.raise_for_status()
        payload = response.json()

        results = payload.get("results") or []
        if not results:
            raise CrawlFetchError(url, "crawl4ai returned no results")
        result = results[0]

        if not result.get("success", True):
            raise CrawlFetchError(url, result.get("error_message") or "crawl failed")

        markdown = result.get("markdown")
        if isinstance(markdown, dict):
            markdown = markdown.get("raw_markdown", "")
        markdown = markdown or ""

        max_bytes = self._max_response_bytes
        encoded = markdown.encode("utf-8")
        if len(encoded) > max_bytes:
            markdown = encoded[:max_bytes].decode("utf-8", errors="ignore")

        metadata = result.get("metadata") or {}
        title = metadata.get("title") or result.get("title")

        return CrawlResult(url=url, title=title, markdown=markdown, metadata=metadata)
