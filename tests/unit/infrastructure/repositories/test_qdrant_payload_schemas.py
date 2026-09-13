from src.infrastructure.db.repositories.qdrant.payload_schemas import (
    SuggestionChunkPayloadDTO,
)

from src.domain.entities import (
    Chunk,
    ShamsiDate,
    SuggestionChunk,
    SuggestionChunkMetadata,
)
from src.domain.enums import ChunkStatus, SuggestionChunkType, SuggestionStatus


def test_suggestion_payload_dto_roundtrip_with_sub_index():
    metadata = SuggestionChunkMetadata(
        chunk_type=SuggestionChunkType.SOLUTION,
        sub_index=3,
        status=SuggestionStatus.APPROVED,
        context_title="معاونت انتقال",
        date=ShamsiDate("1402/05/20"),
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

    # 2. Payload DTO -> Domain Search Result
    result = dto.to_domain(score=0.92)
    assert result.score == 0.92
    assert result.chunk.chunk_id == "chk-12345"
    assert result.chunk.parent_id == "SUG-999"
    assert result.chunk.metadata.chunk_type == SuggestionChunkType.SOLUTION
    assert result.chunk.metadata.sub_index == 3
    assert result.chunk.metadata.status == SuggestionStatus.APPROVED
    assert result.chunk.metadata.context_title == "معاونت انتقال"
    assert str(result.chunk.metadata.date) == "1402/05/20"


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
    assert result.chunk.metadata.sub_index == 0
