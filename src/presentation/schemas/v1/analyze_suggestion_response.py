from __future__ import annotations

from pydantic import Field
from src.presentation.schemas.responses import BaseResponseModel


class AnalyzeSuggestionDataResponse(BaseResponseModel):
    """
    Response payload for suggestion analysis containing provenance IDs across all 5 status partitions
    conforming to 03_Naming_And_Data_Exchange.md.
    """

    analysis: str = Field(
        ...,
        description="Markdown analysis and decision-support summary text",
    )
    similar_executed_ids: list[str] = Field(
        default_factory=list,
        description="IDs of historical executed suggestions matching the suggestion",
    )
    similar_approved_ids: list[str] = Field(
        default_factory=list,
        description="IDs of historical approved suggestions matching the suggestion",
    )
    similar_pending_ids: list[str] = Field(
        default_factory=list,
        description="IDs of ongoing pending suggestions matching the suggestion",
    )
    similar_rejected_ids: list[str] = Field(
        default_factory=list,
        description="IDs of historical rejected suggestions matching the suggestion",
    )
    similar_not_accepted_ids: list[str] = Field(
        default_factory=list,
        description="IDs of historical not-accepted suggestions matching the suggestion",
    )
    applied_statute_ids: list[str] = Field(
        default_factory=list,
        description="IDs of applicable statutory documents and regulatory articles",
    )


# Alias for backward and naming consistency
AnalyzeSuggestionResponseData = AnalyzeSuggestionDataResponse

__all__ = ["AnalyzeSuggestionDataResponse", "AnalyzeSuggestionResponseData"]
