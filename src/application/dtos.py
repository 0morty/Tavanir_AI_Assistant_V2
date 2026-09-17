from dataclasses import dataclass, field

from src.domain.enums import SuggestionStatus


@dataclass
class AnalyzeSuggestionResponse:
    # 1. Dynamic LLM Output (Markdown)
    analysis: str

    # 2. Complete Provenance for all 5 Status Partitions
    similar_executed_ids: list[str] = field(default_factory=list)
    similar_approved_ids: list[str] = field(default_factory=list)
    similar_pending_ids: list[str] = field(default_factory=list)
    similar_rejected_ids: list[str] = field(default_factory=list)
    similar_not_accepted_ids: list[str] = field(default_factory=list)

    # 3. Applicable Statutes & Distances
    applied_statute_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CreateSuggestionDTO:
    suggestion_id: str
    title: str
    problem: str
    solution: str
    status: SuggestionStatus
    scrutiny: str | None = None
    description: str | None = None
    shamsi_date: str | None = None
    context_title: str | None = None


@dataclass(frozen=True)
class IngestSuggestionResponseDTO:
    suggestion_id: str
    chunks_count: int
    status: str = "CREATED"


__all__ = [
    "AnalyzeSuggestionResponse",
    "CreateSuggestionDTO",
    "IngestSuggestionResponseDTO",
]
