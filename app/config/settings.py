from enum import StrEnum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class SearchProviderName(StrEnum):
    SEARXNG = "searxng"
    COMPOSITE = "composite"


class CrawlProviderName(StrEnum):
    CRAWL4AI = "crawl4ai"


class ExecutionMode(StrEnum):
    BLOCKING = "blocking"
    BACKGROUND = "background"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str

    search_provider: SearchProviderName = SearchProviderName.SEARXNG
    searxng_url: str

    # Only read when search_provider == COMPOSITE — an unconfigured
    # deployment never constructs these providers, so behavior is
    # unchanged unless an operator opts in.
    search_searxng_weight: float = 1.0
    search_reddit_enabled: bool = False
    search_reddit_weight: float = 0.4
    search_reddit_max_results: int = 2
    search_reddit_base_url: str = "https://www.reddit.com"
    search_reddit_user_agent: str = "DeepResearchBackend/1.0"

    search_github_enabled: bool = False
    search_github_weight: float = 0.6
    search_github_max_results: int = 3
    search_github_base_url: str = "https://api.github.com"
    # Optional — unauthenticated search works (10 req/min GitHub-enforced
    # limit); a token raises that to 30 req/min. Empty means unauthenticated.
    search_github_token: str = ""

    # Trump's Truth Social feed specifically — relevant only for markets
    # about his statements/policy. Kept at a low weight and small cap by
    # design so an unrelated market can't be drowned in it; see
    # truth_social_provider.py for why this isn't a primary source.
    search_truth_social_enabled: bool = False
    search_truth_social_weight: float = 0.2
    search_truth_social_max_results: int = 2
    search_truth_social_base_url: str = "https://truthsocial.com"

    search_composite_timeout_seconds: float = 15.0

    crawl_provider: CrawlProviderName = CrawlProviderName.CRAWL4AI
    crawl4ai_url: str
    # Crawl4AI refuses to bind beyond loopback without this (see
    # vendor/crawl4ai/deploy/docker/entrypoint.sh) — required once it's
    # reached over the docker network rather than from its own container.
    # Sent as `Authorization: Bearer <token>` by Crawl4AICrawlProvider.
    crawl4ai_api_token: str

    # Secure by default. Set to false only for a deployment that's already
    # network-isolated (firewalled to trusted callers) — disabling this
    # does not add any other access control. SPEC.md §1.
    require_api_key: bool = True

    research_execution_mode_default: ExecutionMode = ExecutionMode.BLOCKING

    crawl_max_response_bytes: int = 5_000_000
    crawl_fetch_timeout_seconds: int = 20
    crawl_per_domain_concurrency: int = 2

    job_max_attempts: int = 3
    worker_poll_interval_seconds: float = 1

    ttl_docs_days: int = 30
    ttl_github_days: int = 7
    ttl_blog_days: int = 7
    ttl_news_hours: int = 6


@lru_cache
def get_settings() -> Settings:
    return Settings()
