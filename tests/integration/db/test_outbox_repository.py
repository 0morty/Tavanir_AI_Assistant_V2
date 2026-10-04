from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text
from src.infrastructure.db.repositories.sql.outbox_repository import SqlOutboxRepository

from src.domain.entities import OutboxEvent

pytestmark = [
    pytest.mark.db,
    pytest.mark.asyncio,
    pytest.mark.usefixtures("postgres_test_database"),
]


async def test_outbox_event_persistence_and_indexes(session_factory):
    async with session_factory() as session:
        repo = SqlOutboxRepository(session)
        event_id = uuid4()
        event = OutboxEvent(
            id=event_id,
            resource_type="SUGGESTION",
            resource_id="test-sugg-100",
            event_type="SUGGESTION_INGESTED",
            version=1,
            payload={
                "suggestion_id": "test-sugg-100",
                "version": 1,
                "title": "تست اوتباکس",
            },
            status="PENDING",
            retry_count=0,
            last_error=None,
            created_at=datetime.now(timezone.utc),
        )

        await repo.append(event)
        await session.commit()

    async with session_factory() as session:
        repo = SqlOutboxRepository(session)
        fetched = await repo.get_by_id(event_id)
        assert fetched is not None
        assert fetched.id == event_id
        assert fetched.resource_type == "SUGGESTION"
        assert fetched.resource_id == "test-sugg-100"
        assert fetched.event_type == "SUGGESTION_INGESTED"
        assert fetched.version == 1
        assert fetched.payload["title"] == "تست اوتباکس"
        assert fetched.status == "PENDING"


async def test_get_for_processing_skips_locked_rows(test_database_config):
    """
    Verifies FOR UPDATE SKIP LOCKED concurrency semantics using two separate connections.
    Worker 1 claims event id1 with lock.
    Worker 2 attempts to claim id1: skips and returns None.
    Worker 2 claims id2: succeeds.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from src.infrastructure.db import create_db_engine

    engine = create_db_engine(test_database_config.postgres_url)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )

    id1 = uuid4()
    id2 = uuid4()

    try:
        async with factory() as setup_session:
            repo = SqlOutboxRepository(setup_session)
            await repo.append(
                OutboxEvent(
                    id=id1,
                    resource_type="SUGGESTION",
                    resource_id="sugg-lock-1",
                    event_type="SUGGESTION_INGESTED",
                    version=1,
                    payload={"id": "sugg-lock-1"},
                    status="PENDING",
                )
            )
            await repo.append(
                OutboxEvent(
                    id=id2,
                    resource_type="SUGGESTION",
                    resource_id="sugg-lock-2",
                    event_type="SUGGESTION_INGESTED",
                    version=1,
                    payload={"id": "sugg-lock-2"},
                    status="PENDING",
                )
            )
            await setup_session.commit()

        # Connection 1: claims id1 with lock, hold transaction open
        async with factory() as session1:
            repo1 = SqlOutboxRepository(session1)
            event1 = await repo1.get_for_processing(id1)
            assert event1 is not None
            assert event1.id == id1
            assert event1.status == "PROCESSING"

            # Connection 2: attempting to claim id1 should skip locked row and return None
            async with factory() as session2:
                repo2 = SqlOutboxRepository(session2)
                event1_contended = await repo2.get_for_processing(id1)
                assert event1_contended is None

                # Connection 2 claiming id2 succeeds
                event2 = await repo2.get_for_processing(id2)
                assert event2 is not None
                assert event2.id == id2
                await session2.commit()

            await session1.commit()
    finally:
        async with factory() as cleanup_session:
            await cleanup_session.execute(
                text("DELETE FROM outbox_events WHERE id IN (:id1, :id2)"),
                {"id1": id1, "id2": id2},
            )
            await cleanup_session.commit()
        await engine.dispose()


async def test_fetch_stale_events_queries_by_index(session_factory):
    id_stale = uuid4()
    id_fresh = uuid4()
    now = datetime.now(timezone.utc)
    old_time = now - timedelta(minutes=10)

    async with session_factory() as session:
        repo = SqlOutboxRepository(session)
        # Stuck event (locked 10m ago in PROCESSING status)
        await repo.append(
            OutboxEvent(
                id=id_stale,
                resource_type="SUGGESTION",
                resource_id="stuck-sugg",
                event_type="SUGGESTION_UPDATED",
                version=2,
                payload={},
                status="PROCESSING",
                retry_count=1,
                locked_at=old_time,
                created_at=old_time,
            )
        )
        # Fresh event (locked just now)
        await repo.append(
            OutboxEvent(
                id=id_fresh,
                resource_type="SUGGESTION",
                resource_id="fresh-sugg",
                event_type="SUGGESTION_UPDATED",
                version=2,
                payload={},
                status="PROCESSING",
                retry_count=1,
                locked_at=now,
                created_at=now,
            )
        )
        await session.commit()

    async with session_factory() as session:
        repo = SqlOutboxRepository(session)
        stale_threshold = now - timedelta(minutes=5)
        stale_events = await repo.fetch_stale_events(stuck_before=stale_threshold)
        stale_ids = [e.id for e in stale_events]
        assert id_stale in stale_ids
        assert id_fresh not in stale_ids


async def test_update_status_and_prune(session_factory):
    event_id = uuid4()

    async with session_factory() as session:
        repo = SqlOutboxRepository(session)
        await repo.append(
            OutboxEvent(
                id=event_id,
                resource_type="SUGGESTION",
                resource_id="prune-sugg",
                event_type="SUGGESTION_DELETED",
                version=3,
                payload={},
                status="PROCESSING",
            )
        )
        await session.commit()

    async with session_factory() as session:
        repo = SqlOutboxRepository(session)
        await repo.update_status(
            event_id=event_id,
            status="COMPLETED",
        )
        await session.commit()

    async with session_factory() as session:
        repo = SqlOutboxRepository(session)
        event = await repo.get_by_id(event_id)
        assert event is not None
        assert event.status == "COMPLETED"
        assert event.processed_at is not None

        # Test prune
        future_cutoff = datetime.now(timezone.utc) + timedelta(minutes=1)
        pruned_count = await repo.prune_completed(before=future_cutoff)
        assert pruned_count >= 1

        remaining = await repo.get_by_id(event_id)
        assert remaining is None
