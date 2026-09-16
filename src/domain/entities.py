import dataclasses
import hashlib
import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, TypeAlias, TypeVar

from src.domain.enums import (
    AuthorityLevel,
    ChunkStatus,
    HistoryRole,
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


# region Reference
@dataclass(frozen=True)
class ReferenceDetails:
    """
    Structural description of the currently available properties of a Reference.

    Describes the property *shape* (name and runtime type of each available
    property), not the runtime values. Properties whose value is `None` are
    excluded, so different instances of the same Reference class may produce
    different `ReferenceDetails`.
    """

    properties: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @classmethod
    def from_instance(cls, reference: "Reference") -> "ReferenceDetails":
        if not dataclasses.is_dataclass(reference):
            return cls()
        available: list[tuple[str, str]] = []
        for dataclass_field in dataclasses.fields(reference):
            value = getattr(reference, dataclass_field.name)
            if value is None:
                continue
            available.append((dataclass_field.name, type(value).__name__))
        return cls(properties=tuple(available))

    def canonical(self) -> str:
        """Deterministically sorted canonical descriptor: `name|type,name|type,...`."""
        descriptors = sorted(
            f"{name}|{property_type}"
            for name, property_type in self.properties
        )
        return ",".join(descriptors)

    def hash(self) -> str:
        """Stable hash of the reference property shape (not instance values)."""
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()


class Reference(ABC):
    """
    Domain entity describing where a Section's content originated.

    A `Reference` owns its state, a semantic `description`, its structural
    `ReferenceDetails`, and an optional native `fluent_text()` behavior.
    """

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable meaning of the Reference (not its final rendered text)."""

    @property
    def details(self) -> ReferenceDetails:
        """Structural description of the currently available properties."""
        return ReferenceDetails.from_instance(self)

    def fluent_text(self) -> str:
        """
        Native human-readable rendering of the Reference.

        The base implementation signals that native rendering is unavailable;
        the caller should fall back to the external generation mechanism.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not provide native fluent-text rendering."
        )


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
    "ReferenceDetails",
    "Reference",
    "HistoryMessage"
]
