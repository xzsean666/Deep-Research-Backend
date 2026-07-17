import pytest

from app.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://test:test@localhost:5432/test",
        searxng_url="http://searxng.test",
        crawl4ai_url="http://crawl4ai.test",
        crawl4ai_api_token="test-token",
    )
