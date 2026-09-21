import re

from src.domain.entities import Reference

_PLACEHOLDER_PATTERN = re.compile(r"\[([A-Za-z_][A-Za-z0-9_]*)\]")


def _fill(template: str, reference: Reference, *, strict: bool) -> str:
    available = {name for name, _ in reference.details.properties}

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in available:
            if strict:
                raise ValueError(
                    f"Template references placeholder {name!r}, which is not "
                    "available in the ReferenceDetails."
                )
            return ""
        value = getattr(reference, name)
        return "" if value is None else str(value)

    return _PLACEHOLDER_PATTERN.sub(_replace, template)


def substitute_placeholders(template: str, reference: Reference) -> str:
    """Deterministically fill a **valid** template with the Reference values.

    The normal invariant applies: every placeholder must correspond to a
    property present in the target ``ReferenceDetails``. A placeholder outside
    ``ReferenceDetails`` means the template is invalid and a ``ValueError`` is
    raised -- the caller must not tolerate such templates on the regular path
    (they are rejected by the ``TemplateValidator`` before filling).
    """
    return _fill(template, reference, strict=True)


def fill_with_fallback(template: str, reference: Reference) -> str:
    """Tolerantly fill a template produced after all generation attempts failed.

    This is the last-resort fill used only when ``max_attempts`` generation
    attempts were exhausted. Placeholders referring to properties that are not
    available in the ``ReferenceDetails`` are replaced with an empty /
    no-value representation instead of failing the whole operation.
    """
    return _fill(template, reference, strict=False)