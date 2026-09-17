# pyright: reportIncompatibleMethodOverride=false
from collections.abc import Sequence
from unittest.mock import AsyncMock

import pytest
from src.application.interfaces.i_dense_embedder import IDenseEmbedder
from src.application.interfaces.i_sparse_embedder import ISparseEmbedder
from src.application.interfaces.i_text_normalizer import ITextNormalizer
from src.application.services.hybrid_embedding_service import HybridEmbeddingService
from src.application.use_cases.ingest_suggestion_use_case import IngestSuggestionUseCase

from src.application.dtos import CreateSuggestionDTO, IngestSuggestionResponseDTO
from src.domain.entities import (
    Chunk,
    CommitteeEvaluation,
    SparseVector,
    Suggestion,
    SuggestionChunk,
    SuggestionChunkMetadata,
    SuggestionContent,
)
from src.domain.enums import ChunkStatus, SuggestionChunkType, SuggestionStatus
from src.domain.exceptions import (
    InvalidSuggestionContentError,
    SuggestionAlreadyExistsError,
    SuggestionChunkingError,
    VectorStorageError,
)
from src.domain.interfaces import (
    IChunkingStrategy,
    ISuggestionRepository,
    ISuggestionVectorRepository,
    IUnitOfWork,
)


class FakeSuggestionRepository(ISuggestionRepository):
    get_by_id: AsyncMock = AsyncMock()
    get_by_ids: AsyncMock = AsyncMock()
    save: AsyncMock = AsyncMock()
    save_batch: AsyncMock = AsyncMock()
    delete: AsyncMock = AsyncMock()
    delete_batch: AsyncMock = AsyncMock()

    def __init__(self, existing_suggestion: Suggestion | None = None):
        self.get_by_id = AsyncMock(return_value=existing_suggestion)
        self.get_by_ids = AsyncMock(return_value=[])
        self.save = AsyncMock()
        self.save_batch = AsyncMock()
        self.delete = AsyncMock()
        self.delete_batch = AsyncMock()


class FakeUoW(IUnitOfWork):
    def __init__(self, existing_suggestion: Suggestion | None = None):
        self._suggestions = FakeSuggestionRepository(existing_suggestion)
        self._checkpoints = AsyncMock()
        self._skipped = AsyncMock()
        self.committed = False
        self.rolled_back = False

    @property
    def suggestions(self) -> FakeSuggestionRepository:
        return self._suggestions

    @property
    def checkpoints(self) -> AsyncMock:
        return self._checkpoints

    @property
    def skipped_suggestions(self) -> AsyncMock:
        return self._skipped

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class FakeNormalizer(ITextNormalizer):
    def normalize(self, text: str) -> str:
        return text.strip()

    async def normalize_async(self, text: str) -> str:
        return text.strip()

    def normalize_batch(self, texts: Sequence[str]) -> list[str]:
        return [t.strip() for t in texts]

    async def normalize_batch_async(self, texts: Sequence[str]) -> list[str]:
        return [t.strip() for t in texts]


class FakeChunker(IChunkingStrategy[Suggestion, SuggestionChunkMetadata]):
    def __init__(self, return_chunks: list[SuggestionChunk] | None = None):
        self._return_chunks = return_chunks

    async def chunk(self, document: Suggestion) -> list[SuggestionChunk]:
        if self._return_chunks is not None:
            return self._return_chunks
        return [
            Chunk[SuggestionChunkMetadata](
                chunk_id="chunk-1",
                parent_id=document.id,
                content=document.content.title,
                metadata=SuggestionChunkMetadata(
                    chunk_type=SuggestionChunkType.TITLE,
                    sub_index=0,
                    status=document.evaluation.status,
                ),
            ),
            Chunk[SuggestionChunkMetadata](
                chunk_id="chunk-2",
                parent_id=document.id,
                content=document.content.problem,
                metadata=SuggestionChunkMetadata(
                    chunk_type=SuggestionChunkType.PROBLEM,
                    sub_index=0,
                    status=document.evaluation.status,
                ),
            ),
            Chunk[SuggestionChunkMetadata](
                chunk_id="chunk-3",
                parent_id=document.id,
                content=document.content.solution,
                metadata=SuggestionChunkMetadata(
                    chunk_type=SuggestionChunkType.SOLUTION,
                    sub_index=0,
                    status=document.evaluation.status,
                ),
            ),
        ]


class FakeDenseEmbedder(IDenseEmbedder):
    @property
    def embedding_dimension(self) -> int:
        return 3

    async def embed_documents(
        self, texts: Sequence[str], truncate: bool = True
    ) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]

    async def embed_query(self, query: str, truncate: bool = True) -> list[float]:
        return [0.1, 0.2, 0.3]


class FakeSparseEmbedder(ISparseEmbedder):
    async def embed_document(self, text: str) -> SparseVector:
        return SparseVector(indices=[1, 2], values=[1.0, 0.5])

    async def embed_documents(self, texts: Sequence[str]) -> list[SparseVector]:
        return [SparseVector(indices=[1, 2], values=[1.0, 0.5]) for _ in texts]

    async def embed_query(self, query: str) -> SparseVector:
        return SparseVector(indices=[1, 2], values=[1.0, 0.5])


class FakeVectorRepo(ISuggestionVectorRepository):
    upsert_chunks_batch: AsyncMock = AsyncMock()
    delete_chunks_by_parent_id: AsyncMock = AsyncMock()
    delete_chunks_by_parent_ids: AsyncMock = AsyncMock()
    activate_staging_chunks: AsyncMock = AsyncMock()
    activate_staging_chunks_batch: AsyncMock = AsyncMock()

    def __init__(
        self,
        fail_upsert: bool = False,
        fail_delete: bool = False,
        fail_activate: bool = False,
    ):
        self.fail_upsert = fail_upsert
        self.fail_delete = fail_delete
        self.fail_activate = fail_activate
        self.upsert_chunks_batch = AsyncMock()
        if fail_upsert:
            self.upsert_chunks_batch.side_effect = VectorStorageError(
                "Qdrant cluster unavailable"
            )
        self.delete_chunks_by_parent_id = AsyncMock()
        if fail_delete:
            self.delete_chunks_by_parent_id.side_effect = VectorStorageError(
                "Qdrant cluster unreachable for delete"
            )
        self.delete_chunks_by_parent_ids = AsyncMock()
        self.activate_staging_chunks = AsyncMock()
        if fail_activate:
            self.activate_staging_chunks.side_effect = VectorStorageError(
                "Qdrant payload activation failed"
            )
        self.activate_staging_chunks_batch = AsyncMock()

    async def provision_collection(self, dense_dimension: int | None = None) -> None:
        pass

    async def upsert_chunk(self, chunk: Chunk[SuggestionChunkMetadata]) -> None:
        pass

    async def delete_staging_chunks(self, parent_id: str) -> None:
        pass

    async def delete_deprecated_chunks(self, parent_id: str) -> None:
        pass

    async def search_suggestions(self, *args, **kwargs):
        return []


@pytest.fixture
def valid_dto() -> CreateSuggestionDTO:
    return CreateSuggestionDTO(
        suggestion_id="sugg-101",
        title="عنوان پیشنهاد تست سیستم",
        problem="شرح مشکل سازمانی با جزییات کامل و کافی",
        solution="ارائه راهکار عملیاتی با کیفیت و استاندارد",
        status=SuggestionStatus.APPROVED,
        scrutiny="بررسی شده در جلسه کارگروه تخصصی",
        description="مصوب جهت پیاده‌سازی آزمایشی",
        shamsi_date="1402/08/15",
        context_title="توزیع نیروی برق",
    )


@pytest.mark.asyncio
async def test_successful_ingestion_flow(valid_dto):
    uow = FakeUoW()
    normalizer = FakeNormalizer()
    chunker = FakeChunker()
    dense = FakeDenseEmbedder()
    sparse = FakeSparseEmbedder()
    embedding_service = HybridEmbeddingService(dense, sparse)
    vector_repo = FakeVectorRepo()

    use_case = IngestSuggestionUseCase(
        uow=uow,
        normalizer=normalizer,
        chunker=chunker,
        embedding_service=embedding_service,
        vector_repo=vector_repo,
    )

    result = await use_case.execute(valid_dto)

    assert isinstance(result, IngestSuggestionResponseDTO)
    assert result.suggestion_id == "sugg-101"
    assert result.chunks_count == 3
    assert result.status == "CREATED"

    # Verify short-lived pre-check called
    uow.suggestions.get_by_id.assert_awaited_once_with("sugg-101")

    # Verify SQL save called with normalized entity
    uow.suggestions.save.assert_awaited_once()
    saved_entity: Suggestion = uow.suggestions.save.call_args[0][0]
    assert saved_entity.id == "sugg-101"
    assert saved_entity.content.title == "عنوان پیشنهاد تست سیستم"

    # Verify pre-emptive Qdrant purge was executed prior to upsert
    vector_repo.delete_chunks_by_parent_id.assert_any_await("sugg-101")

    # Verify Qdrant batch upsert called with fully embedded chunks tagged as STAGING
    vector_repo.upsert_chunks_batch.assert_awaited_once()
    upserted_chunks = vector_repo.upsert_chunks_batch.call_args[0][0]
    assert len(upserted_chunks) == 3
    for chunk in upserted_chunks:
        assert chunk.chunk_status == ChunkStatus.STAGING
        assert chunk.dense_vector == [0.1, 0.2, 0.3]
        assert chunk.sparse_vector == SparseVector(indices=[1, 2], values=[1.0, 0.5])

    # Verify atomic staging activation
    vector_repo.activate_staging_chunks.assert_awaited_once_with("sugg-101")


@pytest.mark.asyncio
async def test_duplicate_suggestion_raises_conflict(valid_dto):
    existing = Suggestion(
        id="sugg-101",
        content=SuggestionContent(
            title="عنوان قدیمی",
            problem="مشکل قبلی ثبت شده",
            solution="راهکار قبلی ثبت شده",
        ),
        evaluation=CommitteeEvaluation(
            status=SuggestionStatus.APPROVED, scrutiny=None, description=None
        ),
        date=None,
        context_title=None,
    )
    uow = FakeUoW(existing_suggestion=existing)
    vector_repo = FakeVectorRepo()

    use_case = IngestSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        embedding_service=HybridEmbeddingService(
            FakeDenseEmbedder(), FakeSparseEmbedder()
        ),
        vector_repo=vector_repo,
    )

    with pytest.raises(SuggestionAlreadyExistsError) as exc_info:
        await use_case.execute(valid_dto)

    assert "sugg-101" in str(exc_info.value)
    assert exc_info.value.pointer == "/data/suggestionId"
    # Gatekeeper verification: neither SQL nor Qdrant mutations/deletions occurred
    uow.suggestions.save.assert_not_called()
    vector_repo.upsert_chunks_batch.assert_not_called()
    vector_repo.delete_chunks_by_parent_id.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_content_raises_domain_error():
    uow = FakeUoW()
    use_case = IngestSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        embedding_service=HybridEmbeddingService(
            FakeDenseEmbedder(), FakeSparseEmbedder()
        ),
        vector_repo=FakeVectorRepo(),
    )

    # Problem is noise placeholder
    bad_dto = CreateSuggestionDTO(
        suggestion_id="sugg-102",
        title="عنوان معتبر و استاندارد",
        problem="ندارد",
        solution="راهکار معتبر و استاندارد سازمانی",
        status=SuggestionStatus.PENDING,
    )

    with pytest.raises(InvalidSuggestionContentError) as exc_info:
        await use_case.execute(bad_dto)

    assert exc_info.value.pointer == "/data/problem"
    uow.suggestions.save.assert_not_called()


@pytest.mark.asyncio
async def test_empty_chunks_raises_chunking_error(valid_dto):
    uow = FakeUoW()
    chunker = FakeChunker(return_chunks=[])
    use_case = IngestSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=chunker,
        embedding_service=HybridEmbeddingService(
            FakeDenseEmbedder(), FakeSparseEmbedder()
        ),
        vector_repo=FakeVectorRepo(),
    )

    with pytest.raises(SuggestionChunkingError) as exc_info:
        await use_case.execute(valid_dto)

    assert "0 chunks" in str(exc_info.value)
    uow.suggestions.save.assert_not_called()


@pytest.mark.asyncio
async def test_qdrant_failure_triggers_compensating_deletion(valid_dto):
    uow = FakeUoW()
    vector_repo = FakeVectorRepo(fail_upsert=True)

    use_case = IngestSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        embedding_service=HybridEmbeddingService(
            FakeDenseEmbedder(), FakeSparseEmbedder()
        ),
        vector_repo=vector_repo,
    )

    with pytest.raises(VectorStorageError) as exc_info:
        await use_case.execute(valid_dto)

    assert "Qdrant cluster unavailable" in str(exc_info.value)

    # SQL save was called first
    uow.suggestions.save.assert_awaited_once()
    # Compensating Qdrant delete was called (both pre-emptive and rollback)
    assert vector_repo.delete_chunks_by_parent_id.await_count >= 1
    # Compensating SQL delete was called to rollback
    uow.suggestions.delete.assert_awaited_once_with("sugg-101")


@pytest.mark.asyncio
async def test_compensating_deletion_failure_does_not_mask_qdrant_error(valid_dto):
    uow = FakeUoW()
    uow.suggestions.delete.side_effect = RuntimeError(
        "Database connection dropped during rollback"
    )
    vector_repo = FakeVectorRepo(fail_upsert=True)

    use_case = IngestSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        embedding_service=HybridEmbeddingService(
            FakeDenseEmbedder(), FakeSparseEmbedder()
        ),
        vector_repo=vector_repo,
    )

    # Must raise original VectorStorageError, NOT the RuntimeError from compensation
    with pytest.raises(VectorStorageError) as exc_info:
        await use_case.execute(valid_dto)

    assert "Qdrant cluster unavailable" in str(exc_info.value)


@pytest.mark.asyncio
async def test_qdrant_cleanup_failure_does_not_block_sql_rollback(valid_dto):
    uow = FakeUoW()
    # Qdrant fails on upsert; pre-emptive delete succeeds, but compensating delete fails
    vector_repo = FakeVectorRepo(fail_upsert=True)
    vector_repo.delete_chunks_by_parent_id.side_effect = [
        None,
        VectorStorageError("Qdrant cluster unreachable for rollback delete"),
    ]

    use_case = IngestSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        embedding_service=HybridEmbeddingService(
            FakeDenseEmbedder(), FakeSparseEmbedder()
        ),
        vector_repo=vector_repo,
    )

    with pytest.raises(VectorStorageError) as exc_info:
        await use_case.execute(valid_dto)

    # SQL rollback MUST still be called even if Qdrant cleanup fails
    uow.suggestions.delete.assert_awaited_once_with("sugg-101")
    assert "Qdrant cluster unavailable" in str(exc_info.value)


@pytest.mark.asyncio
async def test_qdrant_activation_failure_triggers_compensation(valid_dto):
    uow = FakeUoW()
    # Upsert succeeds, but activation fails
    vector_repo = FakeVectorRepo(fail_upsert=False, fail_activate=True)

    use_case = IngestSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        embedding_service=HybridEmbeddingService(
            FakeDenseEmbedder(), FakeSparseEmbedder()
        ),
        vector_repo=vector_repo,
    )

    with pytest.raises(VectorStorageError) as exc_info:
        await use_case.execute(valid_dto)

    assert "Qdrant payload activation failed" in str(exc_info.value)
    # Both SQL and Qdrant compensation called
    vector_repo.delete_chunks_by_parent_id.assert_awaited()
    uow.suggestions.delete.assert_awaited_once_with("sugg-101")
