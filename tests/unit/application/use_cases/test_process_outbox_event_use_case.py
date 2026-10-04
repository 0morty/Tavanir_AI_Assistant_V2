from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from src.application.interfaces.i_outbox_event_handler import IOutboxEventHandler
from src.application.services.outbox.outbox_handler_registry import (
    OutboxHandlerRegistry,
)
from src.application.use_cases.process_outbox_event_use_case import (
    ProcessOutboxEventUseCase,
)
from src.domain.interfaces.i_outbox_repository import IOutboxRepository

from src.application.interfaces import IUnitOfWork
from src.domain.entities import OutboxEvent


class FakeUoWWithOutbox(IUnitOfWork):
    def __init__(self, outbox_repo: IOutboxRepository):
        self._outbox = outbox_repo
        self._suggestions = AsyncMock()
        self._checkpoints = AsyncMock()
        self._skipped_suggestions = AsyncMock()
        self.committed = False
        self.rolled_back = False

    @property
    def outbox(self) -> IOutboxRepository:
        return self._outbox

    @property
    def suggestions(self) -> AsyncMock:
        return self._suggestions

    @property
    def checkpoints(self) -> AsyncMock:
        return self._checkpoints

    @property
    def skipped_suggestions(self) -> AsyncMock:
        return self._skipped_suggestions

    async def try_acquire_advisory_lock(self, lock_key: int) -> bool:
        return True

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.mark.asyncio
async def test_process_event_success_marks_completed():
    event_id = uuid4()
    event = OutboxEvent(
        id=event_id,
        resource_type="SUGGESTION",
        resource_id="sugg-1",
        event_type="SUGGESTION_INGESTED",
        version=1,
        payload={"id": "sugg-1"},
        status="PROCESSING",
    )

    mock_outbox_repo = AsyncMock(spec=IOutboxRepository)
    mock_outbox_repo.get_for_processing = AsyncMock(return_value=event)
    mock_outbox_repo.update_status = AsyncMock()

    uow = FakeUoWWithOutbox(mock_outbox_repo)

    mock_handler = AsyncMock(spec=IOutboxEventHandler)
    registry = OutboxHandlerRegistry(handlers={"SUGGESTION_INGESTED": mock_handler})

    use_case = ProcessOutboxEventUseCase(uow=uow, registry=registry)
    await use_case.execute(event_id)

    mock_handler.handle.assert_awaited_once_with(event, uow)
    mock_outbox_repo.update_status.assert_awaited_once_with(
        event_id=event_id,
        status="COMPLETED",
        error=None,
    )


@pytest.mark.asyncio
async def test_process_event_superseded_marks_superseded():
    event_id = uuid4()
    event = OutboxEvent(
        id=event_id,
        resource_type="SUGGESTION",
        resource_id="sugg-2",
        event_type="SUGGESTION_UPDATED",
        version=1,
        payload={"id": "sugg-2"},
        status="PROCESSING",
    )

    mock_outbox_repo = AsyncMock(spec=IOutboxRepository)
    mock_outbox_repo.get_for_processing = AsyncMock(return_value=event)
    mock_outbox_repo.update_status = AsyncMock()

    uow = FakeUoWWithOutbox(mock_outbox_repo)

    async def fake_handle(ev: OutboxEvent, _uow: IUnitOfWork):
        ev.status = "SUPERSEDED"

    mock_handler = AsyncMock(spec=IOutboxEventHandler)
    mock_handler.handle = AsyncMock(side_effect=fake_handle)

    registry = OutboxHandlerRegistry(handlers={"SUGGESTION_UPDATED": mock_handler})

    use_case = ProcessOutboxEventUseCase(uow=uow, registry=registry)
    await use_case.execute(event_id)

    mock_outbox_repo.update_status.assert_awaited_once_with(
        event_id=event_id,
        status="SUPERSEDED",
        error=None,
    )


@pytest.mark.asyncio
async def test_process_event_already_claimed_or_missing_returns_early():
    event_id = uuid4()
    mock_outbox_repo = AsyncMock(spec=IOutboxRepository)
    mock_outbox_repo.get_for_processing = AsyncMock(return_value=None)

    uow = FakeUoWWithOutbox(mock_outbox_repo)
    mock_handler = AsyncMock(spec=IOutboxEventHandler)
    registry = OutboxHandlerRegistry(handlers={"SUGGESTION_INGESTED": mock_handler})

    use_case = ProcessOutboxEventUseCase(uow=uow, registry=registry)
    await use_case.execute(event_id)

    mock_handler.handle.assert_not_called()
    mock_outbox_repo.update_status.assert_not_called()


@pytest.mark.asyncio
async def test_process_event_failure_increments_retry_and_resets_pending():
    event_id = uuid4()
    event = OutboxEvent(
        id=event_id,
        resource_type="SUGGESTION",
        resource_id="sugg-3",
        event_type="SUGGESTION_INGESTED",
        version=1,
        payload={"id": "sugg-3"},
        status="PROCESSING",
        retry_count=1,
    )

    mock_outbox_repo = AsyncMock(spec=IOutboxRepository)
    mock_outbox_repo.get_for_processing = AsyncMock(return_value=event)
    mock_outbox_repo.update_status = AsyncMock()

    uow = FakeUoWWithOutbox(mock_outbox_repo)

    mock_handler = AsyncMock(spec=IOutboxEventHandler)
    mock_handler.handle = AsyncMock(
        side_effect=RuntimeError("Qdrant connection timeout")
    )

    registry = OutboxHandlerRegistry(handlers={"SUGGESTION_INGESTED": mock_handler})

    use_case = ProcessOutboxEventUseCase(
        uow=uow, registry=registry, max_immediate_retries=5
    )

    with pytest.raises(RuntimeError, match="Qdrant connection timeout"):
        await use_case.execute(event_id)

    mock_outbox_repo.update_status.assert_awaited_once_with(
        event_id=event_id,
        status="PENDING",
        error="Qdrant connection timeout",
        retry_count=2,
    )


@pytest.mark.asyncio
async def test_process_event_failure_marks_failed_when_max_retries_reached():
    event_id = uuid4()
    event = OutboxEvent(
        id=event_id,
        resource_type="SUGGESTION",
        resource_id="sugg-4",
        event_type="SUGGESTION_INGESTED",
        version=1,
        payload={"id": "sugg-4"},
        status="PROCESSING",
        retry_count=4,
    )

    mock_outbox_repo = AsyncMock(spec=IOutboxRepository)
    mock_outbox_repo.get_for_processing = AsyncMock(return_value=event)
    mock_outbox_repo.update_status = AsyncMock()

    uow = FakeUoWWithOutbox(mock_outbox_repo)

    mock_handler = AsyncMock(spec=IOutboxEventHandler)
    mock_handler.handle = AsyncMock(side_effect=RuntimeError("Fatal error"))

    registry = OutboxHandlerRegistry(handlers={"SUGGESTION_INGESTED": mock_handler})

    use_case = ProcessOutboxEventUseCase(
        uow=uow, registry=registry, max_immediate_retries=5
    )

    with pytest.raises(RuntimeError, match="Fatal error"):
        await use_case.execute(event_id)

    mock_outbox_repo.update_status.assert_awaited_once_with(
        event_id=event_id,
        status="FAILED",
        error="Fatal error",
        retry_count=5,
    )
