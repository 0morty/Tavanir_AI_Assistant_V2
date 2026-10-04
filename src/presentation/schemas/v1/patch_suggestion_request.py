from typing import Any

from pydantic import Field, field_validator, model_validator
from src.presentation.schemas.requests import BaseRequestModel

from src.application.dtos import PatchSuggestionDTO
from src.domain.enums import (
    CommitteeScrutiny,
    SecretariatScrutiny,
    SuggestionStatus,
)
from src.presentation.schemas.validators import (
    empty_str_to_none,
    normalize_digits_to_ascii,
    parse_committee_scrutiny,
    parse_secretariat_scrutiny,
    parse_suggestion_status,
)


class PatchSuggestionRequest(BaseRequestModel):
    """
    Inbound request schema for partial update (PATCH /api/v1/suggestions/{suggestionId}).
    All fields are optional; omitted or null fields are ignored (treated as unchanged).
    Must contain at least one non-null field. Reject if suggestionId is in body.
    """

    suggestion_id: str | None = Field(
        default=None,
        description="Immutable identifier; must not be supplied in PATCH body.",
    )
    title: str | None = Field(
        default=None,
        description="Updated title of the suggestion",
    )
    problem: str | None = Field(
        default=None,
        description="Updated description of the organizational problem/gap",
    )
    solution: str | None = Field(
        default=None,
        description="Updated proposed solution or improvement",
    )
    status: Any = Field(
        default=None,
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
        max_length=512,
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
    def validate_patch_rules(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        # Rule 1: Reject suggestionId in PATCH body
        if "suggestion_id" in data or "suggestionId" in data:
            raise ValueError(
                "suggestionId is immutable and must not be provided in PATCH body."
            )

        # Handle aliases
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

        # Rule 2: Ensure at least one substantive, non-blank field is provided
        substantive_values = [
            v
            for k, v in data.items()
            if v is not None and (not isinstance(v, str) or v.strip())
        ]
        if not substantive_values:
            raise ValueError(
                "At least one non-null field must be provided in PATCH request with substantive content."
            )

        return data

    @field_validator("title", "problem", "solution")
    @classmethod
    def validate_content_strings(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Field must not be empty or whitespace only if provided.")
        return cleaned

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, v: Any) -> SuggestionStatus | None:
        if v is None:
            return None
        return parse_suggestion_status(v)

    @field_validator("committee_scrutiny", mode="before")
    @classmethod
    def validate_committee_scrutiny(cls, v: Any) -> CommitteeScrutiny | None:
        if v is None:
            return None
        return parse_committee_scrutiny(v)

    @field_validator("secretariat_scrutiny", mode="before")
    @classmethod
    def validate_secretariat_scrutiny(cls, v: Any) -> SecretariatScrutiny | None:
        if v is None:
            return None
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

    def to_dto(self, path_suggestion_id: str) -> PatchSuggestionDTO:
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

        return PatchSuggestionDTO(
            suggestion_id=path_suggestion_id,
            title=self.title.strip() if self.title is not None else None,
            problem=self.problem.strip() if self.problem is not None else None,
            solution=self.solution.strip() if self.solution is not None else None,
            status=self.status,
            committee_scrutiny=self.committee_scrutiny,
            description=self.description.strip()
            if self.description is not None
            else None,
            shamsi_date=self.shamsi_date,
            context_title=self.context_title.strip()
            if self.context_title is not None
            else None,
            committee_scrutiny_id=committee_id,
            secretariat_scrutiny=self.secretariat_scrutiny,
            secretariat_comment=self.secretariat_comment.strip()
            if self.secretariat_comment is not None
            else None,
            secretariat_scrutiny_id=secretariat_id,
        )


__all__ = ["PatchSuggestionRequest"]
