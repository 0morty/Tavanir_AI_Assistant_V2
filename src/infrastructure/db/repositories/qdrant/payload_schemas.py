from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from src.domain.entities import (
    Chunk,
    RegulatoryChunkMetadata,
    RegulatorySearchResult,
    SearchResultChunk,
    ShamsiDate,
    SuggestionChunkMetadata,
    SuggestionSearchResult,
)
from src.domain.enums import (
    AuthorityLevel,
    ChunkStatus,
    CommitteeScrutiny,
    RegulatoryDocumentType,
    SecretariatScrutiny,
    SuggestionChunkType,
    SuggestionStatus,
)


class BaseChunkPayloadDTO(BaseModel):
    """Base Pydantic payload transfer model for Qdrant payload serialization."""

    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    parent_id: str
    content: str
    chunk_status: str = ChunkStatus.ACTIVE.value
    parent_content: str | None = None


class SuggestionChunkPayloadDTO(BaseChunkPayloadDTO):
    """DTO for serializing/deserializing suggestion chunks to/from Qdrant payload."""

    chunk_type: str
    sub_index: int = 0
    status: str | None = None
    context_title: str | None = None
    date: str | None = None
    committee_scrutiny: str | None = None
    committee_scrutiny_id: int | None = None
    secretariat_scrutiny: str | None = None
    secretariat_scrutiny_id: int | None = None

    @classmethod
    def from_domain(
        cls, chunk: Chunk[SuggestionChunkMetadata]
    ) -> SuggestionChunkPayloadDTO:
        com_scrutiny = (
            chunk.metadata.committee_scrutiny.title_fa
            if isinstance(chunk.metadata.committee_scrutiny, CommitteeScrutiny)
            else (
                str(chunk.metadata.committee_scrutiny)
                if chunk.metadata.committee_scrutiny
                else None
            )
        )
        com_scrutiny_id = (
            chunk.metadata.committee_scrutiny.code
            if isinstance(chunk.metadata.committee_scrutiny, CommitteeScrutiny)
            else chunk.metadata.committee_scrutiny_id
        )
        sec_scrutiny = (
            chunk.metadata.secretariat_scrutiny.title_fa
            if isinstance(chunk.metadata.secretariat_scrutiny, SecretariatScrutiny)
            else (
                str(chunk.metadata.secretariat_scrutiny)
                if chunk.metadata.secretariat_scrutiny
                else None
            )
        )
        sec_scrutiny_id = (
            chunk.metadata.secretariat_scrutiny.code
            if isinstance(chunk.metadata.secretariat_scrutiny, SecretariatScrutiny)
            else chunk.metadata.secretariat_scrutiny_id
        )
        return cls(
            chunk_id=chunk.chunk_id,
            parent_id=chunk.parent_id,
            content=chunk.content,
            parent_content=chunk.parent_content,
            chunk_status=chunk.chunk_status.value,
            chunk_type=chunk.metadata.chunk_type.value,
            sub_index=chunk.metadata.sub_index,
            status=chunk.metadata.status.title_fa if chunk.metadata.status else None,
            context_title=chunk.metadata.context_title,
            date=str(chunk.metadata.date) if chunk.metadata.date else None,
            committee_scrutiny=com_scrutiny,
            committee_scrutiny_id=com_scrutiny_id,
            secretariat_scrutiny=sec_scrutiny,
            secretariat_scrutiny_id=sec_scrutiny_id,
        )

    def to_domain(self, score: float = 0.0) -> SuggestionSearchResult:
        com_enum: CommitteeScrutiny | None = None
        if self.committee_scrutiny_id is not None:
            try:
                com_enum = CommitteeScrutiny.from_code(self.committee_scrutiny_id)
            except Exception:
                pass
        elif self.committee_scrutiny:
            try:
                com_enum = CommitteeScrutiny.from_string(self.committee_scrutiny)
            except Exception:
                pass

        sec_enum: SecretariatScrutiny | None = None
        if self.secretariat_scrutiny_id is not None:
            try:
                sec_enum = SecretariatScrutiny.from_code(self.secretariat_scrutiny_id)
            except Exception:
                pass
        elif self.secretariat_scrutiny:
            try:
                sec_enum = SecretariatScrutiny.from_string(self.secretariat_scrutiny)
            except Exception:
                pass

        metadata = SuggestionChunkMetadata(
            chunk_type=SuggestionChunkType(self.chunk_type),
            sub_index=self.sub_index,
            status=SuggestionStatus.from_string(self.status) if self.status else None,
            context_title=self.context_title,
            date=ShamsiDate(self.date) if self.date else None,
            committee_scrutiny=com_enum,
            committee_scrutiny_id=self.committee_scrutiny_id,
            secretariat_scrutiny=sec_enum,
            secretariat_scrutiny_id=self.secretariat_scrutiny_id,
        )
        chunk = Chunk[SuggestionChunkMetadata](
            chunk_id=self.chunk_id,
            parent_id=self.parent_id,
            content=self.content,
            metadata=metadata,
            parent_content=self.parent_content,
            chunk_status=ChunkStatus(self.chunk_status),
        )
        return SearchResultChunk[SuggestionChunkMetadata](chunk=chunk, score=score)


class RegulatoryChunkPayloadDTO(BaseChunkPayloadDTO):
    """DTO for serializing/deserializing regulatory knowledge chunks to/from Qdrant payload."""

    document_title: str
    document_type: str
    is_binding: bool = True
    authority_level: str = AuthorityLevel.BINDING.value

    @classmethod
    def from_domain(
        cls, chunk: Chunk[RegulatoryChunkMetadata]
    ) -> RegulatoryChunkPayloadDTO:
        return cls(
            chunk_id=chunk.chunk_id,
            parent_id=chunk.parent_id,
            content=chunk.content,
            parent_content=chunk.parent_content,
            chunk_status=chunk.chunk_status.value,
            document_title=chunk.metadata.document_title,
            document_type=chunk.metadata.document_type.value,
            is_binding=chunk.metadata.is_binding,
            authority_level=chunk.metadata.authority_level.value,
        )

    def to_domain(self, score: float = 0.0) -> RegulatorySearchResult:
        metadata = RegulatoryChunkMetadata(
            document_title=self.document_title,
            document_type=RegulatoryDocumentType(self.document_type),
            is_binding=self.is_binding,
            authority_level=AuthorityLevel(self.authority_level),
        )
        chunk = Chunk[RegulatoryChunkMetadata](
            chunk_id=self.chunk_id,
            parent_id=self.parent_id,
            content=self.content,
            metadata=metadata,
            parent_content=self.parent_content,
            chunk_status=ChunkStatus(self.chunk_status),
        )
        return SearchResultChunk[RegulatoryChunkMetadata](chunk=chunk, score=score)


__all__ = [
    "BaseChunkPayloadDTO",
    "SuggestionChunkPayloadDTO",
    "RegulatoryChunkPayloadDTO",
]
