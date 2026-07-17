from app.config import SearchProviderName, Settings, get_settings
from app.services.search.local_fts import search_local
from app.services.search.provider import SearchProvider, SearchResult
from app.services.search.searxng_provider import SearXNGSearchProvider


def get_search_provider(settings: Settings | None = None) -> SearchProvider:
    """Factory — the only place a concrete adapter class is named outside its own file."""
    settings = settings or get_settings()
    if settings.search_provider == SearchProviderName.SEARXNG:
        return SearXNGSearchProvider(base_url=settings.searxng_url)
    raise ValueError(f"Unknown search provider: {settings.search_provider}")


__all__ = ["SearchProvider", "SearchResult", "get_search_provider", "search_local"]
