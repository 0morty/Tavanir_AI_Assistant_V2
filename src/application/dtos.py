from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from src.application.context.allocation.expansion_request import ExpansionRequest

from src.domain.enums import (
    CommitteeScrutiny,
    SecretariatScrutiny,
    SuggestionStatus,
)


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
class SectionOutput:
    """Per-section result after budgeting, reference handling, and overflow fitting."""

    section_type: str
    content: str
    requested_tokens: int
    capacity_tokens: int
    fitted_tokens: int
    overflowed: bool


@dataclass(frozen=True)
class ContextBuilderResult:
    """Final rendered prompt plus per-section accounting."""

    prompt: str
    sections: tuple[SectionOutput, ...]
    budget_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class CapacityRequest:
    """Per-section allocation information consumed by :class:`CapacityAllocator`.

    ``demand`` is the Section's relative request for initial capacity, and
    ``importance`` is its weight when the free capacity is redistributed --
    two independent values in ``[0.0, 1.0]`` that do not need to sum to one.
    ``needed_tokens`` is the amount of capacity the Section can actually use
    (its already-rendered content size).
    """

    key: str
    demand: float
    importance: float
    needed_tokens: int

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("CapacityRequest key must be a non-empty string")
        if not 0.0 <= self.demand <= 1.0:
            raise ValueError(
                f"CapacityRequest demand must be in [0.0, 1.0], got {self.demand!r}"
            )
        if not 0.0 <= self.importance <= 1.0:
            raise ValueError(
                f"CapacityRequest importance must be in [0.0, 1.0], "
                f"got {self.importance!r}"
            )
        if self.needed_tokens < 0:
            raise ValueError(
                f"CapacityRequest needed_tokens must be non-negative, "
                f"got {self.needed_tokens!r}"
            )


@dataclass(frozen=True)
class CapacityAllocation:
    """The outcome of :meth:`CapacityAllocator.allocate`."""

    capacities: Mapping[str, int]
    unused_tokens: int


@dataclass(frozen=True)
class RedistributionResult:
    """The outcome of a redistribution pass over expansion requests."""

    allocations: tuple[ExpansionRequest, ...]
    unused_capacity: int


class CreateSuggestionDTO:
    suggestion_id: str
    title: str
    problem: str
    solution: str
    status: SuggestionStatus
    committee_scrutiny: CommitteeScrutiny | None = None
    description: str | None = None
    shamsi_date: str | None = None
    context_title: str | None = None
    committee_scrutiny_id: int | None = None
    secretariat_scrutiny: SecretariatScrutiny | None = None
    secretariat_comment: str | None = None
    secretariat_scrutiny_id: int | None = None


@dataclass(frozen=True)
class IngestSuggestionResponseDTO:
    suggestion_id: str
    chunks_count: int
    status: str = "CREATED"


@dataclass(frozen=True)
class UpdateSuggestionDTO:
    suggestion_id: str
    title: str
    problem: str
    solution: str
    status: SuggestionStatus
    committee_scrutiny: CommitteeScrutiny | None = None
    description: str | None = None
    shamsi_date: str | None = None
    context_title: str | None = None
    committee_scrutiny_id: int | None = None
    secretariat_scrutiny: SecretariatScrutiny | None = None
    secretariat_comment: str | None = None
    secretariat_scrutiny_id: int | None = None


@dataclass(frozen=True)
class PatchSuggestionDTO:
    suggestion_id: str
    title: str | None = None
    problem: str | None = None
    solution: str | None = None
    status: SuggestionStatus | None = None
    committee_scrutiny: CommitteeScrutiny | None = None
    description: str | None = None
    shamsi_date: str | None = None
    context_title: str | None = None
    committee_scrutiny_id: int | None = None
    secretariat_scrutiny: SecretariatScrutiny | None = None
    secretariat_comment: str | None = None
    secretariat_scrutiny_id: int | None = None


@dataclass(frozen=True)
class UpdateSuggestionResponseDTO:
    suggestion_id: str
    chunks_count: int
    version: int
    status: str = "UPDATED"


@dataclass(frozen=True)
class DeleteSuggestionResponseDTO:
    suggestion_id: str
    status: str = "DELETED"


@dataclass(frozen=True)
class BulkDeleteSuggestionsDTO:
    suggestion_ids: list[str]


@dataclass(frozen=True)
class BulkDeleteErrorItemDTO:
    suggestion_id: str
    index: int
    code: str
    detail: str
    source_pointer: str


@dataclass(frozen=True)
class BulkDeleteResultDTO:
    deleted_ids: list[str]
    errors: list[BulkDeleteErrorItemDTO]
    total_requested: int
    total_deleted: int
    total_failed: int


@dataclass(frozen=True)
class RawSuggestionDataDTO:
    """Raw legacy suggestion record extracted from MSSQL with committee evaluation data."""

    suggestion_id: str
    title: str
    problem: str | None
    solution: str | None
    status_id: int
    committee_scrutiny: str | None
    description: str | None
    shamsi_date: str | None
    context_title: str | None
    committee_scrutiny_id: int | None = None
    secretariat_scrutiny_id: int | None = None
    secretariat_scrutiny: str | None = None
    secretariat_comment: str | None = None


@dataclass(frozen=True)
class SkippedRecordDTO:
    """Diagnostic audit record for an invalid legacy suggestion skipped during ETL."""

    suggestion_id: str
    reason: str
    error_type: str


@dataclass(frozen=True)
class CheckpointData:
    """ETL ingestion checkpoint state."""

    last_offset: int
    last_processed_id: str | None
    total_processed: int


@dataclass(frozen=True)
class HistoricalIngestionResultDTO:
    """Aggregated operational metrics from a cold-start batch ingestion run."""

    total_extracted: int
    total_ingested: int
    total_chunks: int
    total_skipped: int
    last_offset: int
    last_processed_id: str | None
    execution_time_seconds: float


__all__ = [
    "AnalyzeSuggestionResponse",
    "CreateSuggestionDTO",
    "IngestSuggestionResponseDTO",
    "UpdateSuggestionDTO",
    "PatchSuggestionDTO",
    "UpdateSuggestionResponseDTO",
    "DeleteSuggestionResponseDTO",
    "BulkDeleteSuggestionsDTO",
    "BulkDeleteErrorItemDTO",
    "BulkDeleteResultDTO",
    "RawSuggestionDataDTO",
    "SkippedRecordDTO",
    "CheckpointData",
    "HistoricalIngestionResultDTO",
]
