from dataclasses import dataclass, field

from src.domain.enums import (
    CommitteeScrutiny,
    SecretariatScrutiny,
    SuggestionChunkType,
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
class AnalyzeSuggestionDTO:
    title: str
    problem: str
    solution: str
    context_title: str | None = None


@dataclass(frozen=True)
class PooledSuggestionCandidate:
    suggestion_id: str
    status: SuggestionStatus
    winning_chunk_id: str
    winning_chunk_type: SuggestionChunkType
    winning_score: float
    winning_content: str
    all_matched_chunk_types: tuple[SuggestionChunkType, ...]


# Backward-compatible alias


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


@dataclass(frozen=True, slots=True)
class RerankCandidate:
    candidate_id: str
    normalized_text: str
    retrieval_rank: int
    retrieval_score: float

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.candidate_id.strip():
            raise ValueError("candidate_id must be non-empty.")
        if not self.normalized_text or not self.normalized_text.strip():
            raise ValueError("normalized_text must be non-empty.")
        if self.retrieval_rank <= 0:
            raise ValueError("retrieval_rank must be positive.")


@dataclass(frozen=True, slots=True)
class RerankedCandidate:
    candidate_id: str
    retrieval_rank: int
    retrieval_score: float
    rerank_score: float
    reranked_rank: int


__all__ = [
    "AnalyzeSuggestionResponse",
    "AnalyzeSuggestionDTO",
    "PooledSuggestionCandidate",
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
    "RerankCandidate",
    "RerankedCandidate",
]
