from app.config import CrawlProviderName, Settings, get_settings
from app.services.crawl.crawl4ai_provider import Crawl4AICrawlProvider
from app.services.crawl.errors import CrawlBlockedError, CrawlFetchError
from app.services.crawl.provider import CrawlProvider, CrawlResult
from app.services.crawl.url_guard import guard_url
from app.services.proxy import get_crawl4ai_proxy_url


def get_crawl_provider(settings: Settings | None = None) -> CrawlProvider:
    """Factory — the only place a concrete adapter class is named outside its own file."""
    settings = settings or get_settings()
    if settings.crawl_provider == CrawlProviderName.CRAWL4AI:
        return Crawl4AICrawlProvider(
            base_url=settings.crawl4ai_url,
            fetch_timeout_seconds=settings.crawl_fetch_timeout_seconds,
            max_response_bytes=settings.crawl_max_response_bytes,
            api_token=settings.crawl4ai_api_token,
            proxy_url=get_crawl4ai_proxy_url(settings),
        )
    raise ValueError(f"Unknown crawl provider: {settings.crawl_provider}")


__all__ = [
    "CrawlProvider",
    "CrawlResult",
    "CrawlBlockedError",
    "CrawlFetchError",
    "get_crawl_provider",
    "guard_url",
]
