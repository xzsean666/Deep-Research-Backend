import re
from datetime import datetime

import httpx

from app.services.crawl.errors import CrawlFetchError
from app.services.crawl.provider import CrawlResult
from app.services.crawl.url_guard import guard_url

# Crawl4AI's own documented default pruning config (docs/examples/docker/
# demo_docker_api.py) — asking for this populates `markdown.fit_markdown`
# (boilerplate-stripped) instead of leaving it empty, which is what happens
# with no crawler_config at all (today's behavior).
_CRAWLER_CONFIG = {
    "type": "CrawlerRunConfig",
    "params": {
        "markdown_generator": {
            "type": "DefaultMarkdownGenerator",
            "params": {
                "content_filter": {
                    "type": "PruningContentFilter",
                    "params": {"threshold": 0.6, "threshold_type": "relative"},
                }
            },
        }
    },
}

# Tried in order against the crawled page's raw HTML. Neither requires
# Crawl4AI-side config — both are always present in its response, just not
# parsed today.
_JSON_LD_DATE_RE = re.compile(r'"datePublished"\s*:\s*"([^"]+)"')
_OG_DATE_RE = re.compile(r'article:published_time"\s+content="([^"]+)"')


def _extract_published_at(html: str) -> datetime | None:
    for pattern in (_JSON_LD_DATE_RE, _OG_DATE_RE):
        match = pattern.search(html)
        if not match:
            continue
        raw = match.group(1).strip()
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
    return None


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
        api_token: str,
        client: httpx.AsyncClient | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._max_response_bytes = max_response_bytes
        self._api_token = api_token
        self._client = client or httpx.AsyncClient(timeout=fetch_timeout_seconds)

    async def crawl(self, url: str) -> CrawlResult:
        await guard_url(url)

        response = await self._client.post(
            f"{self._base_url}/crawl",
            json={"urls": [url], "crawler_config": _CRAWLER_CONFIG},
            headers={"Authorization": f"Bearer {self._api_token}"},
        )
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
            markdown = markdown.get("fit_markdown") or markdown.get("raw_markdown", "")
        markdown = markdown or ""

        max_bytes = self._max_response_bytes
        encoded = markdown.encode("utf-8")
        if len(encoded) > max_bytes:
            markdown = encoded[:max_bytes].decode("utf-8", errors="ignore")

        metadata = result.get("metadata") or {}
        title = metadata.get("title") or result.get("title")
        published_at = _extract_published_at(result.get("html") or "")

        return CrawlResult(
            url=url, title=title, markdown=markdown, metadata=metadata, published_at=published_at
        )
