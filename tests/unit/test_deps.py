from datetime import UTC, datetime, timedelta

import pytest

from app.api.deps import require_admin, require_api_key
from app.api.errors import UnauthorizedError
from app.models import ApiKey, ApiKeyStatus
from app.repositories import api_key_repository


async def test_require_api_key_enabled_by_default_rejects_missing_header(settings):
    assert settings.require_api_key is True
    with pytest.raises(UnauthorizedError):
        await require_api_key(settings, session=None, authorization=None)


async def test_require_api_key_disabled_skips_the_check_entirely(settings):
    open_settings = settings.model_copy(update={"require_api_key": False})

    result = await require_api_key(open_settings, session=None, authorization=None)

    assert result is None


async def test_require_api_key_rejects_disabled_key(settings, monkeypatch):
    fake_key = ApiKey(
        key_hash="x", label="test", rate_limit_per_minute=60, status=ApiKeyStatus.DISABLED
    )

    async def fake_get_by_hash(session, key_hash):
        return fake_key

    monkeypatch.setattr(api_key_repository, "get_by_hash", fake_get_by_hash)

    with pytest.raises(UnauthorizedError):
        await require_api_key(settings, session=None, authorization="Bearer whatever")


async def test_require_api_key_rejects_expired_key(settings, monkeypatch):
    fake_key = ApiKey(
        key_hash="x",
        label="test",
        rate_limit_per_minute=60,
        status=ApiKeyStatus.ACTIVE,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )

    async def fake_get_by_hash(session, key_hash):
        return fake_key

    monkeypatch.setattr(api_key_repository, "get_by_hash", fake_get_by_hash)

    with pytest.raises(UnauthorizedError):
        await require_api_key(settings, session=None, authorization="Bearer whatever")


async def test_require_api_key_accepts_active_permanent_key(settings, monkeypatch):
    fake_key = ApiKey(
        key_hash="x",
        label="test",
        rate_limit_per_minute=60,
        status=ApiKeyStatus.ACTIVE,
        expires_at=None,
    )

    async def fake_get_by_hash(session, key_hash):
        return fake_key

    monkeypatch.setattr(api_key_repository, "get_by_hash", fake_get_by_hash)

    result = await require_api_key(settings, session=None, authorization="Bearer whatever")

    assert result is fake_key


async def test_require_api_key_accepts_active_not_yet_expired_key(settings, monkeypatch):
    fake_key = ApiKey(
        key_hash="x",
        label="test",
        rate_limit_per_minute=60,
        status=ApiKeyStatus.ACTIVE,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )

    async def fake_get_by_hash(session, key_hash):
        return fake_key

    monkeypatch.setattr(api_key_repository, "get_by_hash", fake_get_by_hash)

    result = await require_api_key(settings, session=None, authorization="Bearer whatever")

    assert result is fake_key


async def test_require_admin_rejects_when_secret_unconfigured(settings):
    assert settings.admin_api_secret == ""
    with pytest.raises(UnauthorizedError):
        await require_admin(settings, authorization="Bearer anything")


async def test_require_admin_rejects_missing_header(settings):
    configured = settings.model_copy(update={"admin_api_secret": "correct-secret"})
    with pytest.raises(UnauthorizedError):
        await require_admin(configured, authorization=None)


async def test_require_admin_rejects_wrong_secret(settings):
    configured = settings.model_copy(update={"admin_api_secret": "correct-secret"})
    with pytest.raises(UnauthorizedError):
        await require_admin(configured, authorization="Bearer wrong-secret")


async def test_require_admin_accepts_correct_secret(settings):
    configured = settings.model_copy(update={"admin_api_secret": "correct-secret"})
    result = await require_admin(configured, authorization="Bearer correct-secret")
    assert result is None
