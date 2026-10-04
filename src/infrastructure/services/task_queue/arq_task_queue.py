from __future__ import annotations

from datetime import timedelta
from typing import Any

import structlog
from arq.connections import ArqRedis

from src.application.exceptions import TaskQueueError
from src.application.interfaces.i_task_queue_service import ITaskQueueService

logger = structlog.get_logger(__name__)


class ArqTaskQueueService(ITaskQueueService):
    """
    ARQ-backed task queue service implementing ITaskQueueService.
    Dispatches asynchronous jobs to Redis using an injected ArqRedis pool.
    """

    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    async def enqueue_task(
        self,
        task_name: str,
        *args: Any,
        defer_by: int | None = None,
        **kwargs: Any,
    ) -> str:
        """
        Enqueues an asynchronous background task by name into Redis via ARQ.

        Args:
            task_name: Function name registered in ARQ WorkerSettings.functions.
            *args: Positional arguments for the task.
            defer_by: Optional delay in seconds before execution.
            **kwargs: Keyword arguments for the task.

        Returns:
            The unique ARQ job identifier.

        Raises:
            TaskQueueError: If enqueue fails or Redis is unreachable.
        """
        defer_timedelta = timedelta(seconds=defer_by) if defer_by is not None else None
        try:
            job = await self._pool.enqueue_job(
                task_name,
                *args,
                _defer_by=defer_timedelta,
                **kwargs,
            )
            if job is None:
                raise TaskQueueError(
                    f"Task '{task_name}' was not enqueued (duplicate job or rejected by queue)"
                )

            await logger.adebug(
                "Task enqueued successfully",
                task_name=task_name,
                job_id=job.job_id,
                defer_by=defer_by,
            )
            return job.job_id

        except Exception as exc:
            if isinstance(exc, TaskQueueError):
                raise
            await logger.aerror(
                "Failed to enqueue task",
                task_name=task_name,
                error=str(exc),
            )
            raise TaskQueueError(
                f"Failed to enqueue task '{task_name}': {exc}"
            ) from exc


__all__ = ["ArqTaskQueueService"]
