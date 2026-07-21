import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApiKey, ApiKeyStatus


async def get_by_hash(session: AsyncSession, key_hash: str) -> ApiKey | None:
    result = await session.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
    return result.scalar_one_or_none()


async def get_by_id(session: AsyncSession, key_id: uuid.UUID) -> ApiKey | None:
    return await session.get(ApiKey, key_id)


async def list_all(session: AsyncSession) -> list[ApiKey]:
    result = await session.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))
    return list(result.scalars().all())


async def create(
    session: AsyncSession,
    *,
    key_hash: str,
    label: str,
    rate_limit_per_minute: int,
    expires_at: datetime | None,
) -> ApiKey:
    api_key = ApiKey(
        key_hash=key_hash,
        label=label,
        rate_limit_per_minute=rate_limit_per_minute,
        expires_at=expires_at,
    )
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)
    return api_key


async def update_status(session: AsyncSession, api_key: ApiKey, status: ApiKeyStatus) -> ApiKey:
    api_key.status = status
    await session.commit()
    await session.refresh(api_key)
    return api_key


async def update_expiry(
    session: AsyncSession, api_key: ApiKey, expires_at: datetime | None
) -> ApiKey:
    api_key.expires_at = expires_at
    await session.commit()
    await session.refresh(api_key)
    return api_key


async def delete(session: AsyncSession, api_key: ApiKey) -> None:
    await session.delete(api_key)
    await session.commit()
