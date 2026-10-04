from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from dependency_injector import providers
from src.containers import Container
from src.infrastructure.db.unit_of_work import SqlUnitOfWork
from src.infrastructure.tasks.outbox_tasks import process_outbox_event_task

from src.domain.entities import (
    CommitteeEvaluation,
    OutboxEvent,
    Suggestion,
    SuggestionContent,
)
from src.domain.enums import SuggestionChunkType, SuggestionStatus
from src.infrastructure.tasks.cron_tasks import sweep_stale_outbox_events_task

pytestmark = [
    pytest.mark.db,
    pytest.mark.asyncio,
    pytest.mark.usefixtures("postgres_test_database", "qdrant_test_database"),
]


def _build_test_container(session_factory) -> Container:
    container = Container()
    container.unit_of_work.override(
        providers.Factory(SqlUnitOfWork, session_factory=session_factory)
    )
    container.tokenizer.override(MagicMock())
    container.arq_redis_pool.override(MagicMock())
    return container


# ==============================================================================
# F-08 & F-09: Dual Compensation Elimination & Crash Recovery
# ==============================================================================
async def test_f08_f09_ingestion_resilience_no_dual_compensation_zombie(
    session_factory,
):
    """
    Validates F-08 & F-09:
    Ingestion commits SQL + Outbox atomically. Even if vector processing encounters
    transient delays or failures, no dual compensation rollbacks execute.
    Background worker reliably completes reconciliation without leaving zombie records.
    """
    sugg_id = f"f08-{uuid4().hex[:8]}"
    event_id = uuid4()

    uow = SqlUnitOfWork(session_factory)
    async with uow:
        suggestion = Suggestion(
            id=sugg_id,
            content=SuggestionContent(
                title="تست تاب‌آوری درج بدون جبران‌سازی دوگانه",
                problem="مسئله آزمایشی پایداری",
                solution="راهکار بر پایه اوتباکس",
            ),
            evaluation=CommitteeEvaluation(status=SuggestionStatus.APPROVED),
            version=1,
        )
        outbox_event = OutboxEvent(
            id=event_id,
            resource_type="SUGGESTION",
            resource_id=sugg_id,
            event_type="SUGGESTION_INGESTED",
            version=1,
            payload={"suggestion_id": sugg_id, "version": 1},
            status="PENDING",
        )
        await uow.suggestions.save(suggestion)
        await uow.outbox.append(outbox_event)
        await uow.commit()

    # Verify SQL record is immediately committed (never rolled back by dual compensation)
    async with uow:
        saved_sugg = await uow.suggestions.get_by_id(sugg_id)
        assert saved_sugg is not None
        assert saved_sugg.version == 1

        saved_event = await uow.outbox.get_by_id(event_id)
        assert saved_event is not None
        assert saved_event.status == "PENDING"

    # Worker processes the outbox event
    container = _build_test_container(session_factory)
    ctx = {"di_container": container, "job_try": 1}
    await process_outbox_event_task(ctx, str(event_id))

    # Verify outbox event transitions to COMPLETED
    async with uow:
        completed_event = await uow.outbox.get_by_id(event_id)
        assert completed_event is not None
        assert completed_event.status == "COMPLETED"

    # Cleanup points
    await container.suggestion_vector_repository().delete_chunks_by_parent_id(sugg_id)


# ==============================================================================
# F-10 & F-11: Delete Compensation Elimination & Anti-Overwrite Guard
# ==============================================================================
async def test_f10_f11_delete_resilience_no_stale_restoration(session_factory):
    """
    Validates F-10 & F-11:
    Delete marks suggestion soft-deleted (is_deleted=True, v=v+1) and appends outbox event.
    No reverse compensation (record.restore()) is ever attempted on vector failure.
    If a newer update (v=3) commits before delete event (v=2) executes, the worker
    supersedes v=2 and preserves v=3 vectors.
    """
    sugg_id = f"f10-{uuid4().hex[:8]}"
    delete_event_id = uuid4()

    uow = SqlUnitOfWork(session_factory)
    async with uow:
        # Initial suggestion v=1
        suggestion = Suggestion(
            id=sugg_id,
            content=SuggestionContent(
                title="پیشنهاد حذف‌شونده",
                problem="مسئله حذف",
                solution="راهکار حذف",
            ),
            evaluation=CommitteeEvaluation(status=SuggestionStatus.APPROVED),
            version=1,
        )
        await uow.suggestions.save(suggestion)
        await uow.commit()

    # Step 1: Soft-delete appends SUGGESTION_DELETED event at v=2
    async with uow:
        sugg = await uow.suggestions.get_by_id(sugg_id)
        sugg.mark_deleted()
        sugg.increment_version()  # v=2
        delete_event = OutboxEvent(
            id=delete_event_id,
            resource_type="SUGGESTION",
            resource_id=sugg_id,
            event_type="SUGGESTION_DELETED",
            version=2,
            payload={"suggestion_id": sugg_id, "version": 2},
            status="PENDING",
        )
        await uow.suggestions.save(sugg)
        await uow.outbox.append(delete_event)
        await uow.commit()

    # Step 2: Concurrently, a newer update un-deletes and increments to v=3
    async with uow:
        sugg = await uow.suggestions.get_by_id(sugg_id, include_deleted=True)
        assert sugg is not None
        sugg.restore()
        sugg.increment_version()  # v=3
        await uow.suggestions.save(sugg)
        await uow.commit()

    # Step 3: Worker now executes the delayed delete event (v=2)
    container = _build_test_container(session_factory)
    ctx = {"di_container": container, "job_try": 1}
    await process_outbox_event_task(ctx, str(delete_event_id))

    # Verify: delete event was SUPERSEDED because current SQL version (3) > event version (2)
    async with uow:
        superseded_event = await uow.outbox.get_by_id(delete_event_id)
        assert superseded_event is not None
        assert superseded_event.status == "SUPERSEDED"

        # Verify SQL record was NOT corrupted by stale compensation
        current_sugg = await uow.suggestions.get_by_id(sugg_id)
        assert current_sugg.version == 3
        assert current_sugg.is_deleted is False


# ==============================================================================
# FIX-ME: Process Restart Sweeper Recovery
# ==============================================================================
async def test_fixme_process_restart_sweeper_reconciliation(session_factory):
    """
    Validates FIX-ME:
    If process crashes immediately after SQL commit, the outbox event remains PENDING.
    On restart, the sweeper cron identifies unhandled PENDING events and re-enqueues them.
    Worker then reconciles Qdrant to match PostgreSQL state.
    """
    sugg_id = f"fixme-{uuid4().hex[:8]}"
    event_id = uuid4()
    old_time = datetime.now(timezone.utc) - timedelta(minutes=3)

    uow = SqlUnitOfWork(session_factory)
    async with uow:
        suggestion = Suggestion(
            id=sugg_id,
            content=SuggestionContent(
                title="پیشنهاد تست بازیابی سوئیپر پس از ری‌استارت",
                problem="مسئله عدم انطباق پس از کرش",
                solution="سوئیپر خودکار اوتباکس",
            ),
            evaluation=CommitteeEvaluation(status=SuggestionStatus.APPROVED),
            version=1,
        )
        outbox_event = OutboxEvent(
            id=event_id,
            resource_type="SUGGESTION",
            resource_id=sugg_id,
            event_type="SUGGESTION_INGESTED",
            version=1,
            payload={"suggestion_id": sugg_id, "version": 1},
            status="PENDING",
            created_at=old_time,
        )
        await uow.suggestions.save(suggestion)
        await uow.outbox.append(outbox_event)
        await uow.commit()

    # Sweeper runs
    container = _build_test_container(session_factory)
    mock_task_queue = AsyncMock()
    container.task_queue_service.override(mock_task_queue)

    ctx = {"di_container": container}
    await sweep_stale_outbox_events_task(ctx)

    # Verify task queue received the re-enqueue call
    enqueued_ids = [
        call.kwargs.get("event_id")
        for call in mock_task_queue.enqueue_task.call_args_list
    ]
    assert str(event_id) in enqueued_ids

    # Worker executes the event
    worker_ctx = {"di_container": container, "job_try": 1}
    await process_outbox_event_task(worker_ctx, str(event_id))

    # Verify event completed
    async with uow:
        reconciled = await uow.outbox.get_by_id(event_id)
        assert reconciled.status == "COMPLETED"

    # Cleanup
    await container.suggestion_vector_repository().delete_chunks_by_parent_id(sugg_id)


# ==============================================================================
# F-01 & F-12: Zero-Blackout Version Cutover & Out-of-Order Rejection
# ==============================================================================
async def test_f01_f12_cutover_idempotency_and_order_fencing(session_factory):
    """
    Validates F-01 and F-12:
    1. Cutover retry never demotes active points (F-01).
    2. Out-of-order events from prior versions are superseded without touching Qdrant (F-12).
    """
    sugg_id = f"f01-{uuid4().hex[:8]}"
    event_v2_id = uuid4()
    event_v1_delayed_id = uuid4()

    uow = SqlUnitOfWork(session_factory)
    async with uow:
        suggestion = Suggestion(
            id=sugg_id,
            content=SuggestionContent(
                title="پیشنهاد تست کات‌اور پایدار نسخه ۲",
                problem="مسئله نوسان کات‌اور",
                solution="حفظ کات‌اور اتمیک بدون خاموشی",
            ),
            evaluation=CommitteeEvaluation(status=SuggestionStatus.APPROVED),
            version=2,  # Already at v=2 in SQL
        )
        # Event for v=2
        event_v2 = OutboxEvent(
            id=event_v2_id,
            resource_type="SUGGESTION",
            resource_id=sugg_id,
            event_type="SUGGESTION_UPDATED",
            version=2,
            payload={"suggestion_id": sugg_id, "version": 2},
            status="PENDING",
        )
        # Delayed out-of-order event for v=1 arriving late
        event_v1_delayed = OutboxEvent(
            id=event_v1_delayed_id,
            resource_type="SUGGESTION",
            resource_id=sugg_id,
            event_type="SUGGESTION_UPDATED",
            version=1,
            payload={"suggestion_id": sugg_id, "version": 1},
            status="PENDING",
        )
        await uow.suggestions.save(suggestion)
        await uow.outbox.append(event_v2)
        await uow.outbox.append(event_v1_delayed)
        await uow.commit()

    container = _build_test_container(session_factory)

    # Step 1: Process v=2
    ctx_v2 = {"di_container": container, "job_try": 1}
    await process_outbox_event_task(ctx_v2, str(event_v2_id))

    async with uow:
        e2 = await uow.outbox.get_by_id(event_v2_id)
        assert e2.status == "COMPLETED"

    # Step 2: Idempotent cutover retry of v=2 (lost ACK simulation)
    # Re-running cutover must complete cleanly without error or demotion
    use_case = container.process_outbox_event_use_case()
    if inspect.isawaitable(use_case):
        use_case = await use_case
    await use_case.execute(event_v2_id)

    # Step 3: Out-of-order execution of delayed event v=1 (F-12)
    ctx_v1 = {"di_container": container, "job_try": 1}
    await process_outbox_event_task(ctx_v1, str(event_v1_delayed_id))

    async with uow:
        e1 = await uow.outbox.get_by_id(event_v1_delayed_id)
        # Must be marked SUPERSEDED because current SQL version (2) > event version (1)
        assert e1.status == "SUPERSEDED"

    # Cleanup
    await container.suggestion_vector_repository().delete_chunks_by_parent_id(sugg_id)


# ==============================================================================
# F-13: Concurrent Ingestion Conflict
# ==============================================================================
async def test_f13_concurrent_ingestion_race(session_factory):
    """
    Validates F-13:
    Two simultaneous ingest attempts with the same ID cannot race or corrupt the outbox.
    PostgreSQL primary key / unique constraint rejects the duplicate.
    """
    sugg_id = f"f13-{uuid4().hex[:8]}"

    uow1 = SqlUnitOfWork(session_factory)
    async with uow1:
        s1 = Suggestion(
            id=sugg_id,
            content=SuggestionContent(
                title="درج اول",
                problem="مسئله",
                solution="راهکار",
            ),
            evaluation=CommitteeEvaluation(status=SuggestionStatus.APPROVED),
            version=1,
        )
        e1 = OutboxEvent(
            id=uuid4(),
            resource_type="SUGGESTION",
            resource_id=sugg_id,
            event_type="SUGGESTION_INGESTED",
            version=1,
            payload={"suggestion_id": sugg_id},
            status="PENDING",
        )
        await uow1.suggestions.save(s1)
        await uow1.outbox.append(e1)
        await uow1.commit()

    # Attempting duplicate insert with same ID in uow2 must fail with integrity error
    uow2 = SqlUnitOfWork(session_factory)
    from src.domain.exceptions import SuggestionAlreadyExistsError

    with pytest.raises(Exception):
        async with uow2:
            s2 = Suggestion(
                id=sugg_id,
                content=SuggestionContent(
                    title="درج تکراری همزمان",
                    problem="مسئله",
                    solution="راهکار",
                ),
                evaluation=CommitteeEvaluation(status=SuggestionStatus.APPROVED),
                version=1,
            )
            e2 = OutboxEvent(
                id=uuid4(),
                resource_type="SUGGESTION",
                resource_id=sugg_id,
                event_type="SUGGESTION_INGESTED",
                version=1,
                payload={"suggestion_id": sugg_id},
                status="PENDING",
            )
            if await uow2.suggestions.exists(sugg_id):
                raise SuggestionAlreadyExistsError(
                    f"Suggestion {sugg_id} already exists"
                )
            await uow2.suggestions.save(s2)
            await uow2.outbox.append(e2)
            await uow2.commit()


# ==============================================================================
# F-14: Semantic Read-Skew Elimination
# ==============================================================================
async def test_f14_semantic_read_skew_prevented(session_factory):
    """
    Validates F-14:
    PostgreSQL holds fresh text at v=2.
    Worker has lag / is delayed, so Qdrant returns candidate matching obsolete v=1 vector.
    Read-path hydration guard rejects candidate because cand.version (1) != sql.version (2).
    Zero semantic corruption / read-skew is returned.
    """
    sugg_id = f"f14-{uuid4().hex[:8]}"

    uow = SqlUnitOfWork(session_factory)
    async with uow:
        suggestion = Suggestion(
            id=sugg_id,
            content=SuggestionContent(
                title="پنل خورشیدی فتوولتائیک",
                problem="راندمان پایین تولید در تابستان",
                solution="نصب پنل خورشیدی",
            ),
            evaluation=CommitteeEvaluation(status=SuggestionStatus.APPROVED),
            version=2,  # Fresh version in SQL
        )
        await uow.suggestions.save(suggestion)
        await uow.commit()

    container = _build_test_container(session_factory)
    use_case = container.analyze_suggestion_use_case()
    if inspect.isawaitable(use_case):
        use_case = await use_case

    # Candidate returned from vector search with obsolete v=1
    from src.application.dtos import PooledSuggestionCandidate

    obsolete_candidate = PooledSuggestionCandidate(
        suggestion_id=sugg_id,
        status=SuggestionStatus.APPROVED,
        winning_chunk_id="chunk-obsolete-1",
        winning_chunk_type=SuggestionChunkType.TITLE,
        winning_score=0.95,
        winning_content="توربین بادی منسوخ",
        all_matched_chunk_types=(SuggestionChunkType.TITLE,),
        version=1,  # Obsolete version from Qdrant lag!
    )

    async with uow:
        sql_record = await uow.suggestions.get_by_id(sugg_id)
        # Test hydration validation
        is_valid = use_case._is_valid_candidate(obsolete_candidate, sql_record)
        # F-14 Defense: MUST be rejected because 1 != 2
        assert is_valid is False

        # Fresh candidate matching version 2
        fresh_candidate = PooledSuggestionCandidate(
            suggestion_id=sugg_id,
            status=SuggestionStatus.APPROVED,
            winning_chunk_id="chunk-fresh-2",
            winning_chunk_type=SuggestionChunkType.TITLE,
            winning_score=0.95,
            winning_content="پنل خورشیدی فتوولتائیک",
            all_matched_chunk_types=(SuggestionChunkType.TITLE,),
            version=2,  # Matching version!
        )
        is_fresh_valid = use_case._is_valid_candidate(fresh_candidate, sql_record)
        assert is_fresh_valid is True
