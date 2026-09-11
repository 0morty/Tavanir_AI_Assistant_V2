import traceback
from dataclasses import dataclass
from typing import Any, cast

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from src.infrastructure.configs.settings import logging_settings
from src.presentation.schemas.responses import (
    DebugInfo,
    ErrorItem,
    ErrorResponse,
    ErrorSource,
)
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.application.exceptions import (
    AggregateApplicationError,
    ApplicationAPIError,
    ApplicationError,
    EmbedderAPIError,
    EmbedderAuthenticationError,
    EmbedderBaseError,
    EmbedderConnectionError,
    EmbedderContextLengthError,
    LLMAPIError,
    LLMAuthenticationError,
    LLMBaseError,
    LLMConfigurationError,
    LLMConnectionError,
)
from src.domain.exceptions import (
    DomainError,
    EntityNotFoundError,
    InvalidShamsiDateFormatError,
    InvalidSparseVectorError,
    InvalidSuggestionStatusError,
    ParentChildIntegrityError,
    VectorCollectionProvisioningError,
    VectorPayloadValidationError,
    VectorSearchError,
    VectorStorageError,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ErrorSpec:
    """Specification mapping an exception type to an HTTP status, internal code, and default pointer."""

    status_code: int
    code: str
    default_pointer: str | None = None


# Declarative registry mapping concrete exceptions to their contract specifications
ERROR_REGISTRY: dict[type[Exception], ErrorSpec] = {
    # --- Domain Exceptions ---
    InvalidShamsiDateFormatError: ErrorSpec(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="INVALID_SHAMSI_DATE",
        default_pointer="/data/date",
    ),
    InvalidSuggestionStatusError: ErrorSpec(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="INVALID_SUGGESTION_STATUS",
        default_pointer="/data/status",
    ),
    InvalidSparseVectorError: ErrorSpec(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="VALIDATION_ERROR",
        default_pointer="/data",
    ),
    VectorPayloadValidationError: ErrorSpec(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="VALIDATION_ERROR",
        default_pointer="/data",
    ),
    ParentChildIntegrityError: ErrorSpec(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="VALIDATION_ERROR",
        default_pointer="/data",
    ),
    EntityNotFoundError: ErrorSpec(
        status_code=status.HTTP_404_NOT_FOUND,
        code="SUGGESTION_NOT_FOUND",
        default_pointer=None,
    ),
    VectorStorageError: ErrorSpec(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="RETRIEVAL_FAILED",
        default_pointer=None,
    ),
    VectorSearchError: ErrorSpec(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="RETRIEVAL_FAILED",
        default_pointer=None,
    ),
    VectorCollectionProvisioningError: ErrorSpec(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="RETRIEVAL_FAILED",
        default_pointer=None,
    ),
    # --- Application Exceptions ---
    EmbedderConnectionError: ErrorSpec(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        code="EMBEDDER_CONNECTION_FAILED",
        default_pointer=None,
    ),
    EmbedderAuthenticationError: ErrorSpec(
        status_code=status.HTTP_401_UNAUTHORIZED,
        code="EMBEDDER_AUTH_FAILED",
        default_pointer="/headers/X-API-Key",
    ),
    EmbedderContextLengthError: ErrorSpec(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="EMBEDDER_CONTEXT_LENGTH",
        default_pointer="/data",
    ),
    EmbedderAPIError: ErrorSpec(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="EMBEDDING_FAILED",
        default_pointer=None,
    ),
    EmbedderBaseError: ErrorSpec(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="EMBEDDING_FAILED",
        default_pointer=None,
    ),
    LLMConfigurationError: ErrorSpec(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="LLM_CONFIGURATION_ERROR",
        default_pointer=None,
    ),
    LLMConnectionError: ErrorSpec(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        code="LLM_CONNECTION_FAILED",
        default_pointer=None,
    ),
    LLMAPIError: ErrorSpec(
        status_code=status.HTTP_502_BAD_GATEWAY,
        code="LLM_API_ERROR",
        default_pointer=None,
    ),
    LLMAuthenticationError: ErrorSpec(
        status_code=status.HTTP_401_UNAUTHORIZED,
        code="LLM_AUTH_FAILED",
        default_pointer="/headers/X-API-Key",
    ),
    LLMBaseError: ErrorSpec(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="LLM_CONFIGURATION_ERROR",
        default_pointer=None,
    ),
    ApplicationAPIError: ErrorSpec(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="INTERNAL_ERROR",
        default_pointer=None,
    ),
}


def resolve_error_spec(exc: Exception) -> ErrorSpec:
    """
    Resolves the ErrorSpec for an exception instance.
    Checks for an exact type match first, then inspects the MRO hierarchy,
    and falls back to broad category defaults.
    """
    exc_type = type(exc)
    if exc_type in ERROR_REGISTRY:
        return ERROR_REGISTRY[exc_type]

    for registered_cls, spec in ERROR_REGISTRY.items():
        if isinstance(exc, registered_cls):
            return spec

    if isinstance(exc, DomainError):
        return ErrorSpec(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="DOMAIN_RULE_VIOLATION",
            default_pointer=None,
        )

    if isinstance(exc, ApplicationError):
        return ErrorSpec(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_ERROR",
            default_pointer=None,
        )

    return ErrorSpec(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="INTERNAL_ERROR",
        default_pointer=None,
    )


def build_debug_info(exc: Exception) -> DebugInfo | None:
    """Builds DebugInfo in non-production environments; returns None in production."""
    is_production = logging_settings.ENVIRONMENT.strip().lower() == "production"
    if is_production:
        return None

    cause_msg = str(exc.__cause__) if exc.__cause__ else None
    return DebugInfo(
        exception=exc.__class__.__name__,
        cause=cause_msg or str(exc),
        stack_trace=traceback.format_exc(),
    )


def extract_pointer(exc: Exception, default_pointer: str | None) -> str | None:
    """Extracts explicit pointer from exception, falls back to default, or returns None."""
    explicit_pointer = getattr(exc, "pointer", None)
    if explicit_pointer:
        return explicit_pointer

    field_name = getattr(exc, "field_name", None)
    if field_name:
        return f"/data/{field_name}"

    return default_pointer


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Transforms Pydantic validation errors into JSON:API error envelopes with RFC 6901 pointers."""
    error_items: list[ErrorItem] = []

    for err in exc.errors():
        loc_parts = [str(part) for part in err.get("loc", []) if part != "body"]
        pointer = f"/data/{'/'.join(loc_parts)}" if loc_parts else "/data"

        err_type = err.get("type", "")
        code = (
            "MISSING_REQUIRED_FIELD"
            if "missing" in err_type
            else "VALIDATION_ERROR"
        )

        error_items.append(
            ErrorItem(
                status=status.HTTP_422_UNPROCESSABLE_CONTENT,
                code=code,
                source=ErrorSource(pointer=pointer),
                debug=DebugInfo(
                    exception="RequestValidationError",
                    cause=err.get("msg", "Validation error"),
                    stack_trace=None,
                )
                if logging_settings.ENVIRONMENT.strip().lower() != "production"
                else None,
            )
        )

    await logger.awarning(
        "Request validation failed",
        path=request.url.path,
        method=request.method,
        error_count=len(error_items),
    )

    response_payload = ErrorResponse.create_multi(errors=error_items)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=response_payload.model_dump(by_alias=True, exclude_none=True),
    )


async def aggregate_application_exception_handler(
    request: Request, exc: AggregateApplicationError
) -> JSONResponse:
    """Handles multi-error batch exceptions, returning HTTP 400 with indexed error items."""
    error_items: list[ErrorItem] = []

    for index, sub_exc in enumerate(exc.errors):
        spec = resolve_error_spec(sub_exc)
        pointer = extract_pointer(sub_exc, default_pointer=f"/data/{index}")
        source = ErrorSource(pointer=pointer) if pointer else None
        debug = build_debug_info(sub_exc)

        error_items.append(
            ErrorItem(
                status=spec.status_code,
                code=spec.code,
                source=source,
                debug=debug,
            )
        )

    await logger.aerror(
        "Batch aggregate operation encountered failures",
        path=request.url.path,
        error_count=len(error_items),
    )

    response_payload = ErrorResponse.create_multi(errors=error_items)
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=response_payload.model_dump(by_alias=True, exclude_none=True),
    )


async def domain_exception_handler(
    request: Request, exc: DomainError
) -> JSONResponse:
    """Handles domain-level business rule violations."""
    spec = resolve_error_spec(exc)
    pointer = extract_pointer(exc, spec.default_pointer)
    debug = build_debug_info(exc)

    await logger.awarning(
        "Domain rule violation",
        path=request.url.path,
        exception=exc.__class__.__name__,
        code=spec.code,
        message=str(exc),
    )

    response_payload = ErrorResponse.create_single(
        status_code=spec.status_code,
        code=spec.code,
        pointer=pointer,
        debug=debug,
    )
    return JSONResponse(
        status_code=spec.status_code,
        content=response_payload.model_dump(by_alias=True, exclude_none=True),
    )


async def application_exception_handler(
    request: Request, exc: ApplicationError
) -> JSONResponse:
    """Handles application use-case and external provider exceptions."""
    spec = resolve_error_spec(exc)
    pointer = extract_pointer(exc, spec.default_pointer)
    debug = build_debug_info(exc)

    await logger.aerror(
        "Application error encountered",
        path=request.url.path,
        exception=exc.__class__.__name__,
        code=spec.code,
        message=str(exc),
    )

    response_payload = ErrorResponse.create_single(
        status_code=spec.status_code,
        code=spec.code,
        pointer=pointer,
        debug=debug,
    )
    return JSONResponse(
        status_code=spec.status_code,
        content=response_payload.model_dump(by_alias=True, exclude_none=True),
    )


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Intercepts standard HTTP exceptions (404, 405, etc.) and wraps them in JSON:API envelope."""
    if hasattr(exc, "code"):
        code = exc.code
        pointer = getattr(exc, "pointer", None)
    else:
        status_to_code = {
            status.HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
            status.HTTP_403_FORBIDDEN: "FORBIDDEN",
            status.HTTP_404_NOT_FOUND: "RESOURCE_NOT_FOUND",
            status.HTTP_405_METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
            status.HTTP_429_TOO_MANY_REQUESTS: "RATE_LIMITED",
        }
        code = status_to_code.get(exc.status_code, "HTTP_ERROR")
        pointer = None

    debug = build_debug_info(exc)

    response_payload = ErrorResponse.create_single(
        status_code=exc.status_code,
        code=code,
        pointer=pointer,
        debug=debug,
    )
    return JSONResponse(
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
        content=response_payload.model_dump(by_alias=True, exclude_none=True),
    )


async def global_unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """
    Global catch-all for any uncaught runtime exceptions.
    Logs the full traceback via structlog so Vector automatically streams it to OpenObserve.
    """
    await logger.aerror(
        "Unhandled server exception",
        path=request.url.path,
        method=request.method,
        exception=exc.__class__.__name__,
        error=str(exc),
        exc_info=True,
    )

    debug = build_debug_info(exc)
    response_payload = ErrorResponse.create_single(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="INTERNAL_ERROR",
        pointer=None,
        debug=debug,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=response_payload.model_dump(by_alias=True, exclude_none=True),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Registers all centralized JSON:API exception handlers on the FastAPI application."""
    app.add_exception_handler(
        RequestValidationError, cast(Any, validation_exception_handler)
    )
    app.add_exception_handler(
        AggregateApplicationError, cast(Any, aggregate_application_exception_handler)
    )
    app.add_exception_handler(
        DomainError, cast(Any, domain_exception_handler)
    )
    app.add_exception_handler(
        ApplicationError, cast(Any, application_exception_handler)
    )
    app.add_exception_handler(
        StarletteHTTPException, cast(Any, http_exception_handler)
    )
    app.add_exception_handler(Exception, global_unhandled_exception_handler)
