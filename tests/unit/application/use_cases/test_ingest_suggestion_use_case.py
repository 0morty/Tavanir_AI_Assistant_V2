# pyright: reportIncompatibleMethodOverride=false
from collections.abc import Sequence
from datetime import datetime
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from src.application.use_cases.ingest_suggestion_use_case import IngestSuggestionUseCase

from src.application.dtos import CreateSuggestionDTO, IngestSuggestionResponseDTO
from src.application.interfaces import ITaskQueueService, ITextNormalizer, IUnitOfWork
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
from src.domain.enums import (
    ChunkStatus,
    CommitteeScrutiny,
    SecretariatScrutiny,
    SuggestionChunkType,
    SuggestionStatus,
)
from src.domain.exceptions import (
    InvalidSuggestionContentError,
    SuggestionAlreadyExistsError,
    SuggestionChunkingError,
    SuggestionProcessingConflictError,
)
from src.domain.interfaces import (
    IChunkingStrategy,
    IOutboxRepository,
    ISuggestionRepository,
)


class FakeSuggestionRepository(ISuggestionRepository):
    def __init__(self, existing_suggestion: Suggestion | None = None):
        self._existing = existing_suggestion
        self.saved_entities: list[Suggestion] = []

    async def get_by_id(
        self, suggestion_id: str, include_deleted: bool = False
    ) -> Suggestion | None:
        return self._existing

    async def get_by_ids(
        self, ids: Sequence[str], include_deleted: bool = False
    ) -> Sequence[Suggestion]:
        return []

    async def insert(self, entity: Suggestion) -> None:
        if self._existing and self._existing.id == entity.id:
            raise SuggestionAlreadyExistsError(
                f"Suggestion with ID '{entity.id}' already exists.",
                pointer="/data/suggestionId",
            )
        self.saved_entities.append(entity)

    async def save(self, entity: Suggestion) -> None:
        self.saved_entities.append(entity)

    async def save_batch(self, entities: Sequence[Suggestion]) -> None:
        self.saved_entities.extend(entities)

    async def delete(self, entity_id: str) -> bool:
        return True

    async def delete_batch(self, entity_ids: Sequence[str]) -> int:
        return len(entity_ids)

    async def soft_delete(self, entity_id: str) -> bool:
        return True


class FakeOutboxRepository(IOutboxRepository):
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
    def __init__(self, existing_suggestion: Suggestion | None = None):
        self._suggestions = FakeSuggestionRepository(existing_suggestion)
        self._outbox = FakeOutboxRepository()
        self._checkpoints = AsyncMock()
        self._skipped = AsyncMock()
        self.committed = False
        self.rolled_back = False

    @property
    def suggestions(self) -> FakeSuggestionRepository:
        return self._suggestions

    @property
    def outbox(self) -> FakeOutboxRepository:
        return self._outbox

    @property
    def checkpoints(self) -> AsyncMock:
        return self._checkpoints

    @property
    def skipped_suggestions(self) -> AsyncMock:
        return self._skipped

    async def try_acquire_advisory_lock(self, lock_key: int) -> bool:
        return True

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
                dense_vector=[0.1] * 10,
                sparse_vector=SparseVector(indices=[1], values=[1.0]),
                chunk_status=ChunkStatus.ACTIVE,
                version=1,
            )
        ]


@pytest.fixture
def valid_dto() -> CreateSuggestionDTO:
    return CreateSuggestionDTO(
        suggestion_id="sugg-101",
        title="عنوان پیشنهاد تست سیستم",
        problem="شرح مشکل سازمانی با جزییات کامل و دقیق جهت ذخیره سازی در پایگاه داده",
        solution="ارایه راهکار مهندسی و بهینه برای حل مشکل شبکه توزیع نیروی برق",
        status=SuggestionStatus.APPROVED,
        committee_scrutiny=CommitteeScrutiny.APPROVED,
        description="مصوب جلسه کمیته فنی",
        shamsi_date="1402/05/20",
        context_title="شرکت توزیع نیروی برق",
        committee_scrutiny_id=0,
    )


@pytest.mark.asyncio
async def test_successful_ingestion_flow(valid_dto):
    uow = FakeUoW()
    mock_task_queue = AsyncMock(spec=ITaskQueueService)
    mock_task_queue.enqueue = AsyncMock()

    use_case = IngestSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        task_queue=mock_task_queue,
    )

    response = await use_case.execute(valid_dto)

    assert isinstance(response, IngestSuggestionResponseDTO)
    assert response.suggestion_id == "sugg-101"
    assert response.status == "CREATED"
    assert response.chunks_count == 1

    # Verify atomic PostgreSQL persistence: suggestion + outbox saved
    assert len(uow.suggestions.saved_entities) == 1
    saved_entity: Suggestion = uow.suggestions.saved_entities[0]
    assert saved_entity.id == "sugg-101"
    assert saved_entity.version == 1

    assert len(uow.outbox.saved_events) == 1
    saved_event: OutboxEvent = uow.outbox.saved_events[0]
    assert saved_event.resource_type == "SUGGESTION"
    assert saved_event.resource_id == "sugg-101"
    assert saved_event.event_type == "SUGGESTION_INGESTED"
    assert saved_event.version == 1
    assert saved_event.status == "PENDING"

    # Verify UoW committed
    assert uow.committed is True

    # Verify background task enqueued (fire-and-forget)
    mock_task_queue.enqueue_task.assert_awaited_once_with(
        "process_outbox_event_task",
        event_id=str(saved_event.id),
        deduplication_id=str(saved_event.id),
    )


@pytest.mark.asyncio
async def test_ingestion_flow_with_secretariat_and_committee_evaluations():
    uow = FakeUoW()
    mock_task_queue = AsyncMock(spec=ITaskQueueService)

    use_case = IngestSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        task_queue=mock_task_queue,
    )

    dto = CreateSuggestionDTO(
        suggestion_id="sugg-103",
        title="عنوان پیشنهاد با ارزیابی دوگانه",
        problem="شرح مشکل دقیق و کامل سازمانی جهت بررسی توسط ارزیاب",
        solution="ارایه راهکار مهندسی دقیق برای حل مشکل",
        status=SuggestionStatus.PENDING,
        committee_scrutiny=CommitteeScrutiny.APPROVED,
        description="توضیحات کمیته",
        secretariat_scrutiny=SecretariatScrutiny.SEND_TO_APPROVER,
        secretariat_comment="توضیحات دبیرخانه",
    )

    response = await use_case.execute(dto)

    assert response.suggestion_id == "sugg-103"
    assert response.status == "CREATED"
    assert len(uow.suggestions.saved_entities) == 1
    assert uow.suggestions.saved_entities[0].version == 1
    assert len(uow.outbox.saved_events) == 1
    mock_task_queue.enqueue_task.assert_awaited_once()


@pytest.mark.asyncio
async def test_duplicate_suggestion_raises_conflict(valid_dto):
    existing = Suggestion(
        id="sugg-101",
        content=SuggestionContent(
            title="عنوان قدیمی",
            problem="مشکل قبلی ثبت شده",
            solution="راهکار قبلی ثبت شده",
        ),
        evaluation=CommitteeEvaluation(status=SuggestionStatus.APPROVED),
    )
    uow = FakeUoW(existing_suggestion=existing)
    mock_task_queue = AsyncMock(spec=ITaskQueueService)

    use_case = IngestSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        task_queue=mock_task_queue,
    )

    with pytest.raises(SuggestionAlreadyExistsError) as exc_info:
        await use_case.execute(valid_dto)

    assert "sugg-101" in str(exc_info.value)
    assert len(uow.suggestions.saved_entities) == 0
    assert len(uow.outbox.saved_events) == 0
    mock_task_queue.enqueue_task.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_content_raises_domain_error():
    uow = FakeUoW()
    mock_task_queue = AsyncMock(spec=ITaskQueueService)

    use_case = IngestSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        task_queue=mock_task_queue,
    )

    bad_dto = CreateSuggestionDTO(
        suggestion_id="sugg-102",
        title="عنوان معتبر و استاندارد",
        problem="ندارد",  # noise placeholder
        solution="راهکار معتبر و استاندارد سازمانی",
        status=SuggestionStatus.APPROVED,
    )

    with pytest.raises(InvalidSuggestionContentError):
        await use_case.execute(bad_dto)

    assert len(uow.suggestions.saved_entities) == 0
    assert len(uow.outbox.saved_events) == 0
    mock_task_queue.enqueue_task.assert_not_called()


@pytest.mark.asyncio
async def test_empty_chunks_raises_chunking_error(valid_dto):
    uow = FakeUoW()
    mock_task_queue = AsyncMock(spec=ITaskQueueService)

    use_case = IngestSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(return_chunks=[]),
        task_queue=mock_task_queue,
    )

    with pytest.raises(SuggestionChunkingError):
        await use_case.execute(valid_dto)

    assert len(uow.suggestions.saved_entities) == 0
    assert len(uow.outbox.saved_events) == 0
    mock_task_queue.enqueue_task.assert_not_called()


@pytest.mark.asyncio
async def test_enqueue_failure_does_not_fail_http_response(valid_dto):
    """
    If Redis/ARQ is temporarily unreachable during enqueue, the HTTP request
    still succeeds because the outbox event is safely persisted in PostgreSQL (ADR-002, FIX-ME).
    """
    uow = FakeUoW()
    mock_task_queue = AsyncMock(spec=ITaskQueueService)
    mock_task_queue.enqueue_task = AsyncMock(
        side_effect=ConnectionError("Redis connection refused")
    )

    use_case = IngestSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        task_queue=mock_task_queue,
    )

    # Must succeed despite enqueue failure
    response = await use_case.execute(valid_dto)

    assert response.suggestion_id == "sugg-101"
    assert response.status == "CREATED"
    assert len(uow.suggestions.saved_entities) == 1
    assert uow.suggestions.saved_entities[0].version == 1
    assert len(uow.outbox.saved_events) == 1
    assert uow.committed is True


@pytest.mark.asyncio
async def test_ingest_suggestion_advisory_lock_contention(valid_dto):
    uow = FakeUoW()
    uow.try_acquire_advisory_lock = AsyncMock(return_value=False)  # type: ignore
    mock_task_queue = AsyncMock(spec=ITaskQueueService)

    use_case = IngestSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        task_queue=mock_task_queue,
    )

    with pytest.raises(SuggestionProcessingConflictError) as exc_info:
        await use_case.execute(valid_dto)

    assert "currently being processed" in str(exc_info.value)
    assert exc_info.value.pointer == "/data/suggestionId"


@pytest.mark.asyncio
async def test_ingest_suggestion_concurrent_insert_duplicate(valid_dto):
    uow = FakeUoW()
    # Simulate race condition where get_by_id passed, but insert encounters duplicate key
    uow.suggestions.insert = AsyncMock(  # type: ignore
        side_effect=SuggestionAlreadyExistsError(
            f"Suggestion with ID '{valid_dto.suggestion_id}' already exists.",
            pointer="/data/suggestionId",
        )
    )
    mock_task_queue = AsyncMock(spec=ITaskQueueService)

    use_case = IngestSuggestionUseCase(
        uow=uow,
        normalizer=FakeNormalizer(),
        chunker=FakeChunker(),
        task_queue=mock_task_queue,
    )

    with pytest.raises(SuggestionAlreadyExistsError) as exc_info:
        await use_case.execute(valid_dto)

    assert f"Suggestion with ID '{valid_dto.suggestion_id}' already exists." in str(exc_info.value)

