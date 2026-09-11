class ApplicationError(Exception):
    """
    Base exception for all application-level errors.

    Pointer Concept and Responsibility:
    -----------------------------------
    A 'pointer' is an RFC 6901 JSON Pointer string (e.g., '/data/currentProblem',
    '/data/0/status', '/headers/X-API-Key') that identifies the exact location
    within the caller's request payload or headers that triggered the error.

    Responsibility:
    - Provides an unambiguous coordinate for upstream clients and frontends.
    - Enables client applications to pinpoint and highlight the offending input field.
    - In batch operations, indicates the specific array index (e.g., '/data/3') that failed.
    - Single-request internal errors: When an error is not caused by caller input
      (e.g., downstream provider connection failure), pointer is None and 'source'
      is completely omitted from the wire response.
    """

    def __init__(
        self,
        message: str,
        pointer: str | None = None,
        field_name: str | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.pointer = pointer
        self.field_name = field_name


class AggregateApplicationError(ApplicationError):
    """Container for multiple errors occurring in batch or multi-stage operations."""

    def __init__(
        self,
        errors: list[Exception],
        message: str = "Multiple errors occurred",
    ):
        super().__init__(message=message)
        self.errors = errors


class ApplicationAPIError(ApplicationError):
    """Base exception for external service API errors carrying HTTP/provider metadata."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        retry_after: float | None = None,
        pointer: str | None = None,
        field_name: str | None = None,
    ):
        super().__init__(message=message, pointer=pointer, field_name=field_name)
        self.status_code = status_code
        self.retry_after = retry_after


# region Embedder Exceptions
class EmbedderBaseError(ApplicationError):
    """Base exception for all embedding-related errors."""

    pass


class EmbedderConnectionError(EmbedderBaseError):
    """Raised when there is a network or timeout issue communicating with the embedder provider."""

    pass


class EmbedderAPIError(EmbedderBaseError, ApplicationAPIError):
    """Raised when the embedder provider returns an API error (e.g., rate limit, server error)."""

    pass


class EmbedderAuthenticationError(EmbedderBaseError):
    """Raised when authentication with the embedding provider fails (e.g., invalid API key)."""

    pass


class EmbedderContextLengthError(EmbedderBaseError):
    """Raised when text exceeds the model's maximum context length and truncate is set to False."""

    pass


class SparseEmbedderError(EmbedderBaseError):
    """Raised when sparse vector embedding generation fails."""

    pass


# endregion


# region LLM Exceptions
class LLMBaseError(ApplicationError):
    """Base exception for all LLM-related errors."""

    pass


class LLMConfigurationError(LLMBaseError):
    """Raised when an LLM provider configuration or API key is missing or invalid."""

    pass


class LLMConnectionError(LLMBaseError):
    """Raised when there is a network or timeout issue communicating with the LLM provider."""

    pass


class LLMAPIError(LLMBaseError, ApplicationAPIError):
    """Raised when the LLM provider returns an API error (e.g., bad request, rate limit, server error)."""

    pass


class LLMAuthenticationError(LLMBaseError):
    """Raised when authentication with the LLM provider fails."""

    pass


# endregion


# region Text Processing Exceptions
class TextNormalizationError(ApplicationError):
    """Raised when Persian text cleaning or normalization fails."""

    pass


# endregion
