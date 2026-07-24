import math
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
# structured JSON (not HTML scraping).
#
# BUG (confirmed live 2026-07-22): this endpoint's `q` parameter is not
# honored server-side — it returns the same ~16 most-recent posts (sorted by
# `sort=date`) no matter what `q` is, including for queries with nothing to
# do with Trump (verified: identical results for weather, sports, and
# shipping-traffic queries). Every non-Trump-specific query falls through to
# this archive, since the primary search above 403s or comes up empty for
# them — so without a client-side relevance check, this source was silently
# returning unrelated posts as "evidence" for almost every query that
# reached it, indistinguishable downstream from genuine results. See
# `_is_relevant` — results are dropped unless enough non-generic tokens
# overlap with the query. A single shared token was tried first and wasn't
# enough on its own: confirmed live twice more, a bare year ("2026") and a
# bare month name ("july") each separately let an unrelated post through
# purely because nearly every post and every market question currently in
# this corpus is dated 2026/July — hence excluding pure numbers and
# requiring 2 overlapping tokens for longer queries.
_FACTBASE_ARCHIVE_URL = "https://rollcall.com/wp-json/factbase/v1/twitter"
_FACTBASE_REFERER = "https://rollcall.com/factbase-twitter/"

# Stopwords excluded from the relevance check below: English function words
# plus a few terms generic enough to appear in almost any prediction-market
# question, which would otherwise let an unrelated post pass a naive overlap
# check.
_RELEVANCE_STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "for",
        "by", "with", "will", "would", "could", "should", "be", "is", "are",
        "was", "were", "this", "that", "from", "into", "onto", "over",
        "under", "before", "after", "have", "has", "had", "market",
        "prediction", "polymarket",
    }
)
_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")


def _relevance_tokens(text: str) -> set[str]:
    # Purely-numeric tokens (years, day-of-month numbers) are excluded: in
    # this corpus almost every post and every market question is dated
    # 2026, so a bare "2026" is enough to make an unrelated post pass a
    # naive overlap check (confirmed live: this is exactly how "Ankara
    # highest temperature July 23 2026" matched a drug-tariff post dated
    # "August 1st, 2026" — the only shared token was the year). A word that
    # mixes letters and digits (e.g. a temperature like "30c") still counts,
    # since that combination is genuinely distinctive.
    return {
        word
        for word in (match.group(0).lower() for match in _TOKEN_RE.finditer(text))
        if len(word) >= 3 and word not in _RELEVANCE_STOPWORDS and not word.isdigit()
    }


def _is_relevant(query: str, text: str) -> bool:
    """Whether `text` shares enough non-generic tokens with `query` to be
    plausibly about the same thing.

    A minimal topical check, not full relevance ranking — it only needs to
    catch the case above: a result with zero real connection to what was
    asked. Requiring just *one* shared token isn't enough on its own: a
    calendar word like a month name is common enough (confirmed live: an
    unrelated post mentioning "July Fourth Weekend" matched a query about
    "highest temperature ... July 23" purely on "july") that single-token
    overlap still lets an unrelated post through. Requiring at least two
    (for queries with more than a couple of tokens) needs a second,
    independent coincidence, which is far less likely by chance. An
    empty/all-stopword query can't be checked meaningfully, so it passes
    everything through rather than filtering blind.
    """
    query_tokens = _relevance_tokens(query)
    if not query_tokens:
        return True
    required_overlap = min(2, max(1, math.ceil(len(query_tokens) / 3)))
    overlap = query_tokens & _relevance_tokens(text)
    return len(overlap) >= required_overlap


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
    live to be what's actually reachable from this deployment's network,
    but see `_is_relevant`: the archive ignores its own query parameter, so
    its results are filtered for topical overlap with the query before
    being returned.
    """

    def __init__(
        self,
        base_url: str = "https://truthsocial.com",
        user_agent: str = _DEFAULT_USER_AGENT,
        proxy: str | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(
            timeout=10, headers={"Accept": "application/json", "User-Agent": user_agent}, proxy=proxy
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
            if not _is_relevant(query, content):
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
