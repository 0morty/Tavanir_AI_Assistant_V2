from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator
from src.presentation.schemas.requests import BaseRequestModel

from src.application.dtos import AnalyzeSuggestionDTO
from src.domain.entities import NOISE_PLACEHOLDERS
from src.domain.exceptions import InvalidSuggestionContentError
from src.presentation.schemas.validators import empty_str_to_none


class AnalyzeSuggestionRequest(BaseRequestModel):
    """
    Inbound request schema for suggestion analysis (ADR-002, 03_Naming_And_Data_Exchange.md).
    Accepts camelCase fields from API clients while binding to internal Python fields.
    """

    title: str = Field(
        ...,
        min_length=5,
        description="Title of the suggestion under evaluation",
    )
    current_problem: str = Field(
        ...,
        min_length=5,
        description="Description of the organizational problem or gap",
        alias="currentProblem",
    )
    solution: str = Field(
        ...,
        min_length=5,
        description="Proposed engineering, operational, or software method",
    )
    context_title: str | None = Field(
        default=None,
        description="Organizational department or technical context",
        alias="contextTitle",
    )

    @field_validator("title", "current_problem", "solution", mode="before")
    @classmethod
    def validate_content_not_empty_or_noise(cls, value: Any, info: Any) -> str:
        field_name = info.field_name or "content"
        pointer_name = (
            "currentProblem" if field_name == "current_problem" else field_name
        )
        pointer = f"/data/{pointer_name}"

        if not isinstance(value, str) or not value.strip():
            raise InvalidSuggestionContentError(
                f"Field '{pointer_name}' must not be empty or whitespace.",
                pointer=pointer,
                field_name=pointer_name,
            )
        cleaned = value.strip()
        if len(cleaned) < 5 or cleaned in NOISE_PLACEHOLDERS:
            raise InvalidSuggestionContentError(
                f"Field '{pointer_name}' must contain substantive content, got '{cleaned}'.",
                pointer=pointer,
                field_name=pointer_name,
            )
        return cleaned

    @field_validator("context_title", mode="before")
    @classmethod
    def clean_context_title(cls, value: Any) -> str | None:
        return empty_str_to_none(value)

    def to_dto(self) -> AnalyzeSuggestionDTO:
        return AnalyzeSuggestionDTO(
            title=self.title,
            problem=self.current_problem,
            solution=self.solution,
            context_title=self.context_title,
        )


__all__ = ["AnalyzeSuggestionRequest"]
