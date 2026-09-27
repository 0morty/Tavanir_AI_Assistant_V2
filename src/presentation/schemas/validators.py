from typing import Any

from src.domain.enums import (
    CommitteeScrutiny,
    SecretariatScrutiny,
    SuggestionStatus,
)
from src.domain.exceptions import (
    InvalidCommitteeScrutinyError,
    InvalidSecretariatScrutinyError,
    InvalidSuggestionStatusError,
)

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

    try:
        if isinstance(value, int):
            return SuggestionStatus.from_id(value)

        if isinstance(value, str):
            cleaned = normalize_digits_to_ascii(value.strip())
            if cleaned is None or not cleaned:
                raise InvalidSuggestionStatusError(
                    "Status must not be empty.",
                    pointer="/data/status",
                    field_name="status",
                )
            try:
                return SuggestionStatus.from_id(int(cleaned))
            except ValueError:
                return SuggestionStatus.from_string(cleaned)
    except InvalidSuggestionStatusError as exc:
        raise InvalidSuggestionStatusError(
            str(exc),
            pointer="/data/status",
            field_name="status",
        ) from exc

    raise InvalidSuggestionStatusError(
        f"Cannot parse suggestion status from value: '{value}'",
        pointer="/data/status",
        field_name="status",
    )


def parse_committee_scrutiny(value: Any) -> CommitteeScrutiny | None:
    """
    Parses a committee scrutiny input (str, int, or CommitteeScrutiny) into a CommitteeScrutiny enum instance.
    Supports Persian titles ('تایید', 'رد'), enum names, or numeric codes (0, 1, -10, '-10').
    Returns None if input is None or whitespace-only.
    """
    if value is None:
        return None

    if isinstance(value, CommitteeScrutiny):
        return value

    try:
        if isinstance(value, int):
            return CommitteeScrutiny.from_code(value)

        if isinstance(value, str):
            cleaned = normalize_digits_to_ascii(value.strip())
            if cleaned is None or not cleaned:
                return None
            try:
                return CommitteeScrutiny.from_code(int(cleaned))
            except ValueError:
                return CommitteeScrutiny.from_string(cleaned)
    except InvalidCommitteeScrutinyError as exc:
        raise InvalidCommitteeScrutinyError(
            str(exc),
            pointer="/data/committeeScrutiny",
            field_name="committee_scrutiny",
        ) from exc

    raise InvalidCommitteeScrutinyError(
        f"Cannot parse committee scrutiny from value: '{value}'",
        pointer="/data/committeeScrutiny",
        field_name="committee_scrutiny",
    )


def parse_secretariat_scrutiny(value: Any) -> SecretariatScrutiny | None:
    """
    Parses a secretariat scrutiny input (str, int, or SecretariatScrutiny) into a SecretariatScrutiny enum instance.
    Supports Persian titles ('خارج از چهارچوب'), enum names, or numeric codes (0, 6, -2, '-2').
    Returns None if input is None or whitespace-only.
    """
    if value is None:
        return None

    if isinstance(value, SecretariatScrutiny):
        return value

    try:
        if isinstance(value, int):
            return SecretariatScrutiny.from_code(value)

        if isinstance(value, str):
            cleaned = normalize_digits_to_ascii(value.strip())
            if cleaned is None or not cleaned:
                return None
            try:
                return SecretariatScrutiny.from_code(int(cleaned))
            except ValueError:
                return SecretariatScrutiny.from_string(cleaned)
    except InvalidSecretariatScrutinyError as exc:
        raise InvalidSecretariatScrutinyError(
            str(exc),
            pointer="/data/secretariatScrutiny",
            field_name="secretariat_scrutiny",
        ) from exc

    raise InvalidSecretariatScrutinyError(
        f"Cannot parse secretariat scrutiny from value: '{value}'",
        pointer="/data/secretariatScrutiny",
        field_name="secretariat_scrutiny",
    )


__all__ = [
    "DIGIT_TO_ASCII_TABLE",
    "normalize_digits_to_ascii",
    "empty_str_to_none",
    "parse_suggestion_status",
    "parse_committee_scrutiny",
    "parse_secretariat_scrutiny",
]
