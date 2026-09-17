from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.application.dtos import CreateSuggestionDTO
from src.domain.enums import SuggestionStatus
from src.presentation.schemas.validators import (
    empty_str_to_none,
    normalize_digits_to_ascii,
    parse_suggestion_status,
)


class IngestSuggestionRequest(BaseModel):
    """
    Inbound request schema for single suggestion ingestion.
    Accepts camelCase fields from API clients while binding to snake_case internally.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
    )

    suggestion_id: str = Field(
        ...,
        alias="suggestionId",
        min_length=1,
        description="Unique business identifier of the suggestion",
    )
    title: str = Field(
        ...,
        min_length=1,
        description="Title of the suggestion",
    )
    problem: str = Field(
        ...,
        min_length=1,
        description="Description of the organizational problem/gap",
    )
    solution: str = Field(
        ...,
        min_length=1,
        description="Proposed solution or improvement",
    )
    status: Any = Field(
        ...,
        description="Evaluation status (Persian string e.g. 'مصوب', ID int, or enum name)",
    )
    scrutiny: str | None = Field(
        default=None,
        description="Expert committee review/scrutiny notes",
    )
    description: str | None = Field(
        default=None,
        description="Final resolution or execution commentary",
    )
    shamsi_date: str | None = Field(
        default=None,
        alias="shamsiDate",
        description="Submission or evaluation date in Shamsi format (YYYY/MM/DD)",
    )
    context_title: str | None = Field(
        default=None,
        alias="contextTitle",
        description="Organizational department or domain context",
    )

    @field_validator("suggestion_id")
    @classmethod
    def validate_suggestion_id(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("suggestionId must not be empty or whitespace only")
        return cleaned

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, v: Any) -> SuggestionStatus:
        return parse_suggestion_status(v)

    @field_validator("shamsi_date", mode="before")
    @classmethod
    def validate_shamsi_date(cls, v: Any) -> str | None:
        coerced = empty_str_to_none(v)
        if coerced is None:
            return None
        return normalize_digits_to_ascii(str(coerced).strip())

    @field_validator("scrutiny", "description", "context_title", mode="before")
    @classmethod
    def validate_optional_strings(cls, v: Any) -> str | None:
        return empty_str_to_none(v)

    def to_dto(self) -> CreateSuggestionDTO:
        return CreateSuggestionDTO(
            suggestion_id=self.suggestion_id,
            title=self.title.strip(),
            problem=self.problem.strip(),
            solution=self.solution.strip(),
            status=self.status,
            scrutiny=self.scrutiny.strip() if self.scrutiny else None,
            description=self.description.strip() if self.description else None,
            shamsi_date=self.shamsi_date,
            context_title=self.context_title.strip() if self.context_title else None,
        )


__all__ = ["IngestSuggestionRequest"]
