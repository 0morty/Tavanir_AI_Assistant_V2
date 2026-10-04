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
    uncertainty: str | None = Field(
        default=None,
        description="Explicit uncertainty or knowledge gaps identified by the model",
    )
    cited_suggestion_ids: list[str] = Field(
        default_factory=list,
        description="IDs of similar suggestions cited in the analysis text",
    )
    is_fallback_mode: bool = Field(
        default=False,
        description="Whether heuristic/RRF fallback mode was active during candidate ranking",
    )
    grounding_ratio: float = Field(
        default=0.0,
        description="Ratio of cited suggestions to the total active candidate pool [0.0, 1.0]",
    )


# Alias for backward and naming consistency
AnalyzeSuggestionResponseData = AnalyzeSuggestionDataResponse

__all__ = ["AnalyzeSuggestionDataResponse", "AnalyzeSuggestionResponseData"]
