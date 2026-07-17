import hashlib
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.errors import UnauthorizedError
from app.config import Settings, get_settings
from app.database import get_db_session
from app.database.engine import get_sessionmaker
from app.models import ApiKey
from app.repositories import api_key_repository
from app.services.crawl import CrawlProvider, get_crawl_provider
from app.services.search import SearchProvider, get_search_provider

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_research_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """The research service opens its own sessions across a long-running
    blocking wait (research_service.py), so it needs the sessionmaker
    itself, not a single request-scoped session — see ARCHITECTURE.md §5.1.
    """
    return get_sessionmaker()


def get_search_provider_dep(settings: SettingsDep) -> SearchProvider:
    return get_search_provider(settings)


def get_crawl_provider_dep(settings: SettingsDep) -> CrawlProvider:
    return get_crawl_provider(settings)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


async def require_api_key(
    settings: SettingsDep, session: DbSessionDep, authorization: str | None = Header(default=None)
) -> ApiKey | None:
    """Auth gate for every route except /health and /ready.

    Returns None, skipping the check entirely, when REQUIRE_API_KEY=false
    (Settings.require_api_key) — for a deployment that's already
    network-isolated to trusted callers. No router reads this dependency's
    return value; it exists purely to raise on failure.
    """
    if not settings.require_api_key:
        return None

    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedError("missing or malformed Authorization header")

    raw_key = authorization.removeprefix("Bearer ").strip()
    api_key = await api_key_repository.get_by_hash(session, hash_api_key(raw_key))
    if api_key is None:
        raise UnauthorizedError("invalid API key")
    return api_key
