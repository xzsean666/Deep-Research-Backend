import hashlib
import secrets
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.errors import UnauthorizedError
from app.config import Settings, get_settings
from app.database import get_db_session
from app.database.engine import get_sessionmaker
from app.models import ApiKey, ApiKeyStatus
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
    if api_key.status != ApiKeyStatus.ACTIVE:
        raise UnauthorizedError("API key is disabled")
    if api_key.expires_at is not None and api_key.expires_at <= datetime.now(UTC):
        raise UnauthorizedError("API key has expired")
    return api_key


async def require_admin(
    settings: SettingsDep, authorization: str | None = Header(default=None)
) -> None:
    """Auth gate for /admin/* (app/api/routers/admin.py).

    A separate secret from REQUIRE_API_KEY/api_keys — this manages *those*
    keys, so it can't be one of them. Fails closed: an unset
    ADMIN_API_SECRET disables the admin API entirely rather than leaving it
    open, the opposite of require_api_key's REQUIRE_API_KEY=false bypass.
    secrets.compare_digest is used (not the hash-indexed lookup
    require_api_key uses) because this compares directly against a single
    configured secret, not a DB-indexed value.
    """
    if not settings.admin_api_secret:
        raise UnauthorizedError("admin API is disabled (ADMIN_API_SECRET not configured)")

    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedError("missing or malformed Authorization header")

    provided = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(provided, settings.admin_api_secret):
        raise UnauthorizedError("invalid admin secret")
