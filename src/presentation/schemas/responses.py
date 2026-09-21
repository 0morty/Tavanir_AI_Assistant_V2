from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

T = TypeVar("T")


class BaseResponseModel(BaseModel):
    """Base model enforcing camelCase aliases and name population across all responses."""

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )


class ErrorSource(BaseResponseModel):
    """Identifies the exact location of the error in the request payload, headers, or parameters."""

    pointer: str = Field(
        ...,
        description="RFC 6901 JSON pointer to the offending field or resource (e.g., '/data/title').",
    )


class DebugInfo(BaseResponseModel):
    """Detailed exception metadata for development/staging diagnostics. Omitted in production."""

    exception: str = Field(..., description="Exception class name.")
    cause: str | None = Field(
        default=None, description="Underlying root cause message."
    )
    stack_trace: str | None = Field(
        default=None, description="Formatted Python stack trace."
    )


class ErrorItem(BaseResponseModel):
    """Represents a single discrete error adhering to JSON:API specification."""

    status: int = Field(
        ..., description="HTTP status code corresponding to this error."
    )
    code: str = Field(
        ...,
        description="Authoritative machine-readable error code in SCREAMING_SNAKE_CASE.",
    )
    source: ErrorSource | None = Field(
        default=None,
        description="Source coordinate pointing to the offending field. Omitted for single internal errors.",
    )
    debug: DebugInfo | None = Field(
        default=None,
        description="Debug details, present only in non-production environments.",
    )


class ErrorResponse(BaseResponseModel):
    """The canonical top-level JSON:API error envelope."""

    errors: list[ErrorItem] = Field(
        ..., description="List of errors associated with the request failure."
    )

    @classmethod
    def create_single(
        cls,
        status_code: int,
        code: str,
        pointer: str | None = None,
        debug: DebugInfo | None = None,
    ) -> "ErrorResponse":
        """Factory helper to build an ErrorResponse containing a single error."""
        source = ErrorSource(pointer=pointer) if pointer is not None else None
        return cls(
            errors=[
                ErrorItem(
                    status=status_code,
                    code=code,
                    source=source,
                    debug=debug,
                )
            ]
        )

    @classmethod
    def create_multi(cls, errors: list[ErrorItem]) -> "ErrorResponse":
        """Factory helper to build an ErrorResponse containing multiple errors."""
        return cls(errors=errors)


class SuccessResponse(BaseResponseModel, Generic[T]):
    """The canonical top-level JSON:API success envelope."""

    status: int = Field(default=200, description="HTTP status code.")
    data: T = Field(..., description="Response payload data.")

    @classmethod
    def create(cls, data: T, status: int = 200) -> "SuccessResponse[T]":
        """Factory helper to construct a standardized SuccessResponse."""
        return cls(status=status, data=data)


class PartialSuccessResponse(BaseResponseModel, Generic[T]):
    """Standardized top-level JSON:API envelope for batch operations returning HTTP 207 Multi-Status."""

    status: int = Field(default=207, description="HTTP status code (207 Multi-Status).")
    data: list[T] = Field(
        default_factory=list, description="List of successfully processed items."
    )
    errors: list[ErrorItem] = Field(
        default_factory=list, description="List of discrete errors for failed items."
    )

    @classmethod
    def create(
        cls,
        data: list[T],
        errors: list[ErrorItem],
        status: int = 207,
    ) -> "PartialSuccessResponse[T]":
        """Factory helper to construct a standardized PartialSuccessResponse."""
        return cls(status=status, data=data, errors=errors)
