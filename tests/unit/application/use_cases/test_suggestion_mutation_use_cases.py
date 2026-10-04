from collections.abc import Sequence
from datetime import datetime
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from src.application.dtos import (
    BulkDeleteSuggestionsDTO,
    PatchSuggestionDTO,
    UpdateSuggestionDTO,
)
from src.application.interfaces import ITaskQueueService, ITextNormalizer, IUnitOfWork
from src.application.use_cases import (
    BulkDeleteSuggestionsUseCase,
    DeleteSuggestionUseCase,
    UpdateSuggestionUseCase,
)
from src.domain.entities import (
    Chunk,
    CommitteeEvaluation,
    OutboxEvent,
    ShamsiDate,
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
    SuggestionAlreadyExistsError,
    SuggestionNotFoundError,
    SuggestionProcessingConflictError,
)
from src.domain.interfaces import (
    IOutboxRepository,
    ISuggestionChunker,
    ISuggestionRepository,
)


class FakeSuggestionRepo(ISuggestionRepository):
    def __init__(self, initial_suggestions: list[Suggestion] | None = None):
        self.suggestions: dict[str, Suggestion] = {
            s.id: s for s in (initial_suggestions or [])
        }
        self.saved_entities: list[Suggestion] = []
        self.soft_delete_called = False

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

    async def insert(self, suggestion: Suggestion) -> None:
        if suggestion.id in self.suggestions:
            raise SuggestionAlreadyExistsError(
                f"Suggestion with ID '{suggestion.id}' already exists.",
                pointer="/data/suggestionId",
            )
        self.suggestions[suggestion.id] = suggestion
        self.saved_entities.append(suggestion)

    async def save(self, suggestion: Suggestion) -> None:
        self.suggestions[suggestion.id] = suggestion
        self.saved_entities.append(suggestion)

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
            s.version += 1
            self.soft_delete_called = True


class FakeOutboxRepo(IOutboxRepository):
    def __init__(self):
        self.saved_events: list[OutboxEvent] = []

    async def append(self, event: OutboxEvent) -> None:
        self.saved_events.append(event)

    async def get_by_id(self, event_id: UUID) -> OutboxEvent | None:
        for ev in self.saved_events:
            if ev.id == event_id:
                return ev
        return None

    async def get_for_processing(self, event_id: UUID) -> OutboxEvent | None:
        return None

    async def update_status(
        self,
        event_id: UUID,
        status: str,
        error: str | None = None,
        retry_count: int | None = None,
    ) -> None:
        pass

    async def fetch_stale_events(
        self, stuck_before: datetime, limit: int = 100
    ) -> list[OutboxEvent]:
        return []

    async def fetch_pending_events(
        self, created_before: datetime, limit: int = 100
    ) -> list[OutboxEvent]:
        return []

    async def fetch_failed_for_retry(
        self, created_after: datetime, max_retries: int = 20, limit: int = 100
    ) -> list[OutboxEvent]:
        return []

    async def prune_completed(self, before: datetime) -> int:
        return 0


class FakeUoW(IUnitOfWork):
    def __init__(self, repo: FakeSuggestionRepo, lock_succeeds: bool = True):
        self._repo = repo
        self._outbox = FakeOutboxRepo()
        self._lock_succeeds = lock_succeeds
        self.lock_keys: list[int] = []
        self.committed = False
        self.rolled_back = False

    @property
    def suggestions(self) -> FakeSuggestionRepo:
        return self._repo

    @property
    def outbox(self) -> FakeOutboxRepo:
        return self._outbox

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

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            await self.rollback()
        else:
            await self.commit()


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
                version=document.version,
            )
        ]


def create_sample_suggestion(
    suggestion_id: str, is_deleted: bool = False, version: int = 1
) -> Suggestion:
    return Suggestion(
        id=suggestion_id,
        content=SuggestionContent(
            title="عنوان تستی معتبر",
            problem="شرح مشکل معتبر جهت تست",
            solution="ارایه راهکار مهندسی دقیق",
        ),
        evaluation=CommitteeEvaluation(
            status=SuggestionStatus.APPROVED,
            scrutiny=CommitteeScrutiny.APPROVED,
            description="تایید در جلسه",
        ),
        date=ShamsiDate("1402/01/01"),
        context_title="شرکت توزیع",
        is_deleted=is_deleted,
        version=version,
    )


# region PUT Tests
@pytest.mark.asyncio
async def test_update_put_success_increments_version_and_saves_outbox():
    existing = create_sample_suggestion("sugg-put-1", version=1)
    repo = FakeSuggestionRepo([existing])
    uow = FakeUoW(repo, lock_succeeds=True)
    mock_task_queue = AsyncMock(spec=ITaskQueueService)

    use_case = UpdateSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        task_queue=mock_task_queue,
    )

    dto = UpdateSuggestionDTO(
        suggestion_id="sugg-put-1",
        title="عنوان به روز رسانی شده",
        problem="شرح مشکل به روز شده",
        solution="راهکار به روز شده",
        status=SuggestionStatus.EXECUTED,
    )

    response = await use_case.execute_put(dto)

    assert response.suggestion_id == "sugg-put-1"
    assert response.status == "UPDATED"
    assert response.version == 2

    # Verify SQL record saved with version 2
    assert len(uow.suggestions.saved_entities) == 1
    updated_sql = repo.suggestions["sugg-put-1"]
    assert updated_sql.version == 2
    assert updated_sql.content.title == "عنوان به روز رسانی شده"
    assert updated_sql.evaluation.status == SuggestionStatus.EXECUTED

    # Verify Outbox event saved with version 2
    assert len(uow.outbox.saved_events) == 1
    saved_event = uow.outbox.saved_events[0]
    assert saved_event.resource_type == "SUGGESTION"
    assert saved_event.resource_id == "sugg-put-1"
    assert saved_event.event_type == "SUGGESTION_UPDATED"
    assert saved_event.version == 2
    assert saved_event.status == "PENDING"

    # Verify atomic commit
    assert uow.committed is True

    # Verify task enqueued
    mock_task_queue.enqueue_task.assert_awaited_once_with(
        "process_outbox_event_task",
        event_id=str(saved_event.id),
        deduplication_id=str(saved_event.id),
    )


@pytest.mark.asyncio
async def test_update_put_restores_soft_deleted_suggestion():
    existing = create_sample_suggestion("sugg-put-del", is_deleted=True, version=2)
    repo = FakeSuggestionRepo([existing])
    uow = FakeUoW(repo, lock_succeeds=True)
    mock_task_queue = AsyncMock(spec=ITaskQueueService)

    use_case = UpdateSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        task_queue=mock_task_queue,
    )

    dto = UpdateSuggestionDTO(
        suggestion_id="sugg-put-del",
        title="عنوان پیشنهاد احیا شده",
        problem="شرح مشکل",
        solution="راهکار",
        status=SuggestionStatus.PENDING,
    )

    response = await use_case.execute_put(dto)

    assert response.version == 3
    updated_sql = repo.suggestions["sugg-put-del"]
    assert updated_sql.is_deleted is False
    assert updated_sql.version == 3
    assert len(uow.outbox.saved_events) == 1
    assert uow.outbox.saved_events[0].version == 3


@pytest.mark.asyncio
async def test_update_put_non_existent_raises_404():
    repo = FakeSuggestionRepo([])
    uow = FakeUoW(repo)
    mock_task_queue = AsyncMock(spec=ITaskQueueService)

    use_case = UpdateSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        task_queue=mock_task_queue,
    )

    dto = UpdateSuggestionDTO(
        suggestion_id="sugg-missing",
        title="عنوان",
        problem="مشکل",
        solution="راهکار",
        status=SuggestionStatus.APPROVED,
    )

    with pytest.raises(SuggestionNotFoundError):
        await use_case.execute_put(dto)


@pytest.mark.asyncio
async def test_update_lock_contention_raises_409():
    existing = create_sample_suggestion("sugg-lock")
    repo = FakeSuggestionRepo([existing])
    uow = FakeUoW(repo, lock_succeeds=False)
    mock_task_queue = AsyncMock(spec=ITaskQueueService)

    use_case = UpdateSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        task_queue=mock_task_queue,
    )

    dto = UpdateSuggestionDTO(
        suggestion_id="sugg-lock",
        title="عنوان",
        problem="مشکل",
        solution="راهکار",
        status=SuggestionStatus.APPROVED,
    )

    with pytest.raises(SuggestionProcessingConflictError):
        await use_case.execute_put(dto)


# endregion


# region PATCH Tests
@pytest.mark.asyncio
async def test_update_patch_success_overlays_only_provided_fields():
    existing = create_sample_suggestion("sugg-patch", version=1)
    repo = FakeSuggestionRepo([existing])
    uow = FakeUoW(repo, lock_succeeds=True)
    mock_task_queue = AsyncMock(spec=ITaskQueueService)

    use_case = UpdateSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        task_queue=mock_task_queue,
    )

    dto = PatchSuggestionDTO(
        suggestion_id="sugg-patch",
        title="عنوان به روز شده فقط",
    )

    response = await use_case.execute_patch(dto)

    assert response.status == "UPDATED"
    assert response.version == 2
    updated = repo.suggestions["sugg-patch"]
    assert updated.content.title == "عنوان به روز شده فقط"
    assert updated.content.problem == "شرح مشکل معتبر جهت تست"  # Preserved
    assert len(uow.outbox.saved_events) == 1
    assert uow.outbox.saved_events[0].version == 2


@pytest.mark.asyncio
async def test_update_patch_rejects_soft_deleted_record():
    existing = create_sample_suggestion("sugg-del", is_deleted=True, version=1)
    repo = FakeSuggestionRepo([existing])
    uow = FakeUoW(repo)
    mock_task_queue = AsyncMock(spec=ITaskQueueService)

    use_case = UpdateSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        task_queue=mock_task_queue,
    )

    dto = PatchSuggestionDTO(
        suggestion_id="sugg-del",
        title="عنوان جدید",
    )

    with pytest.raises(SuggestionNotFoundError):
        await use_case.execute_patch(dto)


# endregion


# region DELETE Tests
@pytest.mark.asyncio
async def test_delete_success_soft_deletes_and_saves_outbox():
    existing = create_sample_suggestion("sugg-del-1", is_deleted=False, version=1)
    repo = FakeSuggestionRepo([existing])
    uow = FakeUoW(repo, lock_succeeds=True)
    mock_task_queue = AsyncMock(spec=ITaskQueueService)

    use_case = DeleteSuggestionUseCase(
        uow=uow,
        task_queue=mock_task_queue,
    )

    response = await use_case.execute("sugg-del-1")

    assert response.suggestion_id == "sugg-del-1"
    assert response.status == "DELETED"
    assert repo.suggestions["sugg-del-1"].is_deleted is True
    assert repo.suggestions["sugg-del-1"].version == 2

    # Verify Outbox event created
    assert len(uow.outbox.saved_events) == 1
    event = uow.outbox.saved_events[0]
    assert event.resource_id == "sugg-del-1"
    assert event.event_type == "SUGGESTION_DELETED"
    assert event.version == 2

    # Verify task enqueued
    mock_task_queue.enqueue_task.assert_awaited_once_with(
        "process_outbox_event_task",
        event_id=str(event.id),
        deduplication_id=str(event.id),
    )


@pytest.mark.asyncio
async def test_delete_idempotent_for_already_deleted_suggestion():
    existing = create_sample_suggestion("sugg-del-2", is_deleted=True, version=2)
    repo = FakeSuggestionRepo([existing])
    uow = FakeUoW(repo, lock_succeeds=True)
    mock_task_queue = AsyncMock(spec=ITaskQueueService)

    use_case = DeleteSuggestionUseCase(
        uow=uow,
        task_queue=mock_task_queue,
    )

    response = await use_case.execute("sugg-del-2")

    assert response.status == "DELETED"
    # Idempotent: should NOT re-enqueue or create extra outbox event
    assert len(uow.outbox.saved_events) == 0
    mock_task_queue.enqueue_task.assert_not_called()


@pytest.mark.asyncio
async def test_delete_not_found_raises_404():
    repo = FakeSuggestionRepo([])
    uow = FakeUoW(repo)
    mock_task_queue = AsyncMock(spec=ITaskQueueService)

    use_case = DeleteSuggestionUseCase(
        uow=uow,
        task_queue=mock_task_queue,
    )

    with pytest.raises(SuggestionNotFoundError):
        await use_case.execute("sugg-nonexistent")


# endregion


# region BULK DELETE Tests
@pytest.mark.asyncio
async def test_bulk_delete_all_succeed():
    s1 = create_sample_suggestion("s1")
    s2 = create_sample_suggestion("s2")
    repo = FakeSuggestionRepo([s1, s2])
    uow = FakeUoW(repo)
    mock_task_queue = AsyncMock(spec=ITaskQueueService)

    delete_use_case = DeleteSuggestionUseCase(uow=uow, task_queue=mock_task_queue)
    bulk_use_case = BulkDeleteSuggestionsUseCase(delete_use_case=delete_use_case)

    dto = BulkDeleteSuggestionsDTO(suggestion_ids=["s1", "s2"])
    response = await bulk_use_case.execute(dto)

    assert response.total_deleted == 2
    assert response.total_failed == 0
    assert len(response.errors) == 0
    assert repo.suggestions["s1"].is_deleted is True
    assert repo.suggestions["s2"].is_deleted is True


@pytest.mark.asyncio
async def test_bulk_delete_partial_success_isolates_errors_with_pointers():
    s1 = create_sample_suggestion("s1")
    s3 = create_sample_suggestion("s3")
    repo = FakeSuggestionRepo([s1, s3])
    uow = FakeUoW(repo)
    mock_task_queue = AsyncMock(spec=ITaskQueueService)

    delete_use_case = DeleteSuggestionUseCase(uow=uow, task_queue=mock_task_queue)
    bulk_use_case = BulkDeleteSuggestionsUseCase(delete_use_case=delete_use_case)

    dto = BulkDeleteSuggestionsDTO(suggestion_ids=["s1", "s2_missing", "s3"])
    response = await bulk_use_case.execute(dto)

    assert response.total_deleted == 2
    assert response.total_failed == 1
    assert len(response.errors) == 1
    failure = response.errors[0]
    assert failure.suggestion_id == "s2_missing"
    assert failure.code == "SUGGESTION_NOT_FOUND"
    assert failure.source_pointer == "/data/suggestionIds/1"


# endregion
