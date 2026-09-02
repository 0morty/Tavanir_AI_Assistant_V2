class ApplicationError(Exception):
    """Base exception for all application-level errors."""

    pass


class ApplicationAPIError(ApplicationError):
    """Base exception for external service API errors carrying HTTP/provider metadata."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        retry_after: float | None = None,
    ):
        super().__init__(message)
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
