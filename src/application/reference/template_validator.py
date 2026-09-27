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
    """Schema differences found in a candidate reference template.

    Missing contains declared properties absent from the template in schema
    order. Unknown contains placeholders absent from the schema, sorted
    alphabetically. Repeated valid placeholders remain allowed.
    """

    valid: bool
    missing: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()

    def error_message(self) -> str:
        """Return corrective feedback for the next LLM attempt."""
        if self.valid:
            return ""
        messages = []
        if self.unknown:
            messages.append(
                "Template references unavailable properties: "
                + ", ".join(self.unknown)
                + "."
            )
        if self.missing:
            messages.append(
                "Template omits required properties: "
                + ", ".join(self.missing)
                + "."
            )
        return "\n".join(messages) if messages else "Template validation failed."


class TemplateValidator(ITemplateValidator):
    """Require every available property and reject unknown placeholders.

    Validation uses the shape in ReferenceDetails rather than property values.
    Repeating a valid placeholder is permitted by the existing contract.
    """

    def validate(
        self, template: str, details: ReferenceDetails
    ) -> TemplateValidationResult:
        placeholders = extract_placeholders(template)
        detected = set(placeholders)
        available = {name for name, _ in details.properties}
        missing = tuple(
            name for name, _ in details.properties if name not in detected
        )
        unknown = tuple(sorted(detected - available))
        return TemplateValidationResult(
            valid=not missing and not unknown,
            missing=missing,
            unknown=unknown,
        )
