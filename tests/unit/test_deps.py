import pytest

from app.api.deps import require_api_key
from app.api.errors import UnauthorizedError


async def test_require_api_key_enabled_by_default_rejects_missing_header(settings):
    assert settings.require_api_key is True
    with pytest.raises(UnauthorizedError):
        await require_api_key(settings, session=None, authorization=None)


async def test_require_api_key_disabled_skips_the_check_entirely(settings):
    open_settings = settings.model_copy(update={"require_api_key": False})

    result = await require_api_key(open_settings, session=None, authorization=None)

    assert result is None
