from app.config import SearchProviderName, Settings, get_settings
from app.services.search.composite_provider import CompositeSearchProvider, WeightedSource
from app.services.search.github_provider import GitHubSearchProvider
from app.services.search.local_fts import search_local
from app.services.search.provider import SearchProvider, SearchResult
from app.services.search.reddit_provider import RedditSearchProvider
from app.services.search.searxng_provider import SearXNGSearchProvider
from app.services.search.truth_social_provider import TruthSocialSearchProvider


def _build_composite(settings: Settings) -> SearchProvider:
    sources = [
        WeightedSource(
            name="searxng",
            provider=SearXNGSearchProvider(base_url=settings.searxng_url),
            weight=settings.search_searxng_weight,
            max_results=None,
        ),
    ]
    if settings.search_reddit_enabled:
        sources.append(
            WeightedSource(
                name="reddit",
                provider=RedditSearchProvider(
                    base_url=settings.search_reddit_base_url,
                    user_agent=settings.search_reddit_user_agent,
                ),
                weight=settings.search_reddit_weight,
                max_results=settings.search_reddit_max_results,
            )
        )
    if settings.search_github_enabled:
        sources.append(
            WeightedSource(
                name="github",
                provider=GitHubSearchProvider(
                    base_url=settings.search_github_base_url,
                    token=settings.search_github_token,
                ),
                weight=settings.search_github_weight,
                max_results=settings.search_github_max_results,
            )
        )
    if settings.search_truth_social_enabled:
        sources.append(
            WeightedSource(
                name="truth_social",
                provider=TruthSocialSearchProvider(base_url=settings.search_truth_social_base_url),
                weight=settings.search_truth_social_weight,
                max_results=settings.search_truth_social_max_results,
            )
        )
    # Next source (a news API, ...): same "if settings.search_<x>_enabled"
    # block, appended here — nothing else in this file changes.
    return CompositeSearchProvider(
        sources, per_source_timeout_seconds=settings.search_composite_timeout_seconds
    )


def get_search_provider(settings: Settings | None = None) -> SearchProvider:
    """Factory — the only place a concrete adapter class is named outside its own file."""
    settings = settings or get_settings()
    if settings.search_provider == SearchProviderName.SEARXNG:
        return SearXNGSearchProvider(base_url=settings.searxng_url)
    if settings.search_provider == SearchProviderName.COMPOSITE:
        return _build_composite(settings)
    raise ValueError(f"Unknown search provider: {settings.search_provider}")


__all__ = ["SearchProvider", "SearchResult", "get_search_provider", "search_local"]
