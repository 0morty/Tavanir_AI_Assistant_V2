class DomainError(Exception):
    """
    Base exception for all domain-level business rule violations.

    Pointer Concept and Responsibility:
    -----------------------------------
    A 'pointer' is an RFC 6901 JSON Pointer string (e.g., '/data/currentProblem',
    '/data/0/status', '/headers/X-API-Key') that identifies the exact location
    within the caller's request payload or headers that triggered the error.

    Responsibility:
    - Provides an unambiguous coordinate for upstream clients and frontends.
    - Enables client applications (e.g., React / Blazor forms) to automatically
      pinpoint and highlight the offending input field in red without parsing text messages.
    - In batch operations, indicates the specific array index (e.g., '/data/3') that failed.
    - Single-request internal errors: When an error is not caused by the caller's input
      (e.g., server crash or provider timeout), pointer is None and the 'source' field
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


class InvalidShamsiDateFormatError(DomainError):
    """Raised when a date string does not conform to the expected Shamsi date format."""

    pass


class InvalidSuggestionStatusError(DomainError):
    """Raised when an unrecognized suggestion status value or ID is encountered."""

    pass


class InvalidSparseVectorError(DomainError):
    pass


# region Vector Store Exceptions
class VectorStorageError(DomainError):
    """Raised when write, upsert, or payload modification operations in the vector store fail."""

    pass


class VectorSearchError(DomainError):
    """Raised when query or hybrid retrieval operations in the vector store fail."""

    pass


class VectorCollectionProvisioningError(DomainError):
    """Raised when collection initialization, indexing configuration, or schema verification fails."""

    pass


class VectorPayloadValidationError(DomainError):
    """Raised when chunk metadata or attributes violate expected domain invariants."""

    pass


# endregion


# region Relational / Suggestion Hydration Exceptions
class EntityNotFoundError(DomainError):
    """Raised when a parent entity requested during SQL hydration does not exist."""

    pass


class ParentChildIntegrityError(DomainError):
    """Raised when a child chunk references a non-existent or invalid parent_id."""

    pass


# endregion


# region Chunking Exceptions
class ChunkingError(DomainError):
    """Base domain exception for document decomposition failures."""

    pass


class SuggestionChunkingError(ChunkingError):
    """Raised when decomposing a Suggestion entity into vector chunks fails."""

    pass


class RegulatoryChunkingError(ChunkingError):
    """Raised when decomposing a RegulatoryDocument into vector chunks fails."""

    pass


# endregion


class InvalidSuggestionContentError(DomainError):
    """Raised when suggestion content fields violate domain invariants (e.g. empty, noise placeholders)."""

    pass


class SuggestionAlreadyExistsError(DomainError):
    """Raised when attempting to ingest a suggestion whose ID already exists."""

    pass
