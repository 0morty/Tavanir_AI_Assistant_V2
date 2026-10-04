import pytest
from src.infrastructure.configs.settings import security_settings
from src.presentation.security import AuthenticationError, get_api_key


@pytest.mark.asyncio
async def test_get_api_key_valid():
    key = await get_api_key(security_settings.API_KEY)
    assert key == security_settings.API_KEY


@pytest.mark.asyncio
async def test_get_api_key_missing():
    with pytest.raises(AuthenticationError) as exc_info:
        await get_api_key(None)
    assert exc_info.value.code == "API_KEY_MISSING"
    assert exc_info.value.status_code == 401
    assert exc_info.value.headers.get("WWW-Authenticate") == "ApiKey"


@pytest.mark.asyncio
async def test_get_api_key_invalid():
    with pytest.raises(AuthenticationError) as exc_info:
        await get_api_key("wrong-secret-key")
    assert exc_info.value.code == "API_KEY_INVALID"
    assert exc_info.value.status_code == 401
    assert exc_info.value.headers.get("WWW-Authenticate") == "ApiKey"


@pytest.mark.asyncio
async def test_get_api_key_non_ascii_bytes():
    # Non-ASCII UTF-8 characters decoded by ASGI as Latin-1 must not crash with TypeError
    non_ascii_key = "نامعتبر-کلید"
    with pytest.raises(AuthenticationError) as exc_info:
        await get_api_key(non_ascii_key)
    assert exc_info.value.code == "API_KEY_INVALID"
    assert exc_info.value.status_code == 401
    assert exc_info.value.headers.get("WWW-Authenticate") == "ApiKey"
