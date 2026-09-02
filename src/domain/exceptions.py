class DomainError(Exception):
    """Base exception for all domain-level business rule violations."""

    pass


class InvalidShamsiDateFormatError(DomainError):
    """Raised when a date string does not conform to the expected Shamsi date format."""

    pass


class InvalidSuggestionStatusError(DomainError):
    """Raised when an unrecognized suggestion status value or ID is encountered."""

    pass
