from typing import Any

from src.domain.enums import SuggestionStatus
from src.domain.exceptions import InvalidSuggestionStatusError

# Translation table mapping both Persian (U+06F0-U+06F9) and Arabic-Indic (U+0660-U+0669) digits to ASCII (0-9)
DIGIT_TO_ASCII_TABLE = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)


def normalize_digits_to_ascii(value: str | None) -> str | None:
    """Converts Persian and Arabic digits to standard ASCII digits."""
    if value is None:
        return None
    return value.translate(DIGIT_TO_ASCII_TABLE)


def empty_str_to_none(value: Any) -> Any:
    """Coerces empty strings or whitespace-only strings to None."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


def parse_suggestion_status(value: Any) -> SuggestionStatus:
    """
    Parses a status input (str, int, or SuggestionStatus) into a SuggestionStatus enum instance.
    Supports Persian titles ('مصوب', 'رد'), enum names ('APPROVED'), or numeric IDs (3, '3').
    """
    if isinstance(value, SuggestionStatus):
        return value

    if isinstance(value, int):
        return SuggestionStatus.from_id(value)

    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.isdigit():
            return SuggestionStatus.from_id(int(cleaned))
        return SuggestionStatus.from_string(cleaned)

    raise InvalidSuggestionStatusError(
        f"Cannot parse suggestion status from value: '{value}'",
        pointer="/data/status",
    )


__all__ = [
    "DIGIT_TO_ASCII_TABLE",
    "normalize_digits_to_ascii",
    "empty_str_to_none",
    "parse_suggestion_status",
]
