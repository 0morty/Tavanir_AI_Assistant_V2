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


def test_exception_inheritance_hierarchy():
    # Base invariant
    assert issubclass(InvalidShamsiDateFormatError, DomainError)
    assert issubclass(InvalidSuggestionStatusError, DomainError)
    assert issubclass(InvalidSparseVectorError, DomainError)

    # Vector store exceptions
    assert issubclass(VectorStorageError, DomainError)
    assert issubclass(VectorSearchError, DomainError)
    assert issubclass(VectorCollectionProvisioningError, DomainError)
    assert issubclass(VectorPayloadValidationError, DomainError)

    # Relational hydration exceptions
    assert issubclass(EntityNotFoundError, DomainError)
    assert issubclass(ParentChildIntegrityError, DomainError)


def test_exception_messages():
    err = VectorPayloadValidationError("Invalid chunk payload")
    assert str(err) == "Invalid chunk payload"
    assert isinstance(err, DomainError)
