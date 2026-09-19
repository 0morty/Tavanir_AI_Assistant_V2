from dataclasses import dataclass, field

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
    "RawSuggestionDataDTO",
    "SkippedRecordDTO",
    "CheckpointData",
    "HistoricalIngestionResultDTO",
]
