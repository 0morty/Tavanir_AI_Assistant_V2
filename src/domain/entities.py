import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

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


# region Prompt Architecture Entities


@dataclass
class Chunk:
    id: str
    title: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class PromptSectionType(Enum):
    ROLE = "ROLE"
    PRE_CONTEXT = "PRE-CONTEXT"
    CHUNKS = "CHUNKS"
    POST_CONTEXT = "POST-CONTEXT"
    SYSTEM_INPUT = "SYSTEM-INPUT"
    USER_INPUT = "USER-INPUT"
    OUTPUT_FORMAT = "OUTPUT-FORMAT"


@dataclass
class PromptSection:
    section_type: PromptSectionType
    content: str | list[Chunk]
    separator: str = "\n\n"


@dataclass
class PromptBuildContext:
    sections: list[PromptSection] = field(default_factory=list)

    def render(self) -> str:
        parts: list[str] = []
        for section in self.sections:
            if isinstance(section.content, list):
                rendered_chunks = []
                for i, chunk in enumerate(section.content, 1):
                    rendered_chunks.append(f"Chunk {i}:\n{chunk.content}")
                parts.append("\n\n".join(rendered_chunks))
            else:
                parts.append(section.content)
        return section.separator.join(parts)


# endregion
