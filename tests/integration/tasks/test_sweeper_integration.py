from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from src.containers import Container
from src.infrastructure.db.repositories.sql.outbox_repository import SqlOutboxRepository

from src.domain.entities import OutboxEvent
from src.infrastructure.tasks.cron_tasks import sweep_stale_outbox_events_task

pytestmark = [
    pytest.mark.db,
    pytest.mark.asyncio,
    pytest.mark.usefixtures("postgres_test_database"),
]


async def test_sweeper_recovers_stuck_processing_events(session_factory):
    """
    Validates FIX-ME requirement:
    Seeds stuck PROCESSING event in PostgreSQL test DB.
    Sweeper resets status to PENDING and re-enqueues for processing.
    """
    id_stuck = uuid4()
    now = datetime.now(timezone.utc)
    old_time = now - timedelta(minutes=10)

    async with session_factory() as session:
        repo = SqlOutboxRepository(session)
        await repo.append(
            OutboxEvent(
                id=id_stuck,
                resource_type="SUGGESTION",
                resource_id="stuck-sugg-1",
                event_type="SUGGESTION_INGESTED",
                version=1,
                payload={"suggestion_id": "stuck-sugg-1"},
                status="PROCESSING",
                retry_count=1,
                locked_at=old_time,
                created_at=old_time,
            )
        )
        await session.commit()

    # Setup container with mocked task queue and test session_factory UoW
    from dependency_injector import providers
    from src.infrastructure.db.unit_of_work import SqlUnitOfWork

    container = Container()
    mock_task_queue = AsyncMock()
    container.task_queue_service.override(mock_task_queue)
    container.unit_of_work.override(
        providers.Factory(SqlUnitOfWork, session_factory=session_factory)
    )

    ctx = {"di_container": container}
    await sweep_stale_outbox_events_task(ctx)

    # Verify task queue enqueue was called with stuck event
    enqueued_event_ids = [
        call.kwargs.get("event_id")
        for call in mock_task_queue.enqueue_task.call_args_list
    ]
    assert str(id_stuck) in enqueued_event_ids

    # Verify event status in DB was updated from PROCESSING to PENDING
    async with session_factory() as session:
        repo = SqlOutboxRepository(session)
        recovered = await repo.get_by_id(id_stuck)
        assert recovered is not None
        assert recovered.status == "PENDING"
