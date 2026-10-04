import secrets

import structlog
from fastapi import Request, Security, status
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
    request: Request,
    api_key_header: str | None = Security(api_key_header_scheme),
) -> str:
    """
    Validates the incoming API Key against configured security settings.
    Differentiates between missing key and invalid key according to Contract 06.
    Ensures duplicate headers with contradictory credentials are authenticated strictly.
    """
    if request is not None and hasattr(request, "headers"):
        header_values = request.headers.getlist(security_settings.API_KEY_NAME)
    elif isinstance(request, str):
        header_values = [request]
    elif isinstance(api_key_header, str):
        header_values = [api_key_header]
    else:
        header_values = []

    if not header_values:
        await logger.awarning(
            "API Key authentication failed: missing header",
            header_name=security_settings.API_KEY_NAME,
        )
        raise AuthenticationError(
            code="API_KEY_MISSING",
            message=f"Missing mandatory authentication header '{security_settings.API_KEY_NAME}'",
        )

    for val in header_values:
        try:
            is_valid = secrets.compare_digest(val, security_settings.API_KEY)
        except TypeError:
            is_valid = False

        if not is_valid:
            await logger.awarning(
                "API Key authentication failed: invalid key value",
                header_name=security_settings.API_KEY_NAME,
            )
            raise AuthenticationError(
                code="API_KEY_INVALID",
                message="The provided API Key is invalid",
            )

    return header_values[0]
