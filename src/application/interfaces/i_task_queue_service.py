from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ITaskQueueService(ABC):
    """
    Application port for asynchronous background task dispatching.
    Decouples application use cases from specific queue implementations (e.g. ARQ/Redis).
    """

    @abstractmethod
    async def enqueue_task(
        self,
        task_name: str,
        *args: Any,
        defer_by: int | None = None,
        **kwargs: Any,
    ) -> str:
        """
        Enqueues an asynchronous background task by name and returns the unique job ID.

        Args:
            task_name: Registered name of the background task function.
            *args: Positional arguments to forward to the task.
            defer_by: Optional delay in seconds before the task becomes eligible for execution.
            **kwargs: Keyword arguments to forward to the task.

        Returns:
            Unique string job identifier assigned by the queue backend.

        Raises:
            TaskQueueError: If task dispatching fails or the queue is unreachable.
        """
        pass


__all__ = ["ITaskQueueService"]
