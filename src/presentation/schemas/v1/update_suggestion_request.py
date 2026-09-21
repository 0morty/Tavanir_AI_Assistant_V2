from typing import Any

from pydantic import Field, field_validator, model_validator
from src.presentation.schemas.requests import BaseRequestModel

from src.application.dtos import UpdateSuggestionDTO
from src.domain.enums import (
    CommitteeScrutiny,
    SecretariatScrutiny,
    SuggestionStatus,
)
from src.domain.exceptions import SuggestionPayloadValidationError
from src.presentation.schemas.validators import (
    empty_str_to_none,
    normalize_digits_to_ascii,
    parse_committee_scrutiny,
    parse_secretariat_scrutiny,
    parse_suggestion_status,
)


class UpdateSuggestionRequest(BaseRequestModel):
    """
    Inbound request schema for full replacement update (PUT /api/v1/suggestions/{suggestionId}).
    All core fields (title, problem, solution, status) are mandatory.
    """

    suggestion_id: str | None = Field(
        default=None,
        description="Optional ID in body. If provided, must match the URL path parameter exactly.",
    )
    title: str = Field(
        ...,
        min_length=1,
        description="Updated title of the suggestion",
    )
    problem: str = Field(
        ...,
        min_length=1,
        description="Updated description of the organizational problem/gap",
    )
    solution: str = Field(
        ...,
        min_length=1,
        description="Updated proposed solution or improvement",
    )
    status: Any = Field(
        ...,
        description="Evaluation status (Persian string e.g. 'مصوب', ID int, or enum name)",
    )
    committee_scrutiny: Any = Field(
        default=None,
        description="Expert committee review/scrutiny (Persian title, code int, or string)",
    )
    description: str | None = Field(
        default=None,
        description="Final resolution or execution commentary",
    )
    shamsi_date: str | None = Field(
        default=None,
        description="Submission or evaluation date in Shamsi format (YYYY/MM/DD)",
    )
    context_title: str | None = Field(
        default=None,
        description="Organizational department or domain context",
    )
    secretariat_scrutiny: Any = Field(
        default=None,
        description="Secretariat primary scrutiny (Persian title, code int, or string)",
    )
    secretariat_comment: str | None = Field(
        default=None,
        description="Secretariat review rationale or commentary",
    )
    tributary_scrutiny: Any = Field(
        default=None,
        description="Legacy alias for secretariat scrutiny",
    )
    tributary_comment: str | None = Field(
        default=None,
        description="Legacy alias for secretariat commentary",
    )

    @model_validator(mode="before")
    @classmethod
    def validate_mutually_exclusive_aliases(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        sec_scrutiny = data.get("secretariat_scrutiny")
        if sec_scrutiny is None:
            sec_scrutiny = data.get("secretariatScrutiny")

        trib_scrutiny = data.get("tributary_scrutiny")
        if trib_scrutiny is None:
            trib_scrutiny = data.get("tributaryScrutiny")

        if sec_scrutiny is not None and trib_scrutiny is not None:
            raise ValueError(
                "Cannot supply both secretariat_scrutiny and tributary_scrutiny in the same request."
            )

        sec_comment = data.get("secretariat_comment")
        if sec_comment is None:
            sec_comment = data.get("secretariatComment")

        trib_comment = data.get("tributary_comment")
        if trib_comment is None:
            trib_comment = data.get("tributaryComment")

        if sec_comment is not None and trib_comment is not None:
            raise ValueError(
                "Cannot supply both secretariat_comment and tributary_comment in the same request."
            )

        if trib_scrutiny is not None and sec_scrutiny is None:
            data["secretariat_scrutiny"] = trib_scrutiny

        if trib_comment is not None and sec_comment is None:
            data["secretariat_comment"] = trib_comment

        return data

    @field_validator("title", "problem", "solution")
    @classmethod
    def validate_non_empty_strings(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Field must not be empty or whitespace only.")
        return cleaned

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, v: Any) -> SuggestionStatus:
        return parse_suggestion_status(v)

    @field_validator("committee_scrutiny", mode="before")
    @classmethod
    def validate_committee_scrutiny(cls, v: Any) -> CommitteeScrutiny | None:
        return parse_committee_scrutiny(v)

    @field_validator("secretariat_scrutiny", mode="before")
    @classmethod
    def validate_secretariat_scrutiny(cls, v: Any) -> SecretariatScrutiny | None:
        return parse_secretariat_scrutiny(v)

    @field_validator("shamsi_date", mode="before")
    @classmethod
    def validate_shamsi_date(cls, v: Any) -> str | None:
        coerced = empty_str_to_none(v)
        if coerced is None:
            return None
        return normalize_digits_to_ascii(str(coerced).strip())

    @field_validator(
        "description",
        "context_title",
        "secretariat_comment",
        "tributary_comment",
        mode="before",
    )
    @classmethod
    def validate_optional_strings(cls, v: Any) -> str | None:
        return empty_str_to_none(v)

    def to_dto(self, path_suggestion_id: str) -> UpdateSuggestionDTO:
        if self.suggestion_id is not None:
            cleaned_body_id = self.suggestion_id.strip()
            if cleaned_body_id and cleaned_body_id != path_suggestion_id:
                raise SuggestionPayloadValidationError(
                    f"Body suggestionId '{cleaned_body_id}' does not match URL path '{path_suggestion_id}'.",
                    pointer="/data/suggestionId",
                    field_name="suggestion_id",
                )

        committee_id = (
            self.committee_scrutiny.code
            if isinstance(self.committee_scrutiny, CommitteeScrutiny)
            else None
        )
        secretariat_id = (
            self.secretariat_scrutiny.code
            if isinstance(self.secretariat_scrutiny, SecretariatScrutiny)
            else None
        )

        return UpdateSuggestionDTO(
            suggestion_id=path_suggestion_id,
            title=self.title.strip(),
            problem=self.problem.strip(),
            solution=self.solution.strip(),
            status=self.status,
            committee_scrutiny=self.committee_scrutiny,
            description=self.description.strip() if self.description else None,
            shamsi_date=self.shamsi_date,
            context_title=self.context_title.strip() if self.context_title else None,
            committee_scrutiny_id=committee_id,
            secretariat_scrutiny=self.secretariat_scrutiny,
            secretariat_comment=self.secretariat_comment.strip()
            if self.secretariat_comment
            else None,
            secretariat_scrutiny_id=secretariat_id,
        )


__all__ = ["UpdateSuggestionRequest"]
