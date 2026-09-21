from pydantic import Field, field_validator
from src.presentation.schemas.requests import BaseRequestModel

from src.application.dtos import BulkDeleteSuggestionsDTO


class BulkDeleteRequest(BaseRequestModel):
    """
    Inbound request schema for bulk soft deletion (POST /api/v1/suggestions/bulk-delete).
    Strictly bounded to 1-100 items; duplicates are rejected.
    """

    suggestion_ids: list[str] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Bounded list of unique suggestion IDs to delete (1-100 items).",
    )

    @field_validator("suggestion_ids")
    @classmethod
    def validate_suggestion_ids(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("suggestionIds must contain at least 1 item.")

        if len(v) > 100:
            raise ValueError("suggestionIds cannot exceed 100 items per request.")

        cleaned_ids: list[str] = []
        seen = set()

        for idx, item in enumerate(v):
            if not isinstance(item, str) or not item.strip():
                raise ValueError(
                    f"suggestionIds[{idx}] must be a non-empty string."
                )
            cleaned = item.strip()
            if cleaned in seen:
                raise ValueError(
                    f"Duplicate suggestion ID '{cleaned}' found in request."
                )
            seen.add(cleaned)
            cleaned_ids.append(cleaned)

        return cleaned_ids

    def to_dto(self) -> BulkDeleteSuggestionsDTO:
        return BulkDeleteSuggestionsDTO(suggestion_ids=self.suggestion_ids)


__all__ = ["BulkDeleteRequest"]
