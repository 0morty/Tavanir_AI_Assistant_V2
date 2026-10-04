from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from src.application.interfaces.i_text_normalizer import ITextNormalizer
from src.application.services.outbox.handlers import (
    IngestSuggestionVectorsHandler,
    PurgeSuggestionVectorsHandler,
    UpdateSuggestionVectorsHandler,
)

from src.application.interfaces import IUnitOfWork
from src.domain.entities import (
    Chunk,
    CommitteeEvaluation,
    OutboxEvent,
    SparseVector,
    Suggestion,
    SuggestionChunk,
    SuggestionChunkMetadata,
    SuggestionContent,
)
from src.domain.enums import ChunkStatus, SuggestionChunkType, SuggestionStatus
from src.domain.interfaces import (
    ISuggestionChunker,
    ISuggestionRepository,
    ISuggestionVectorRepository,
)


class DummyNormalizer(ITextNormalizer):
    def normalize(self, text: str) -> str:
        return text.strip()

    async def normalize_async(self, text: str) -> str:
        return text.strip()

    def normalize_batch(self, texts: list[str]) -> list[str]:
        return [t.strip() for t in texts]

    async def normalize_batch_async(self, texts: list[str]) -> list[str]:
        return [t.strip() for t in texts]


def make_dummy_chunk(suggestion_id: str, version: int = 1) -> SuggestionChunk:
    return Chunk[SuggestionChunkMetadata](
        chunk_id=f"{suggestion_id}-chunk-0",
        parent_id=suggestion_id,
        content="Test suggestion title",
        metadata=SuggestionChunkMetadata(
            chunk_type=SuggestionChunkType.TITLE,
            sub_index=0,
            status=SuggestionStatus.APPROVED,
        ),
        dense_vector=[0.1] * 10,
        sparse_vector=SparseVector(indices=[1], values=[1.0]),
        chunk_status=ChunkStatus.ACTIVE,
        version=version,
    )


@pytest.mark.asyncio
async def test_ingest_handler_purges_orphans_before_storing_active_vectors():
    mock_chunker = AsyncMock(spec=ISuggestionChunker)
    mock_embedding_service = AsyncMock()
    mock_vector_repo = AsyncMock(spec=ISuggestionVectorRepository)
    mock_uow = AsyncMock(spec=IUnitOfWork)
    mock_suggestion_repo = AsyncMock(spec=ISuggestionRepository)

    existing_suggestion = Suggestion(
        id="sugg-1",
        content=SuggestionContent(
            title="Title 1",
            problem="Problem 1",
            solution="Solution 1",
        ),
        evaluation=CommitteeEvaluation(status=SuggestionStatus.APPROVED),
        version=1,
    )
    mock_suggestion_repo.get_by_id = AsyncMock(return_value=existing_suggestion)
    mock_uow.suggestions = mock_suggestion_repo

    chunk = make_dummy_chunk("sugg-1", version=1)
    mock_chunker.chunk = AsyncMock(return_value=[chunk])
    mock_embedding_service.embed_chunks = AsyncMock(return_value=[chunk])

    handler = IngestSuggestionVectorsHandler(
        chunker=mock_chunker,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        normalizer=DummyNormalizer(),
    )

    event = OutboxEvent(
        id=uuid4(),
        resource_type="SUGGESTION",
        resource_id="sugg-1",
        event_type="SUGGESTION_INGESTED",
        version=1,
        payload={"id": "sugg-1"},
    )

    await handler.handle(event, mock_uow)

    assert event.status != "SUPERSEDED"
    # Verify orphan purge called
    mock_vector_repo.delete_chunks_by_parent_id.assert_awaited_once_with("sugg-1")
    # Verify chunks stored with ACTIVE status directly
    mock_vector_repo.upsert_chunks_batch.assert_awaited_once_with([chunk])


@pytest.mark.asyncio
async def test_update_handler_supersedes_if_newer_version_committed():
    mock_chunker = AsyncMock(spec=ISuggestionChunker)
    mock_embedding_service = AsyncMock()
    mock_vector_repo = AsyncMock(spec=ISuggestionVectorRepository)
    mock_uow = AsyncMock(spec=IUnitOfWork)
    mock_suggestion_repo = AsyncMock(spec=ISuggestionRepository)

    current_suggestion = Suggestion(
        id="sugg-2",
        content=SuggestionContent(
            title="Title v3",
            problem="Problem v3",
            solution="Solution v3",
        ),
        evaluation=CommitteeEvaluation(status=SuggestionStatus.APPROVED),
        version=3,
    )
    mock_suggestion_repo.get_by_id = AsyncMock(return_value=current_suggestion)
    mock_uow.suggestions = mock_suggestion_repo

    handler = UpdateSuggestionVectorsHandler(
        chunker=mock_chunker,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        normalizer=DummyNormalizer(),
    )

    event = OutboxEvent(
        id=uuid4(),
        resource_type="SUGGESTION",
        resource_id="sugg-2",
        event_type="SUGGESTION_UPDATED",
        version=2,
        payload={"id": "sugg-2"},
    )

    await handler.handle(event, mock_uow)

    assert event.status == "SUPERSEDED"
    mock_vector_repo.upsert_chunks_batch.assert_not_called()
    mock_vector_repo.activate_version_chunks.assert_not_called()
    mock_vector_repo.delete_obsolete_version_chunks.assert_not_called()


@pytest.mark.asyncio
async def test_update_handler_idempotent_cutover_on_retry():
    mock_chunker = AsyncMock(spec=ISuggestionChunker)
    mock_embedding_service = AsyncMock()
    mock_vector_repo = AsyncMock(spec=ISuggestionVectorRepository)
    mock_uow = AsyncMock(spec=IUnitOfWork)
    mock_suggestion_repo = AsyncMock(spec=ISuggestionRepository)

    current_suggestion = Suggestion(
        id="sugg-3",
        content=SuggestionContent(
            title="Title v2",
            problem="Problem v2",
            solution="Solution v2",
        ),
        evaluation=CommitteeEvaluation(status=SuggestionStatus.APPROVED),
        version=2,
    )
    mock_suggestion_repo.get_by_id = AsyncMock(return_value=current_suggestion)
    mock_uow.suggestions = mock_suggestion_repo

    chunk_v2 = make_dummy_chunk("sugg-3", version=2)
    mock_chunker.chunk = AsyncMock(return_value=[chunk_v2])
    mock_embedding_service.embed_chunks = AsyncMock(return_value=[chunk_v2])

    handler = UpdateSuggestionVectorsHandler(
        chunker=mock_chunker,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        normalizer=DummyNormalizer(),
    )

    event = OutboxEvent(
        id=uuid4(),
        resource_type="SUGGESTION",
        resource_id="sugg-3",
        event_type="SUGGESTION_UPDATED",
        version=2,
        payload={"id": "sugg-3"},
    )

    await handler.handle(event, mock_uow)

    assert event.status != "SUPERSEDED"
    # Verify staging upsert
    mock_vector_repo.upsert_chunks_batch.assert_awaited_once_with([chunk_v2])
    # Verify idempotent promotion of version 2 points
    mock_vector_repo.activate_version_chunks.assert_awaited_once_with(
        parent_id="sugg-3", target_version=2
    )
    # Verify cleanup of obsolete version < 2 points
    mock_vector_repo.delete_obsolete_version_chunks.assert_awaited_once_with(
        parent_id="sugg-3", max_version_exclusive=2
    )


@pytest.mark.asyncio
async def test_purge_handler_deletes_all_points():
    mock_vector_repo = AsyncMock(spec=ISuggestionVectorRepository)
    mock_uow = AsyncMock(spec=IUnitOfWork)
    mock_suggestion_repo = AsyncMock(spec=ISuggestionRepository)

    soft_deleted_suggestion = Suggestion(
        id="sugg-4",
        content=SuggestionContent(
            title="Title",
            problem="Problem",
            solution="Solution",
        ),
        evaluation=CommitteeEvaluation(status=SuggestionStatus.APPROVED),
        version=3,
        is_deleted=True,
    )
    mock_suggestion_repo.get_by_id = AsyncMock(return_value=soft_deleted_suggestion)
    mock_uow.suggestions = mock_suggestion_repo

    handler = PurgeSuggestionVectorsHandler(vector_repo=mock_vector_repo)

    event = OutboxEvent(
        id=uuid4(),
        resource_type="SUGGESTION",
        resource_id="sugg-4",
        event_type="SUGGESTION_DELETED",
        version=3,
        payload={"id": "sugg-4"},
    )

    await handler.handle(event, mock_uow)

    assert event.status != "SUPERSEDED"
    mock_vector_repo.delete_chunks_by_parent_id.assert_awaited_once_with("sugg-4")
