from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from src.containers import Container

logger = structlog.get_logger(__name__)


async def worker_heartbeat_cron(ctx: dict[str, Any]) -> None:
    """
    Periodic scheduled task demonstrating cron engine capability.
    Validates container accessibility in the worker context.
    """
    container: Container | None = ctx.get("di_container")
    if container is None:
        await logger.aerror("DI Container missing in worker cron context")
        return
    await logger.adebug("Worker cron heartbeat triggered successfully")


async def sweep_stale_outbox_events_task(ctx: dict[str, Any]) -> None:
    """
    Scheduled cron running every 5 minutes:
    1. Resets crashed 'PROCESSING' locks back to 'PENDING' and re-enqueues them.
    2. Re-enqueues unhandled 'PENDING' events older than 1 minute.
    3. Auto-heals 'FAILED' events from extended outages (< 24h old, < 20 retries).
    """
    container: Container | None = ctx.get("di_container")
    if container is None:
        await logger.aerror("DI Container missing in sweeper cron context")
        return

    uow = container.unit_of_work()
    task_queue = container.task_queue_service()
    now = datetime.now(timezone.utc)

    # 1. Recover crashed PROCESSING events
    stuck_before = now - timedelta(minutes=5)
    async with uow:
        stale_events = await uow.outbox.fetch_stale_events(stuck_before=stuck_before)
        for event in stale_events:
            await uow.outbox.update_status(event_id=event.id, status="PENDING")
        await uow.commit()

    for event in stale_events:
        await task_queue.enqueue_task(
            "process_outbox_event_task",
            event_id=str(event.id),
            deduplication_id=f"stale-{event.id}-{int(now.timestamp())}",
        )
        await logger.awarning(
            "Re-enqueued stuck outbox event",
            event_id=str(event.id),
            resource_id=event.resource_id,
        )

    # 2. Re-enqueue unhandled PENDING events
    pending_before = now - timedelta(minutes=1)
    async with uow:
        pending_events = await uow.outbox.fetch_pending_events(
            created_before=pending_before
        )

    for event in pending_events:
        await task_queue.enqueue_task(
            "process_outbox_event_task",
            event_id=str(event.id),
            deduplication_id=f"pending-{event.id}-{int(now.timestamp())}",
        )
        await logger.ainfo(
            "Re-enqueued unhandled pending outbox event",
            event_id=str(event.id),
            resource_id=event.resource_id,
        )

    # 3. Extended Outage Auto-Healing (events failed < 24h ago with < 20 retries)
    failed_after = now - timedelta(hours=24)
    async with uow:
        failed_events = await uow.outbox.fetch_failed_for_retry(
            created_after=failed_after, max_retries=20
        )
        for event in failed_events:
            await uow.outbox.update_status(event_id=event.id, status="PENDING")
        await uow.commit()

    for event in failed_events:
        await task_queue.enqueue_task(
            "process_outbox_event_task",
            event_id=str(event.id),
            deduplication_id=f"reheal-{event.id}-{int(now.timestamp())}",
        )
        await logger.ainfo(
            "Auto-healing failed outbox event from extended outage",
            event_id=str(event.id),
            retry_count=event.retry_count,
        )


async def prune_completed_outbox_events_cron(ctx: dict[str, Any]) -> None:
    """
    Scheduled cron running daily at 02:00 UTC.
    Prunes 'COMPLETED' and 'SUPERSEDED' outbox events older than 7 days.
    """
    container: Container | None = ctx.get("di_container")
    if container is None:
        await logger.aerror("DI Container missing in prune cron context")
        return

    uow = container.unit_of_work()
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    async with uow:
        deleted_count = await uow.outbox.prune_completed(before=cutoff)
        await uow.commit()

    await logger.ainfo(
        "Pruned completed outbox events",
        pruned_count=deleted_count,
        cutoff=cutoff.isoformat(),
    )


__all__ = [
    "worker_heartbeat_cron",
    "sweep_stale_outbox_events_task",
    "prune_completed_outbox_events_cron",
]
