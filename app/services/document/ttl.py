from datetime import datetime, timedelta
from urllib.parse import urlsplit

from app.config import Settings
from app.models import SourceType

# ARCHITECTURE.md §6.2 — heuristic detection, cheapest signal first.
_GITHUB_HOSTS = frozenset({"github.com", "raw.githubusercontent.com", "gist.github.com"})
_NEWS_HOSTS = frozenset(
    {
        "news.google.com",
        "reuters.com",
        "apnews.com",
        "bbc.com",
        "cnn.com",
        "nytimes.com",
    }
)
_DOCS_HOST_MARKERS = ("docs.", "readthedocs.io")


def classify_source_type(url: str) -> SourceType:
    host = (urlsplit(url).hostname or "").lower()
    bare_host = host.removeprefix("www.")

    if bare_host in _GITHUB_HOSTS or host.endswith(".github.com"):
        return SourceType.GITHUB
    if bare_host in _NEWS_HOSTS or host.endswith(".news.google.com"):
        return SourceType.NEWS
    if any(marker in host for marker in _DOCS_HOST_MARKERS):
        return SourceType.DOCS

    # Default fallback per ARCHITECTURE.md §6.2 — most of the web is this.
    return SourceType.BLOG


def compute_expires_at(
    source_type: SourceType, fetched_at: datetime, settings: Settings
) -> datetime:
    ttl_by_type = {
        SourceType.DOCS: timedelta(days=settings.ttl_docs_days),
        SourceType.GITHUB: timedelta(days=settings.ttl_github_days),
        SourceType.BLOG: timedelta(days=settings.ttl_blog_days),
        SourceType.NEWS: timedelta(hours=settings.ttl_news_hours),
        SourceType.OTHER: timedelta(days=settings.ttl_blog_days),
    }
    return fetched_at + ttl_by_type[source_type]
