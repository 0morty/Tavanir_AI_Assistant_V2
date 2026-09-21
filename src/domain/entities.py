import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, TypeAlias, TypeVar

from src.domain.enums import (
    AuthorityLevel,
    ChunkStatus,
    CommitteeScrutiny,
    RegulatoryDocumentType,
    SecretariatScrutiny,
    SuggestionChunkType,
    SuggestionStatus,
)
from src.domain.exceptions import (
    InvalidShamsiDateFormatError,
    InvalidSparseVectorError,
    InvalidSuggestionContentError,
    VectorPayloadValidationError,
)

TMetadata = TypeVar("TMetadata")

# Semantic type alias for dense embedding vectors
DenseVector: TypeAlias = Sequence[float]

from src.domain.enums import HistoryRole

NOISE_PLACEHOLDERS: frozenset[str] = frozenset(
    {
        "-",
        "--",
        "---",
        ".",
        "..",
        "...",
        "ندارد",
        "بدون شرح",
        "هیچ",
        "ثبت نشده",
        "موردی ندارد",
        "عدم وجود",
    }
)


@dataclass(frozen=True)
class ShamsiDate:
    value: str

    def __post_init__(self):
        pattern = r"^[1-4]\d{3}/(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])$"
        if not re.match(pattern, self.value):
            raise InvalidShamsiDateFormatError(
                f"Invalid Shamsi date format: '{self.value}'. Expected 'YYYY/MM/DD'."
            )

    def __str__(self) -> str:
        return self.value


# region Suggestion


@dataclass(frozen=True)
class SuggestionContent:
    title: str
    problem: str
    solution: str

    def __post_init__(self):
        self._validate_field("title", self.title, min_len=5, pointer="/data/title")
        self._validate_field(
            "problem", self.problem, min_len=5, pointer="/data/problem"
        )
        self._validate_field(
            "solution", self.solution, min_len=5, pointer="/data/solution"
        )

    @staticmethod
    def _validate_field(
        field_name: str, value: str, min_len: int, pointer: str
    ) -> None:
        if not value or not value.strip():
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


@dataclass(frozen=True)
class SecretariatEvaluation:
    scrutiny: SecretariatScrutiny | None = None
    comment: str | None = None
    scrutiny_id: int | None = None


@dataclass(frozen=True)
class CommitteeEvaluation:
    status: SuggestionStatus
    scrutiny: CommitteeScrutiny | None = None
    description: str | None = None
    scrutiny_id: int | None = None


@dataclass
class Suggestion:
    id: str
    content: SuggestionContent
    evaluation: CommitteeEvaluation
    date: ShamsiDate | None = None
    context_title: str | None = None
    secretariat_evaluation: SecretariatEvaluation | None = None
    is_deleted: bool = False
    version: int = 1

    def mark_deleted(self) -> None:
        """Mark suggestion as soft-deleted."""
        self.is_deleted = True

    def restore(self) -> None:
        """Restore soft-deleted suggestion back to active state."""
        self.is_deleted = False

    def increment_version(self) -> None:
        """Advance optimistic concurrency version token."""
        self.version += 1


# endregion


# region Regulatory Document
@dataclass
class RegulatoryDocument:
    """Master document representing laws, regulations, directives, or guidelines (ADR-003)."""

    id: str
    title: str
    file_name: str
    content: str  # Extracted text/tables representing the full document
    created_at: str | None = None


# endregion


# region Chunk & Metadata
@dataclass(frozen=True)
class SparseVector:
    indices: list[int]
    values: list[float]

    def __post_init__(self):
        if len(self.indices) != len(self.values):
            raise InvalidSparseVectorError(
                f"SparseVector dimension mismatch: {len(self.indices)} indices vs {len(self.values)} values."
            )

    @classmethod
    def from_dict(cls, data: dict[int, float]) -> "SparseVector":
        """Factory creating a deterministically sorted SparseVector from term-weight mapping."""
        if not data:
            return cls(indices=[], values=[])
        sorted_items = sorted(data.items())
        return cls(
            indices=[k for k, _ in sorted_items],
            values=[float(v) for _, v in sorted_items],
        )


@dataclass(frozen=True)
class SuggestionChunkMetadata:
    """Filterable, strongly-typed metadata payload for suggestion child chunks (ADR-002)."""

    chunk_type: SuggestionChunkType
    sub_index: int = 0
    status: SuggestionStatus | None = None
    context_title: str | None = None
    date: ShamsiDate | None = None
    committee_scrutiny: CommitteeScrutiny | None = None
    committee_scrutiny_id: int | None = None
    secretariat_scrutiny: SecretariatScrutiny | None = None
    secretariat_scrutiny_id: int | None = None


@dataclass(frozen=True)
class RegulatoryChunkMetadata:
    """Filterable, strongly-typed lean metadata payload for regulatory chunks (ADR-003)."""

    document_title: str
    document_type: RegulatoryDocumentType
    is_binding: bool = True
    authority_level: AuthorityLevel = AuthorityLevel.BINDING


@dataclass
class Chunk(Generic[TMetadata]):
    """
    Universal vector search chunk carrying strictly-typed metadata.

    Supports both Parent-Child patterns:
    - 1:N SQL Pattern: `parent_id` references the master record in PostgreSQL;
      `parent_content` is None to eliminate storage duplication.
    - 1:1 Zero-SQL Pattern: `parent_id` references the document; `parent_content`
      holds the raw markdown table directly in memory.
    """

    chunk_id: str
    parent_id: (
        str  # ID of parent entity (Suggestion.id in SQL or RegulatoryDocument.id)
    )
    content: str  # Searchable text (field content, article, breadcrumbs+table caption)
    metadata: TMetadata  # Strongly-typed domain metadata
    parent_content: str | None = None  # Populated ONLY for 1:1 zero-SQL blocks (tables)
    dense_vector: DenseVector | None = None
    sparse_vector: SparseVector | None = None
    chunk_status: ChunkStatus = ChunkStatus.ACTIVE

    def __post_init__(self):
        if not self.chunk_id or not self.chunk_id.strip():
            raise VectorPayloadValidationError(
                "Chunk chunk_id must be a non-empty string."
            )
        if not self.parent_id or not self.parent_id.strip():
            raise VectorPayloadValidationError(
                "Chunk parent_id must be a non-empty string."
            )
        if not self.content or not self.content.strip():
            raise VectorPayloadValidationError("Chunk content must not be empty.")


# Type aliases for explicit domain consumption
SuggestionChunk: TypeAlias = Chunk[SuggestionChunkMetadata]
RegulatoryChunk: TypeAlias = Chunk[RegulatoryChunkMetadata]


@dataclass(frozen=True)
class QueryEmbedding:
    """Encapsulates dense and sparse representations of a search query."""

    text: str
    dense_vector: DenseVector
    sparse_vector: SparseVector | None = None


@dataclass(frozen=True)
class SearchResultChunk(Generic[TMetadata]):
    """Standard search hit containing the hydrated chunk and similarity score."""

    chunk: Chunk[TMetadata]
    score: float

    @property
    def parent_id(self) -> str:
        """Convenience direct access to the parent entity ID for MaxP aggregation."""
        return self.chunk.parent_id


SuggestionSearchResult: TypeAlias = SearchResultChunk[SuggestionChunkMetadata]
RegulatorySearchResult: TypeAlias = SearchResultChunk[RegulatoryChunkMetadata]
# endregion


@dataclass(frozen=True)
class HistoryMessage:
    role: HistoryRole
    content: str


__all__ = [
    "ShamsiDate",
    "SuggestionContent",
    "CommitteeEvaluation",
    "Suggestion",
    "RegulatoryDocument",
    "DenseVector",
    "SparseVector",
    "SuggestionChunkMetadata",
    "RegulatoryChunkMetadata",
    "Chunk",
    "SuggestionChunk",
    "RegulatoryChunk",
    "QueryEmbedding",
    "SearchResultChunk",
    "SuggestionSearchResult",
    "RegulatorySearchResult",
    "HistoryMessage",
    "NOISE_PLACEHOLDERS",
]
