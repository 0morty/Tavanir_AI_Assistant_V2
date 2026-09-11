from src.presentation.exception_handlers import (
    ERROR_REGISTRY,
    extract_pointer,
    resolve_error_spec,
)

from src.application.exceptions import (
    AggregateApplicationError,
    ApplicationError,
    EmbedderConnectionError,
)
from src.domain.exceptions import (
    DomainError,
    InvalidShamsiDateFormatError,
    InvalidSuggestionStatusError,
)


def get_all_subclasses(cls: type) -> set[type]:
    """Recursively discover all subclasses of a given class."""
    subclasses = set(cls.__subclasses__())
    for s in list(subclasses):
        subclasses.update(get_all_subclasses(s))
    return subclasses


def test_all_concrete_exceptions_are_mapped_in_error_registry():
    """
    CI Safety Test (Concern 1):
    Asserts that every concrete domain and application exception has an explicit
    entry in ERROR_REGISTRY, preventing unmapped exceptions from falling back to
    generic codes.
    """
    domain_exceptions = get_all_subclasses(DomainError)
    app_exceptions = get_all_subclasses(ApplicationError)

    all_exceptions = domain_exceptions.union(app_exceptions)
    # AggregateApplicationError is handled by a dedicated multi-error handler
    all_exceptions.discard(AggregateApplicationError)

    missing_mappings = [
        exc_cls.__name__ for exc_cls in all_exceptions if exc_cls not in ERROR_REGISTRY
    ]

    assert not missing_mappings, (
        f"The following exceptions lack an explicit entry in ERROR_REGISTRY: "
        f"{missing_mappings}. Register them in src/presentation/exception_handlers.py!"
    )


def test_resolve_error_spec_exact_match():
    """Verifies that exact exception type matches resolve their exact spec."""
    spec = resolve_error_spec(InvalidSuggestionStatusError("Invalid status"))
    assert spec.status_code == 422
    assert spec.code == "INVALID_SUGGESTION_STATUS"
    assert spec.default_pointer == "/data/status"


def test_resolve_error_spec_mro_fallback():
    """Verifies that unmapped sub-exceptions fall back via MRO or base category."""

    class UnknownCustomDomainError(DomainError):
        pass

    spec = resolve_error_spec(UnknownCustomDomainError("Unknown issue"))
    assert spec.status_code == 400
    assert spec.code == "DOMAIN_RULE_VIOLATION"


def test_extract_pointer_priority():
    """Verifies that custom exc.pointer takes precedence over default pointer."""
    exc_with_pointer = InvalidShamsiDateFormatError(
        "Bad date", pointer="/data/custom/dateField"
    )
    assert extract_pointer(exc_with_pointer, "/data/date") == "/data/custom/dateField"

    exc_without_pointer = InvalidShamsiDateFormatError("Bad date")
    assert extract_pointer(exc_without_pointer, "/data/date") == "/data/date"

    exc_with_field_name = InvalidShamsiDateFormatError(
        "Bad date", field_name="birthDate"
    )
    assert extract_pointer(exc_with_field_name, "/data/date") == "/data/birthDate"


def test_internal_single_error_pointer_omission():
    """Verifies that single-request internal errors return None for pointer."""
    exc = EmbedderConnectionError("TEI provider timed out")
    spec = resolve_error_spec(exc)
    pointer = extract_pointer(exc, spec.default_pointer)
    assert pointer is None
