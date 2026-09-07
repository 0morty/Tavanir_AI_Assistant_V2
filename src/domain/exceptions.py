class DomainError(Exception):
    """Base exception for all domain-level business rule violations."""

    pass


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

