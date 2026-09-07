import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, TypeAlias, TypeVar

from src.domain.enums import (
    AuthorityLevel,
    ChunkStatus,
    RegulatoryDocumentType,
    SuggestionChunkType,
    SuggestionStatus,
)
from src.domain.exceptions import (
    InvalidShamsiDateFormatError,
    InvalidSparseVectorError,
    VectorPayloadValidationError,
)

TMetadata = TypeVar("TMetadata")

# Semantic type alias for dense embedding vectors
DenseVector: TypeAlias = Sequence[float]


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
    problem: str | None
    solution: str | None


@dataclass(frozen=True)
class CommitteeEvaluation:
    status: SuggestionStatus
    scrutiny: str | None
    description: str | None


@dataclass
class Suggestion:
    id: str
    content: SuggestionContent
    evaluation: CommitteeEvaluation
    date: ShamsiDate | None
    context_title: str | None


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
    status: SuggestionStatus | None = None
    context_title: str | None = None
    date: ShamsiDate | None = None


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
SuggestionChunk = Chunk[SuggestionChunkMetadata]
RegulatoryChunk = Chunk[RegulatoryChunkMetadata]


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


SuggestionSearchResult = SearchResultChunk[SuggestionChunkMetadata]
RegulatorySearchResult = SearchResultChunk[RegulatoryChunkMetadata]
# endregion


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
]
