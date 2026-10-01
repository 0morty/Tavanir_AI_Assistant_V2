from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:  # pragma: no cover
    from src.application.context.allocation.expansion_request import ExpansionRequest
    from src.domain.entities import HistoryMessage

from src.application.exceptions import DuplicateEvidenceIdError
from src.domain.entities import GenerationChunk, NOISE_PLACEHOLDERS, Reference
from src.domain.enums import (
    CommitteeScrutiny,
    SecretariatScrutiny,
    SuggestionChunkType,
    SuggestionStatus,
)
from src.domain.exceptions import InvalidSuggestionContentError


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
class SectionProcessingResult:
    """Immutable prepared or transformed section content.

    ``items`` preserves collection boundaries and metadata. ``item_bodies``
    holds each reference-enriched body for exact prefix rendering; ``item_inputs``
    holds each complete pre/post-framed input for independent summarization.
    ``citation_ids`` preserves surviving original item identities.
    Single-text sections leave these collection fields as None.
    """

    content: str
    items: tuple[Any, ...] | None = None
    item_bodies: tuple[str, ...] | None = None
    item_inputs: tuple[str, ...] | None = None
    citation_ids: tuple[str, ...] | None = None


@dataclass(frozen=True)
class SectionOutput:
    """Final section result with token accounting owned by ContextBuilder."""

    section_type: str
    content: str
    requested_tokens: int
    capacity_tokens: int
    fitted_tokens: int
    overflowed: bool
    items: tuple[Any, ...] | None = None
    citation_ids: tuple[str, ...] | None = None

    @property
    def history_messages(self) -> tuple[HistoryMessage, ...] | None:
        if self.section_type != "HISTORY":
            return None
        return cast("tuple[HistoryMessage, ...] | None", self.items)


@dataclass(frozen=True)
class ContextBuilderResult:
    """Final rendered prompt, per-section accounting, and assembly separator."""

    prompt: str
    sections: tuple[SectionOutput, ...]
    budget_tokens: int
    total_tokens: int
    section_separator: str = "\n\n"


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


def _validate_suggestion_field(
    field_name: str, value: str, min_len: int, pointer: str
) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidSuggestionContentError(
            f"Suggestion {field_name} must not be empty.",
            pointer=pointer,
            field_name=field_name,
        )
    cleaned = value.strip()
    if len(cleaned) < min_len or cleaned in NOISE_PLACEHOLDERS:
        raise InvalidSuggestionContentError(
            f"Suggestion {field_name} must contain substantive content, got '{cleaned}'.",
            pointer=pointer,
            field_name=field_name,
        )


@dataclass(frozen=True, slots=True)
class CurrentSuggestionInput:
    title: str
    problem: str
    solution: str
    id: str | None = None
    status: SuggestionStatus = SuggestionStatus.PENDING
    context_title: str | None = None

    def __post_init__(self) -> None:
        _validate_suggestion_field("title", self.title, 5, "/data/currentTitle")
        _validate_suggestion_field("problem", self.problem, 5, "/data/currentProblem")
        _validate_suggestion_field(
            "solution", self.solution, 5, "/data/currentSolution"
        )


@dataclass(frozen=True, slots=True)
class SimilarSuggestionInput:
    id: str
    status: SuggestionStatus
    title: str
    problem: str
    solution: str
    similarity: float
    context_title: str | None = None
    reference: Reference | None = None

    def to_generation_chunk(self, index: int = 1) -> GenerationChunk:
        """Adapts this suggestion DTO into a strictly typed GenerationChunk."""
        from src.application.reference.similar_suggestion_reference import (
            SimilarSuggestionReference,
        )

        status_str = (
            self.status.title_fa
            if hasattr(self.status, "title_fa")
            else str(self.status)
        )
        sim_str = f"{float(self.similarity):.2f}"
        ctx_str = f" | حوزه: {self.context_title}" if self.context_title else ""

        ref = self.reference
        if ref is None:
            ref = SimilarSuggestionReference(
                suggestion_id=self.id,
                status=status_str,
                similarity=self.similarity,
                context_title=self.context_title,
            )

        content = (
            f"[پیشنهاد مشابه {index}] کد پیشنهاد: {self.id} | "
            f"وضعیت: {status_str} | میزان تشابه: {sim_str}\n"
            f"عنوان: {self.title}\n"
            f"مسئله: {self.problem}\n"
            f"راهکار: {self.solution}"
        )

        return GenerationChunk(
            chunk_id=self.id,
            content=content,
            reference=ref,
        )

    def validate_with_index(self, index: int) -> None:
        if not self.id or not isinstance(self.id, str) or not self.id.strip():
            raise InvalidSuggestionContentError(
                "Similar suggestion id must not be empty.",
                pointer=f"/data/similarSuggestions/{index}/id",
                field_name="id",
            )
        _validate_suggestion_field(
            "title", self.title, 5, f"/data/similarSuggestions/{index}/title"
        )
        _validate_suggestion_field(
            "problem", self.problem, 5, f"/data/similarSuggestions/{index}/problem"
        )
        _validate_suggestion_field(
            "solution", self.solution, 5, f"/data/similarSuggestions/{index}/solution"
        )
        if (
            self.similarity is None
            or isinstance(self.similarity, bool)
            or not isinstance(self.similarity, (int, float))
            or math.isnan(self.similarity)
            or math.isinf(self.similarity)
        ):
            raise InvalidSuggestionContentError(
                f"Similar suggestion similarity must be a finite float, got {self.similarity!r}.",
                pointer=f"/data/similarSuggestions/{index}/similarity",
                field_name="similarity",
            )


@dataclass(frozen=True, slots=True)
class RegulationInput:
    id: str
    title: str
    content: str
    citation: str | None = None


@dataclass(frozen=True, slots=True)
class GenerationInput:
    current_suggestion: CurrentSuggestionInput
    similar_suggestions: list[SimilarSuggestionInput] = field(default_factory=list)
    regulations: list[RegulationInput] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.current_suggestion is None or not isinstance(
            self.current_suggestion, CurrentSuggestionInput
        ):
            raise InvalidSuggestionContentError(
                "current_suggestion must be a valid CurrentSuggestionInput instance.",
                pointer="/data/currentSuggestion",
                field_name="current_suggestion",
            )
        seen_ids: set[str] = set()
        for idx, item in enumerate(self.similar_suggestions):
            if not isinstance(item, SimilarSuggestionInput):
                raise InvalidSuggestionContentError(
                    f"Expected SimilarSuggestionInput at index {idx}, got {type(item).__name__}.",
                    pointer=f"/data/similarSuggestions/{idx}",
                    field_name="similar_suggestions",
                )
            item.validate_with_index(idx)
            if item.id in seen_ids:
                raise DuplicateEvidenceIdError(
                    f"Duplicate similar suggestion id detected: {item.id!r}",
                    pointer=f"/data/similarSuggestions/{idx}/id",
                    field_name="id",
                )
            seen_ids.add(item.id)


@dataclass(frozen=True, slots=True)
class PreparedGeneration:
    """Fitted prompt and only the original suggestions retained in it."""

    context: ContextBuilderResult
    citation_map: Mapping[str, SimilarSuggestionInput]


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """Validated model answer with original cited evidence."""

    answer: str
    citations: list[GenerationChunk | SimilarSuggestionInput]
    uncertainty: str | None = None


__all__ = [
    "AnalyzeSuggestionResponse",
    "SectionOutput",
    "ContextBuilderResult",
    "CapacityRequest",
    "CapacityAllocation",
    "RedistributionResult",
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
    "CurrentSuggestionInput",
    "SimilarSuggestionInput",
    "RegulationInput",
    "GenerationInput",
    "PreparedGeneration",
    "GenerationResult",
]
