import re
from dataclasses import dataclass

from src.domain.enums import SuggestionStatus
from src.domain.exceptions import InvalidShamsiDateFormatError


@dataclass(frozen=True)
class ShamsiDate:
    value: str

    def __post_init__(self):
        pattern = r"^[1-4]\d{3}/(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])$"
        if not re.match(pattern, self.value):
            raise InvalidShamsiDateFormatError(
                f"Invalid Shamsi date format: '{self.value}'. Expected 'YYYY/MM/DD'."
            )

    def __str__(self) -> str:
        return self.value


# region Suggestion


@dataclass(frozen=True)
class SuggestionContent:
    title: str
    problem: str | None
    solution: str | None


@dataclass(frozen=True)
class CommitteeEvaluation:
    status: SuggestionStatus
    scrutiny: str | None
    description: str | None


@dataclass
class Suggestion:
    id: str
    content: SuggestionContent
    evaluation: CommitteeEvaluation
    date: ShamsiDate | None
    context_title: str | None


# endregion


# region Statute
@dataclass
class StatuteDocument:
    id: str
    title: str
    file_name: str
    content: str  # Extracted text/tables representing the full statute
    created_at: str | None = None


# endregion
