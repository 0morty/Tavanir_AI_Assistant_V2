from src.infrastructure.db.repositories.qdrant.payload_schemas import (
    SuggestionChunkPayloadDTO,
)

from src.domain.entities import (
    Chunk,
    ShamsiDate,
    SuggestionChunk,
    SuggestionChunkMetadata,
)
from src.domain.enums import (
    ChunkStatus,
    CommitteeScrutiny,
    SecretariatScrutiny,
    SuggestionChunkType,
    SuggestionStatus,
)


def test_suggestion_payload_dto_roundtrip_with_sub_index():
    metadata = SuggestionChunkMetadata(
        chunk_type=SuggestionChunkType.SOLUTION,
        sub_index=3,
        status=SuggestionStatus.APPROVED,
        context_title="معاونت انتقال",
        date=ShamsiDate("1402/05/20"),
        committee_scrutiny=CommitteeScrutiny.APPROVED,
        committee_scrutiny_id=0,
        secretariat_scrutiny=SecretariatScrutiny.REFER_TO_COMMITTEE,
        secretariat_scrutiny_id=3,
    )
    chunk: SuggestionChunk = Chunk(
        chunk_id="chk-12345",
        parent_id="SUG-999",
        content="نصب ترانسفورماتور کم‌تلفات",
        metadata=metadata,
        parent_content=None,
        chunk_status=ChunkStatus.ACTIVE,
    )

    # 1. Domain -> Payload DTO
    dto = SuggestionChunkPayloadDTO.from_domain(chunk)
    assert dto.chunk_id == "chk-12345"
    assert dto.parent_id == "SUG-999"
    assert dto.content == "نصب ترانسفورماتور کم‌تلفات"
    assert dto.chunk_type == "solution"
    assert dto.sub_index == 3
    assert dto.status == "مصوب"
    assert dto.context_title == "معاونت انتقال"
    assert dto.date == "1402/05/20"
    assert dto.committee_scrutiny == "تایید"
    assert dto.committee_scrutiny_id == 0
    assert dto.secretariat_scrutiny == "ارجاع به کمیته"
    assert dto.secretariat_scrutiny_id == 3

    # 2. Payload DTO -> Domain Search Result
    result = dto.to_domain(score=0.92)
    assert result.score == 0.92
    assert result.chunk.chunk_id == "chk-12345"
    assert result.chunk.parent_id == "SUG-999"
    meta = result.chunk.metadata
    assert isinstance(meta, SuggestionChunkMetadata)
    assert meta.chunk_type == SuggestionChunkType.SOLUTION
    assert meta.sub_index == 3
    assert meta.status == SuggestionStatus.APPROVED
    assert meta.context_title == "معاونت انتقال"
    assert str(meta.date) == "1402/05/20"
    assert meta.committee_scrutiny == CommitteeScrutiny.APPROVED
    assert meta.committee_scrutiny_id == 0
    assert meta.secretariat_scrutiny == SecretariatScrutiny.REFER_TO_COMMITTEE
    assert meta.secretariat_scrutiny_id == 3


def test_suggestion_payload_dto_default_sub_index():
    metadata = SuggestionChunkMetadata(
        chunk_type=SuggestionChunkType.TITLE,
    )
    chunk: SuggestionChunk = Chunk(
        chunk_id="chk-title-1",
        parent_id="SUG-100",
        content="عنوان آزمایشی",
        metadata=metadata,
    )

    dto = SuggestionChunkPayloadDTO.from_domain(chunk)
    assert dto.sub_index == 0

    result = dto.to_domain()
    meta = result.chunk.metadata
    assert isinstance(meta, SuggestionChunkMetadata)
    assert meta.sub_index == 0
