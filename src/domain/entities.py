import dataclasses
import hashlib
import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import (
    Any,
    ClassVar,
    Generic,
    TypeAlias,
    TypeVar,
    get_origin,
    get_type_hints,
)
from uuid import UUID

from src.domain.enums import (
    AuthorityLevel,
    ChunkStatus,
    CommitteeScrutiny,
    HistoryRole,
    OutboxEventStatus,
    OutboxEventType,
    OutboxResourceType,
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
        pattern = r"^([1-4]\d{3})/(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])$"
        match = re.match(pattern, self.value)
        if not match:
            raise InvalidShamsiDateFormatError(
                f"Invalid Shamsi date format: '{self.value}'. Expected 'YYYY/MM/DD'."
            )
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))

        if 1 <= month <= 6:
            max_days = 31
        elif 7 <= month <= 11:
            max_days = 30
        else:  # Month 12 (Esfand)
            # Birashk 33-year cycle leap year calculation for Solar Hijri calendar
            is_leap = (year % 33) in (1, 5, 9, 13, 17, 22, 26, 30)
            max_days = 30 if is_leap else 29

        if day > max_days:
            raise InvalidShamsiDateFormatError(
                f"Invalid Shamsi date: '{self.value}'. Month {month:02d} has maximum {max_days} days."
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
    version: int = 1

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


# region Reference
@dataclass(frozen=True)
class ReferenceDetails:
    """
    Structural description of the currently available properties of a Reference.

    Describes the property *shape* (name and declared type of each available
    property), not the runtime values. Properties whose value is `None` or
    unset are excluded, so different instances of the same Reference class
    may produce different `ReferenceDetails`.
    """

    properties: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @classmethod
    def from_instance(cls, reference: "Reference") -> "ReferenceDetails":
        declared: dict[str, object] = {}
        for base in reversed(type(reference).__mro__):
            if base is Reference or not issubclass(base, Reference):
                continue
            declared.update(base.__dict__.get("__annotations__", {}))

        if not declared:
            return cls()

        try:
            resolved = get_type_hints(type(reference))
        except (AttributeError, NameError, TypeError):
            # Locally scoped forward references may not be resolvable here.
            # Their declared text can still describe an available property.
            resolved = {}

        available: list[tuple[str, str]] = []
        for name, raw_type in declared.items():
            declared_type = resolved.get(name, raw_type)
            if get_origin(declared_type) is ClassVar or isinstance(
                declared_type, dataclasses.InitVar
            ):
                continue
            if isinstance(declared_type, str) and declared_type.split("[")[0] in {
                "ClassVar",
                "typing.ClassVar",
                "InitVar",
                "dataclasses.InitVar",
            }:
                continue
            try:
                value = getattr(reference, name)
            except AttributeError:
                continue
            if value is None:
                continue
            if isinstance(declared_type, type):
                type_name = declared_type.__name__
            else:
                type_name = str(declared_type).removeprefix("typing.")
            available.append((name, type_name))
        return cls(properties=tuple(available))

    def canonical(self) -> str:
        """Deterministically sorted canonical descriptor: `name|type,name|type,...`."""
        descriptors = sorted(
            f"{name}|{property_type}" for name, property_type in self.properties
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


@dataclass
class GenerationChunk:
    """Generation-API side representation of a retrieved chunk.

    Owned by the LLM / Generation scope; Retrieval keeps its own ``Chunk``.
    Carries the content that may enter the prompt together with the optional
    Reference used to enrich it. The ``reference`` is never a Retrieval-side
    concern.
    """

    chunk_id: str
    content: str
    reference: Reference | None = None


@dataclass
class OutboxEvent:
    """Domain representation of a transactional outbox record."""

    id: UUID
    resource_type: OutboxResourceType
    resource_id: str
    event_type: OutboxEventType
    version: int
    payload: dict[str, Any]
    status: OutboxEventStatus = OutboxEventStatus.PENDING
    retry_count: int = 0
    last_error: str | None = None
    locked_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    processed_at: datetime | None = None

    def __post_init__(self) -> None:
        if isinstance(self.resource_type, str) and not isinstance(
            self.resource_type, OutboxResourceType
        ):
            self.resource_type = OutboxResourceType(self.resource_type)
        if isinstance(self.event_type, str) and not isinstance(
            self.event_type, OutboxEventType
        ):
            self.event_type = OutboxEventType(self.event_type)
        if isinstance(self.status, str) and not isinstance(
            self.status, OutboxEventStatus
        ):
            self.status = OutboxEventStatus(self.status)


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
    "GenerationChunk",
    "HistoryMessage",
    "OutboxEvent",
    "NOISE_PLACEHOLDERS",
]
