from __future__ import annotations

from typing import Any

import structlog
from arq import cron, func
from arq.connections import RedisSettings as ArqRedisSettings

from src.containers import Container
from src.infrastructure.configs.logging_setup import configure_logging
from src.infrastructure.configs.settings import redis_settings, worker_settings
from src.infrastructure.tasks.cron_tasks import (
    prune_completed_outbox_events_cron,
    sweep_stale_outbox_events_task,
    worker_heartbeat_cron,
)
from src.infrastructure.tasks.outbox_tasks import process_outbox_event_task
from src.infrastructure.tasks.system_tasks import ping_task

logger = structlog.get_logger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    """
    Worker startup hook: Configures logging and bootstraps an isolated DI Container.
    Initializes long-lived container resources (e.g. database pools, HTTP clients).
    """
    configure_logging()
    container = Container()
    await container.init_resources()  # type: ignore
    ctx["di_container"] = container
    await logger.ainfo("ARQ Worker initialized successfully")


async def shutdown(ctx: dict[str, Any]) -> None:
    """
    Worker shutdown hook: Gracefully tears down all DI container resources.
    """
    await logger.ainfo("ARQ Worker shutting down...")
    container: Container | None = ctx.get("di_container")
    if container is not None:
        try:
            await container.shutdown_resources()  # type: ignore
        except Exception as exc:
            await logger.aerror("Error during container shutdown", error=str(exc))
    await logger.ainfo("ARQ Worker shut down cleanly")


class WorkerSettings:
    """
    ARQ Worker configuration defining task handlers, cron schedules,
    Redis connectivity, timeouts, retries, and healthcheck settings.
    """

    # Dedicated specific task functions
    functions = [
        func(ping_task, name="ping_task", timeout=30),
        func(
            process_outbox_event_task,
            name="process_outbox_event_task",
            timeout=worker_settings.JOB_TIMEOUT,
            max_tries=worker_settings.MAX_RETRIES,
        ),
    ]

    # Scheduled cron jobs
    cron_jobs = [
        cron(worker_heartbeat_cron, minute=0),
        cron(
            sweep_stale_outbox_events_task,
            minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
        ),
        cron(
            prune_completed_outbox_events_cron,
            hour=2,
            minute=0,
        ),
    ]

    # Redis connection settings
    redis_settings = ArqRedisSettings(
        host=redis_settings.REDIS_HOST,
        port=redis_settings.REDIS_PORT,
        password=redis_settings.REDIS_PASSWORD or None,
        database=redis_settings.REDIS_DB,
    )

    job_timeout = worker_settings.JOB_TIMEOUT
    max_tries = worker_settings.MAX_RETRIES
    max_jobs = worker_settings.MAX_JOBS
    health_check_interval = worker_settings.HEALTH_CHECK_INTERVAL
    health_check_key = "arq:health-check"

    on_startup = startup
    on_shutdown = shutdown


__all__ = ["WorkerSettings", "shutdown", "startup"]
