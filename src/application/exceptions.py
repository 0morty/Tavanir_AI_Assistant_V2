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


class ChunkSummarizationError(LLMBaseError):
    """Raised when batched LLM chunk summarization cannot produce a strict 1:1 mapping.

    The model response could not be split back into exactly one summary per
    input chunk (in order) even after the configured retry attempts, so the
    caller must not continue with a partially-summarized collection.
    """

    pass


# endregion


# region Text Processing Exceptions
class TextNormalizationError(ApplicationError):
    """Raised when Persian text cleaning or normalization fails."""

    pass


# endregion


# region Tokenizer Exceptions
class TokenizerError(ApplicationError):
    """Raised when LLM text tokenization or decoding fails."""

    pass


# endregion


# region Reranker Exceptions
class RerankerBaseError(ApplicationError):
    """Base exception for all reranker failures."""

    pass


class RerankerValidationError(RerankerBaseError):
    """Raised when reranker inputs (e.g. query, top_n) fail validation preconditions."""

    pass


class RerankerConfigurationError(RerankerBaseError):
    """Raised when reranker is misconfigured, unauthorized (401/403), or model identity mismatches."""

    pass


class RerankerConnectionError(RerankerBaseError):
    """Raised on network connection failure, transport timeout, or DNS resolution failure."""

    pass


class RerankerOverloadedError(RerankerBaseError, ApplicationAPIError):
    """Raised when TEI server returns 429 Too Many Requests or is persistently overloaded."""

    pass


class RerankerInputLimitError(RerankerBaseError, ApplicationAPIError):
    """Raised when request payload or token pair length exceeds server capacity (413/422)."""

    pass


class RerankerAPIError(RerankerBaseError, ApplicationAPIError):
    """Raised when the reranker provider returns an unrecoverable 5xx server error."""

    pass


class RerankerProtocolError(RerankerBaseError):
    """Raised when TEI response is malformed, has missing/duplicate indices, or non-finite logits."""

    pass


# endregion
