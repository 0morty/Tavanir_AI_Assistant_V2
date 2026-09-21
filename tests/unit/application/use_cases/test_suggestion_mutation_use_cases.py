from collections.abc import Sequence
from unittest.mock import AsyncMock

import pytest
from src.application.interfaces.i_dense_embedder import IDenseEmbedder
from src.application.interfaces.i_sparse_embedder import ISparseEmbedder
from src.application.interfaces.i_text_normalizer import ITextNormalizer
from src.application.services.hybrid_embedding_service import HybridEmbeddingService

from src.application.dtos import (
    BulkDeleteSuggestionsDTO,
    PatchSuggestionDTO,
    UpdateSuggestionDTO,
)
from src.application.interfaces import IUnitOfWork
from src.application.use_cases import (
    BulkDeleteSuggestionsUseCase,
    DeleteSuggestionUseCase,
    UpdateSuggestionUseCase,
)
from src.domain.entities import (
    Chunk,
    CommitteeEvaluation,
    DenseVector,
    SparseVector,
    Suggestion,
    SuggestionChunk,
    SuggestionChunkMetadata,
    SuggestionContent,
)
from src.domain.enums import (
    ChunkStatus,
    CommitteeScrutiny,
    SuggestionChunkType,
    SuggestionStatus,
)
from src.domain.exceptions import (
    SuggestionNotFoundError,
    SuggestionProcessingConflictError,
    VectorStorageError,
)
from src.domain.interfaces import (
    ISuggestionChunker,
    ISuggestionRepository,
    ISuggestionVectorRepository,
)


class FakeSuggestionRepo(ISuggestionRepository):
    def __init__(self, initial_suggestions: list[Suggestion] | None = None):
        self.suggestions: dict[str, Suggestion] = {
            s.id: s for s in (initial_suggestions or [])
        }
        self.save_called = False
        self.soft_delete_called = False
        self.fail_save = False

    async def get_by_id(
        self, suggestion_id: str, include_deleted: bool = False
    ) -> Suggestion | None:
        s = self.suggestions.get(suggestion_id)
        if s is None:
            return None
        if not include_deleted and s.is_deleted:
            return None
        return s

    async def get_by_ids(
        self, suggestion_ids: Sequence[str], include_deleted: bool = False
    ) -> list[Suggestion]:
        results = []
        for sid in suggestion_ids:
            s = self.suggestions.get(sid)
            if s and (include_deleted or not s.is_deleted):
                results.append(s)
        return results

    async def save(self, suggestion: Suggestion) -> None:
        if self.fail_save:
            raise RuntimeError("PostgreSQL connection failure on save")
        self.suggestions[suggestion.id] = suggestion
        self.save_called = True

    async def save_batch(self, suggestions: Sequence[Suggestion]) -> None:
        for s in suggestions:
            await self.save(s)

    async def delete(self, suggestion_id: str) -> None:
        self.suggestions.pop(suggestion_id, None)

    async def delete_batch(self, suggestion_ids: Sequence[str]) -> None:
        for sid in suggestion_ids:
            self.suggestions.pop(sid, None)

    async def soft_delete(self, suggestion_id: str) -> None:
        s = self.suggestions.get(suggestion_id)
        if s:
            s.mark_deleted()
            self.soft_delete_called = True


class FakeUoW(IUnitOfWork):
    def __init__(self, repo: FakeSuggestionRepo, lock_succeeds: bool = True):
        self._repo = repo
        self._lock_succeeds = lock_succeeds
        self.lock_keys: list[int] = []
        self.committed = False
        self.rolled_back = False

    @property
    def suggestions(self) -> FakeSuggestionRepo:
        return self._repo

    @property
    def checkpoints(self) -> AsyncMock:
        return AsyncMock()

    @property
    def skipped_suggestions(self) -> AsyncMock:
        return AsyncMock()

    async def try_acquire_advisory_lock(self, lock_key: int) -> bool:
        self.lock_keys.append(lock_key)
        return self._lock_succeeds

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


class FakeChunker(ISuggestionChunker):
    async def chunk(self, document: Suggestion) -> list[SuggestionChunk]:
        metadata = SuggestionChunkMetadata(
            chunk_type=SuggestionChunkType.TITLE,
            status=document.evaluation.status,
            committee_scrutiny=document.evaluation.scrutiny,
        )
        return [
            Chunk[SuggestionChunkMetadata](
                chunk_id=f"chunk-{document.id}-1",
                parent_id=document.id,
                content=document.content.title,
                metadata=metadata,
                chunk_status=ChunkStatus.ACTIVE,
            )
        ]


class FakeDenseEmbedder(IDenseEmbedder):
    @property
    def embedding_dimension(self) -> int:
        return 3

    async def embed(self, text: str) -> DenseVector:
        return (0.1, 0.2, 0.3)

    async def embed_batch(self, texts: Sequence[str]) -> list[DenseVector]:
        return [(0.1, 0.2, 0.3) for _ in texts]

    async def embed_documents(
        self, texts: Sequence[str], truncate: bool = True
    ) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]

    async def embed_query(self, query: str, truncate: bool = True) -> list[float]:
        return [0.1, 0.2, 0.3]


class FakeSparseEmbedder(ISparseEmbedder):
    def embed_sparse(self, text: str) -> SparseVector:
        return SparseVector(indices=[1, 2], values=[0.5, 0.8])

    def embed_sparse_batch(self, texts: Sequence[str]) -> list[SparseVector]:
        return [SparseVector(indices=[1, 2], values=[0.5, 0.8]) for _ in texts]

    async def embed_document(self, text: str) -> SparseVector:
        return SparseVector(indices=[1, 2], values=[1.0, 0.5])

    async def embed_documents(self, texts: Sequence[str]) -> list[SparseVector]:
        return [SparseVector(indices=[1, 2], values=[1.0, 0.5]) for _ in texts]

    async def embed_query(self, query: str) -> SparseVector:
        return SparseVector(indices=[1, 2], values=[1.0, 0.5])


class FakeVectorRepo(ISuggestionVectorRepository):
    def __init__(self, fail_delete: bool = False):
        self.staged_chunks: list[SuggestionChunk] = []
        self.deleted_parent_ids: list[str] = []
        self.deleted_chunk_ids: list[str] = []
        self.activated_parent_ids: list[str] = []
        self.superseded_calls: list[tuple[str, list[str]]] = []
        self.fail_delete = fail_delete

    async def provision_collection(self, dense_dimension: int | None = None) -> None:
        pass

    async def upsert_chunk(self, chunk: Chunk[SuggestionChunkMetadata]) -> None:
        pass

    async def upsert_chunks_batch(
        self, chunks: Sequence[Chunk[SuggestionChunkMetadata]]
    ) -> None:
        self.staged_chunks.extend(chunks)  # type: ignore

    async def delete_chunks_by_parent_id(self, parent_id: str) -> None:
        if self.fail_delete:
            raise VectorStorageError("Qdrant cluster unreachable for delete")
        self.deleted_parent_ids.append(parent_id)

    async def delete_chunks_by_parent_ids(self, parent_ids: Sequence[str]) -> None:
        self.deleted_parent_ids.extend(parent_ids)

    async def delete_staging_chunks(self, parent_id: str) -> None:
        pass

    async def activate_staging_chunks(self, parent_id: str) -> None:
        self.activated_parent_ids.append(parent_id)

    async def activate_staging_chunks_batch(self, parent_ids: Sequence[str]) -> None:
        self.activated_parent_ids.extend(parent_ids)

    async def delete_deprecated_chunks(self, parent_id: str) -> None:
        pass

    async def delete_chunks_by_ids(self, chunk_ids: Sequence[str]) -> None:
        self.deleted_chunk_ids.extend(chunk_ids)

    async def delete_superseded_chunks(
        self, parent_id: str, active_chunk_ids: Sequence[str]
    ) -> None:
        self.superseded_calls.append((parent_id, list(active_chunk_ids)))

    async def search_suggestions(self, *args, **kwargs):
        return []


def create_sample_suggestion(
    suggestion_id: str = "sugg-1", is_deleted: bool = False, version: int = 1
) -> Suggestion:
    return Suggestion(
        id=suggestion_id,
        content=SuggestionContent(
            title="عنوان تست",
            problem="شرح مشکل اولیه",
            solution="راهکار اولیه",
        ),
        evaluation=CommitteeEvaluation(
            status=SuggestionStatus.APPROVED,
            scrutiny=CommitteeScrutiny.APPROVED,
            description="شرح بررسی اولیه",
        ),
        is_deleted=is_deleted,
        version=version,
    )


# --- Tests for UpdateSuggestionUseCase ---


@pytest.mark.asyncio
async def test_update_put_success_increments_version_and_activates_chunks():
    existing = create_sample_suggestion("sugg-1", version=1)
    repo = FakeSuggestionRepo([existing])
    uow = FakeUoW(repo, lock_succeeds=True)
    vector_repo = FakeVectorRepo()
    embedding_service = HybridEmbeddingService(
        FakeDenseEmbedder(), FakeSparseEmbedder()
    )

    use_case = UpdateSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        embedding_service=embedding_service,
        vector_repo=vector_repo,
    )

    dto = UpdateSuggestionDTO(
        suggestion_id="sugg-1",
        title="عنوان بروزرسانی شده",
        problem="شرح مشکل جدید",
        solution="راهکار جدید",
        status=SuggestionStatus.EXECUTED,
    )

    result = await use_case.execute_put(dto)

    assert result.suggestion_id == "sugg-1"
    assert result.version == 2
    assert result.status == "UPDATED"
    assert uow.committed is True
    assert "sugg-1" in vector_repo.activated_parent_ids
    assert len(vector_repo.superseded_calls) == 1

    saved = repo.suggestions["sugg-1"]
    assert saved.content.title == "عنوان بروزرسانی شده"
    assert saved.evaluation.status == SuggestionStatus.EXECUTED
    assert saved.version == 2
    assert saved.is_deleted is False


@pytest.mark.asyncio
async def test_update_put_restores_soft_deleted_suggestion():
    existing = create_sample_suggestion("sugg-deleted", is_deleted=True, version=3)
    repo = FakeSuggestionRepo([existing])
    uow = FakeUoW(repo, lock_succeeds=True)
    vector_repo = FakeVectorRepo()
    embedding_service = HybridEmbeddingService(
        FakeDenseEmbedder(), FakeSparseEmbedder()
    )

    use_case = UpdateSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        embedding_service=embedding_service,
        vector_repo=vector_repo,
    )

    dto = UpdateSuggestionDTO(
        suggestion_id="sugg-deleted",
        title="عنوان پیشنهاد احیا شده",
        problem="مشکل جدید احیا شده",
        solution="راهکار احیا شده",
        status=SuggestionStatus.APPROVED,
    )

    result = await use_case.execute_put(dto)

    assert result.version == 4
    saved = repo.suggestions["sugg-deleted"]
    assert saved.is_deleted is False


@pytest.mark.asyncio
async def test_update_put_non_existent_raises_404():
    repo = FakeSuggestionRepo([])
    uow = FakeUoW(repo)
    use_case = UpdateSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        embedding_service=HybridEmbeddingService(
            FakeDenseEmbedder(), FakeSparseEmbedder()
        ),
        vector_repo=FakeVectorRepo(),
    )

    dto = UpdateSuggestionDTO(
        suggestion_id="missing-id",
        title="عنوان پیشنهاد تست",
        problem="شرح مشکل سازمانی برای بررسی",
        solution="ارائه راهکار عملیاتی پیشنهادی",
        status=SuggestionStatus.PENDING,
    )

    with pytest.raises(SuggestionNotFoundError):
        await use_case.execute_put(dto)


@pytest.mark.asyncio
async def test_update_lock_contention_cleans_staged_chunks_and_raises_409():
    existing = create_sample_suggestion("sugg-locked", version=1)
    repo = FakeSuggestionRepo([existing])
    # Simulate lock acquisition failure (e.g. concurrent request holds lock)
    uow = FakeUoW(repo, lock_succeeds=False)
    vector_repo = FakeVectorRepo()

    use_case = UpdateSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        embedding_service=HybridEmbeddingService(
            FakeDenseEmbedder(), FakeSparseEmbedder()
        ),
        vector_repo=vector_repo,
    )

    dto = UpdateSuggestionDTO(
        suggestion_id="sugg-locked",
        title="تست بروزرسانی قفل",
        problem="شرح مشکل سازمانی برای بررسی",
        solution="ارائه راهکار عملیاتی پیشنهادی",
        status=SuggestionStatus.APPROVED,
    )

    with pytest.raises(SuggestionProcessingConflictError):
        await use_case.execute_put(dto)

    # Verify newly staged chunks in Qdrant were deleted to leave zero trace
    assert "chunk-sugg-locked-1" in vector_repo.deleted_chunk_ids
    assert uow.committed is False


@pytest.mark.asyncio
async def test_update_version_mismatch_raises_409():
    existing = create_sample_suggestion("sugg-race", version=1)
    repo = FakeSuggestionRepo([existing])
    uow = FakeUoW(repo, lock_succeeds=True)
    vector_repo = FakeVectorRepo()

    use_case = UpdateSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        embedding_service=HybridEmbeddingService(
            FakeDenseEmbedder(), FakeSparseEmbedder()
        ),
        vector_repo=vector_repo,
    )

    dto = UpdateSuggestionDTO(
        suggestion_id="sugg-race",
        title="تست مسابقه نسخه",
        problem="شرح مشکل سازمانی برای بررسی",
        solution="ارائه راهکار عملیاتی پیشنهادی",
        status=SuggestionStatus.APPROVED,
    )

    # Simulate another worker updating the record to version 2 while Phase 1 was running
    async def simulate_race(chunks):
        existing.version = 2

    use_case._embedding_service.embed_chunks = AsyncMock(side_effect=simulate_race)

    with pytest.raises(SuggestionProcessingConflictError):
        await use_case.execute_put(dto)

    assert "chunk-sugg-race-1" in vector_repo.deleted_chunk_ids


@pytest.mark.asyncio
async def test_update_put_phase3_retries_transient_failure_and_succeeds():
    existing = create_sample_suggestion("sugg-retry", version=1)
    repo = FakeSuggestionRepo([existing])
    uow = FakeUoW(repo, lock_succeeds=True)
    vector_repo = FakeVectorRepo()

    # Fail on first activation attempt, succeed on second attempt
    activation_attempts = 0

    async def flaky_activate(suggestion_id: str):
        nonlocal activation_attempts
        activation_attempts += 1
        if activation_attempts == 1:
            raise VectorStorageError("Temporary Qdrant connection timeout")

    vector_repo.activate_staging_chunks = AsyncMock(side_effect=flaky_activate)

    use_case = UpdateSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        embedding_service=HybridEmbeddingService(
            FakeDenseEmbedder(), FakeSparseEmbedder()
        ),
        vector_repo=vector_repo,
    )

    dto = UpdateSuggestionDTO(
        suggestion_id="sugg-retry",
        title="تست تاب‌آوری بازآزمایی",
        problem="شرح مشکل برای بررسی قابلیت بازیابی",
        solution="ارائه راهکار عملیاتی پیشنهادی",
        status=SuggestionStatus.APPROVED,
    )

    res = await use_case.execute_put(dto)

    assert res.suggestion_id == "sugg-retry"
    assert res.version == 2
    assert activation_attempts == 2
    assert len(vector_repo.superseded_calls) == 1
    assert vector_repo.superseded_calls[0][0] == "sugg-retry"


@pytest.mark.asyncio
async def test_update_patch_success_overlays_only_provided_fields():
    existing = create_sample_suggestion("sugg-patch", version=1)
    repo = FakeSuggestionRepo([existing])
    uow = FakeUoW(repo, lock_succeeds=True)
    vector_repo = FakeVectorRepo()

    use_case = UpdateSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        embedding_service=HybridEmbeddingService(
            FakeDenseEmbedder(), FakeSparseEmbedder()
        ),
        vector_repo=vector_repo,
    )

    dto = PatchSuggestionDTO(
        suggestion_id="sugg-patch",
        title="فقط عنوان عوض شده",
        # problem and solution are omitted / None
    )

    result = await use_case.execute_patch(dto)

    assert result.version == 2
    saved = repo.suggestions["sugg-patch"]
    assert saved.content.title == "فقط عنوان عوض شده"
    # problem and solution preserved
    assert saved.content.problem == "شرح مشکل اولیه"
    assert saved.content.solution == "راهکار اولیه"


@pytest.mark.asyncio
async def test_update_patch_rejects_soft_deleted_record():
    existing = create_sample_suggestion("sugg-del", is_deleted=True, version=1)
    repo = FakeSuggestionRepo([existing])
    uow = FakeUoW(repo)
    use_case = UpdateSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        embedding_service=HybridEmbeddingService(
            FakeDenseEmbedder(), FakeSparseEmbedder()
        ),
        vector_repo=FakeVectorRepo(),
    )

    dto = PatchSuggestionDTO(
        suggestion_id="sugg-del",
        title="تلاش برای پچ رکورد حذف شده",
    )

    with pytest.raises(SuggestionNotFoundError):
        await use_case.execute_patch(dto)


# --- Tests for DeleteSuggestionUseCase ---


@pytest.mark.asyncio
async def test_delete_success_soft_deletes_and_purges_vectors():
    existing = create_sample_suggestion("sugg-del-1", is_deleted=False)
    repo = FakeSuggestionRepo([existing])
    uow = FakeUoW(repo, lock_succeeds=True)
    vector_repo = FakeVectorRepo()

    use_case = DeleteSuggestionUseCase(uow=uow, vector_repo=vector_repo)
    result = await use_case.execute("sugg-del-1")

    assert result.suggestion_id == "sugg-del-1"
    assert result.status == "DELETED"
    assert existing.is_deleted is True
    assert "sugg-del-1" in vector_repo.deleted_parent_ids
    assert uow.committed is True


@pytest.mark.asyncio
async def test_delete_idempotent_for_already_deleted_suggestion():
    existing = create_sample_suggestion("sugg-del-2", is_deleted=True)
    repo = FakeSuggestionRepo([existing])
    uow = FakeUoW(repo, lock_succeeds=True)
    vector_repo = FakeVectorRepo()

    use_case = DeleteSuggestionUseCase(uow=uow, vector_repo=vector_repo)
    result = await use_case.execute("sugg-del-2")

    assert result.status == "DELETED"
    # Should not attempt second Qdrant delete since it was already deleted
    assert "sugg-del-2" not in vector_repo.deleted_parent_ids


@pytest.mark.asyncio
async def test_delete_not_found_raises_404():
    repo = FakeSuggestionRepo([])
    uow = FakeUoW(repo)
    use_case = DeleteSuggestionUseCase(uow=uow, vector_repo=FakeVectorRepo())

    with pytest.raises(SuggestionNotFoundError):
        await use_case.execute("non-existent-id")


@pytest.mark.asyncio
async def test_delete_qdrant_failure_restores_sql_record():
    existing = create_sample_suggestion("sugg-del-fail", is_deleted=False)
    repo = FakeSuggestionRepo([existing])
    uow = FakeUoW(repo, lock_succeeds=True)
    # Simulate Qdrant purge failure
    vector_repo = FakeVectorRepo(fail_delete=True)

    use_case = DeleteSuggestionUseCase(uow=uow, vector_repo=vector_repo)

    with pytest.raises(VectorStorageError):
        await use_case.execute("sugg-del-fail")

    # SQL compensation: record should be restored to is_deleted = False
    assert existing.is_deleted is False
    assert existing.version == 2
    assert len(uow.lock_keys) == 2  # Once for delete, once for compensation


@pytest.mark.asyncio
async def test_delete_qdrant_failure_compensation_lock_contention_still_raises_vector_error():
    existing = create_sample_suggestion("sugg-del-fail-2", is_deleted=False)
    repo = FakeSuggestionRepo([existing])
    attempts = 0

    class FlakyLockUoW(FakeUoW):
        async def try_acquire_advisory_lock(self, lock_key: int) -> bool:
            nonlocal attempts
            attempts += 1
            self.lock_keys.append(lock_key)
            return attempts == 1

    uow = FlakyLockUoW(repo)
    vector_repo = FakeVectorRepo(fail_delete=True)

    use_case = DeleteSuggestionUseCase(uow=uow, vector_repo=vector_repo)

    with pytest.raises(VectorStorageError):
        await use_case.execute("sugg-del-fail-2")

    assert attempts == 2


# --- Tests for BulkDeleteSuggestionsUseCase ---


@pytest.mark.asyncio
async def test_bulk_delete_all_succeed():
    s1 = create_sample_suggestion("s1")
    s2 = create_sample_suggestion("s2")
    repo = FakeSuggestionRepo([s1, s2])
    uow = FakeUoW(repo)
    vector_repo = FakeVectorRepo()

    del_use_case = DeleteSuggestionUseCase(uow=uow, vector_repo=vector_repo)
    bulk_use_case = BulkDeleteSuggestionsUseCase(delete_use_case=del_use_case)

    dto = BulkDeleteSuggestionsDTO(suggestion_ids=["s1", "s2"])
    result = await bulk_use_case.execute(dto)

    assert result.total_requested == 2
    assert result.total_deleted == 2
    assert result.total_failed == 0
    assert result.deleted_ids == ["s1", "s2"]
    assert len(result.errors) == 0


@pytest.mark.asyncio
async def test_bulk_delete_partial_success_isolates_errors_with_pointers():
    s1 = create_sample_suggestion("s1")
    # s2 does not exist
    s3 = create_sample_suggestion("s3")
    repo = FakeSuggestionRepo([s1, s3])
    uow = FakeUoW(repo)
    vector_repo = FakeVectorRepo()

    del_use_case = DeleteSuggestionUseCase(uow=uow, vector_repo=vector_repo)
    bulk_use_case = BulkDeleteSuggestionsUseCase(delete_use_case=del_use_case)

    dto = BulkDeleteSuggestionsDTO(suggestion_ids=["s1", "s2", "s3"])
    result = await bulk_use_case.execute(dto)

    assert result.total_requested == 3
    assert result.total_deleted == 2
    assert result.total_failed == 1
    assert result.deleted_ids == ["s1", "s3"]

    assert len(result.errors) == 1
    err = result.errors[0]
    assert err.suggestion_id == "s2"
    assert err.index == 1
    assert err.code == "SUGGESTION_NOT_FOUND"
    assert err.source_pointer == "/data/suggestionIds/1"
