import secrets

import structlog
from fastapi import Security, status
from fastapi.security import APIKeyHeader
from src.infrastructure.configs.settings import security_settings
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = structlog.stdlib.get_logger(__name__)

api_key_header_scheme = APIKeyHeader(
    name=security_settings.API_KEY_NAME, auto_error=False
)


class AuthenticationError(StarletteHTTPException):
    """Raised when request authentication fails against configured security policies."""

    def __init__(self, code: str, message: str):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=message,
            headers={"WWW-Authenticate": "ApiKey"},
        )
        self.code = code
        self.pointer = f"/headers/{security_settings.API_KEY_NAME}"


async def get_api_key(
    api_key_header: str | None = Security(api_key_header_scheme),
) -> str:
    """
    Validates the incoming API Key against configured security settings.
    Differentiates between missing key and invalid key according to Contract 06.
    """
    if api_key_header is None:
        await logger.awarning(
            "API Key authentication failed: missing header",
            header_name=security_settings.API_KEY_NAME,
        )
        raise AuthenticationError(
            code="API_KEY_MISSING",
            message=f"Missing mandatory authentication header '{security_settings.API_KEY_NAME}'",
        )

    if not secrets.compare_digest(api_key_header, security_settings.API_KEY):
        await logger.awarning(
            "API Key authentication failed: invalid key value",
            header_name=security_settings.API_KEY_NAME,
        )
        raise AuthenticationError(
            code="API_KEY_INVALID",
            message="The provided API Key is invalid",
        )

    return api_key_header
