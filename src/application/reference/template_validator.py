import re
from dataclasses import dataclass

from src.application.interfaces.i_template_validator import ITemplateValidator
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
    """Outcome of validating a template against a ``ReferenceDetails`` instance.

    ``missing`` holds the placeholders that refer to properties not available
    in the validated ``ReferenceDetails``, sorted alphabetically. The
    validator only *reports*; deciding whether to retry or fall back belongs to
    the calling generation workflow.
    """

    valid: bool
    missing: tuple[str, ...] = ()

    def error_message(self) -> str:
        """Human-readable description of the failure, or ``""`` when valid.

        This is the exact error text a generation workflow should feed back to
        the LLM on a retry attempt, without rewriting or reformatting.
        """
        if self.valid:
            return ""
        listed = ", ".join(self.missing)
        return f"Template references unavailable properties: {listed}."


class TemplateValidator(ITemplateValidator):
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