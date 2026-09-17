import re
from dataclasses import dataclass

from src.domain.entities import ReferenceDetails

_PLACEHOLDER_PATTERN = re.compile(r"\[([A-Za-z_][A-Za-z0-9_]*)\]")


def extract_placeholders(template: str) -> tuple[str, ...]:
    """Extract the unique property placeholders referenced by a template.

    A placeholder has the form ``[property_name]``. Duplicates are returned
    once, in first-seen order, so repeated properties are never validated
    twice.
    """
    return tuple(dict.fromkeys(_PLACEHOLDER_PATTERN.findall(template)))


@dataclass(frozen=True)
class TemplateValidationResult:
    """Outcome of validating a template against a ``ReferenceDetails`` instance."""

    valid: bool
    missing: tuple[str, ...] = ()


class TemplateValidator:
    """Validate that every placeholder in a template refers to an available property.

    The check is about property *existence* in the given
    :class:`ReferenceDetails`. It never inspects property values: a property
    whose value is ``None`` is still valid as long as it exists in
    ``ReferenceDetails.properties``. A template with no placeholders
    references nothing that could be missing and is therefore valid.
    """

    def validate(
        self, template: str, details: ReferenceDetails
    ) -> TemplateValidationResult:
        placeholders = extract_placeholders(template)
        available = {name for name, _ in details.properties}
        missing = tuple(
            sorted(placeholder for placeholder in placeholders if placeholder not in available)
        )
        return TemplateValidationResult(valid=not missing, missing=missing)