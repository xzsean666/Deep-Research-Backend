import re

import httpx

from app.services.search.provider import SearchResult

# Truth Social's Mastodon-style search API 403s a bare httpx User-Agent;
# a desktop browser UA is required, not just polite (confirmed live).
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_MAX_TITLE_CHARS = 160
_MAX_SNIPPET_CHARS = 500
_HTML_TAG_RE = re.compile(r"<[^>]*>")
_HTML_ENTITIES = {
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&#39;": "'",
    "&#039;": "'",
    "&#x27;": "'",
    "&quot;": '"',
    "&nbsp;": " ",
}


def _strip_html(html: str) -> str:
    text = _HTML_TAG_RE.sub(" ", html)
    for entity, replacement in _HTML_ENTITIES.items():
        text = text.replace(entity, replacement)
    return " ".join(text.split())


def _status_url(status: dict) -> str | None:
    if status.get("url"):
        return status["url"]
    if status.get("uri"):
        return status["uri"]
    account = status.get("account") or {}
    acct = account.get("acct") or account.get("username")
    status_id = status.get("id")
    if acct and status_id:
        return f"https://truthsocial.com/@{acct}/{status_id}"
    return None


# Confirmed live: Truth Social's own API 403s (Cloudflare) from at least two
# separate egress networks, so this fallback is the one that actually serves
# data in practice. Third-party archive of Trump's Truth Social posts,
# structured JSON (not HTML scraping). Query matching is loose — good for
# genuinely Trump-related queries, degrades to generic recent posts for
# anything else — which is why this source stays low-weight/capped by
# default regardless of which tier answers.
_FACTBASE_ARCHIVE_URL = "https://rollcall.com/wp-json/factbase/v1/twitter"
_FACTBASE_REFERER = "https://rollcall.com/factbase-twitter/"


class TruthSocialSearchProvider:
    """The only file that knows Truth Social's search response shapes.

    This is Donald Trump's Truth Social feed specifically — genuinely
    relevant only for markets about his statements/policy, noise for
    everything else (this is the exact source that, in a prior system with
    naive cross-source relevance scoring, drowned out relevant results on
    unrelated queries). Meant to be enabled only with a low weight and a
    small `max_results` cap via CompositeSearchProvider, never as a
    primary source — see SEARCH_TRUTH_SOCIAL_* settings.

    Tries the primary Mastodon-style search API first; on failure (or a
    clean empty result), falls back to the Factbase archive — confirmed
    live to be what's actually reachable from this deployment's network.
    """

    def __init__(
        self,
        base_url: str = "https://truthsocial.com",
        user_agent: str = _DEFAULT_USER_AGENT,
        client: httpx.AsyncClient | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(
            timeout=10, headers={"Accept": "application/json", "User-Agent": user_agent}
        )

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        try:
            results = await self._search_primary(query, limit)
        except httpx.HTTPStatusError:
            results = []
        if results:
            return results
        return await self._search_factbase_archive(query, limit)

    async def _search_primary(self, query: str, limit: int) -> list[SearchResult]:
        response = await self._client.get(
            f"{self._base_url}/api/v2/search",
            params={"type": "statuses", "limit": limit, "q": query},
        )
        response.raise_for_status()
        statuses = response.json().get("statuses", [])

        results = []
        for rank, status in enumerate(statuses[:limit], start=1):
            status = status.get("reblog") or status
            url = _status_url(status)
            if not url:
                continue
            content = _strip_html(status.get("content") or "")
            if not content:
                continue
            results.append(
                SearchResult(
                    url=url,
                    title=content[:_MAX_TITLE_CHARS],
                    snippet=content[:_MAX_SNIPPET_CHARS],
                    rank=rank,
                )
            )
        return results

    async def _search_factbase_archive(self, query: str, limit: int) -> list[SearchResult]:
        response = await self._client.get(
            _FACTBASE_ARCHIVE_URL,
            params={
                "q": query,
                "platform": "truth social",
                "sort": "date",
                "sort_order": "desc",
                "page": 1,
                "format": "json",
            },
            headers={"Referer": _FACTBASE_REFERER},
        )
        response.raise_for_status()
        items = response.json().get("data", [])

        results = []
        for item in items:
            if (item.get("platform") or "").lower() != "truth social":
                continue
            url = item.get("post_url") or item.get("factbase_url")
            if not url:
                continue
            content = _strip_html(item.get("text") or (item.get("social") or {}).get("post_html") or "")
            if not content:
                continue
            results.append(
                SearchResult(
                    url=url,
                    title=content[:_MAX_TITLE_CHARS],
                    snippet=content[:_MAX_SNIPPET_CHARS],
                    rank=len(results) + 1,
                )
            )
            if len(results) >= limit:
                break
        return results
