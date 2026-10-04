from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.exceptions import TaskQueueError
from src.infrastructure.services.task_queue.arq_task_queue import ArqTaskQueueService


@pytest.mark.asyncio
async def test_arq_task_queue_enqueue_success():
    mock_pool = MagicMock()
    mock_job = MagicMock()
    mock_job.job_id = "job-abc-123"
    mock_pool.enqueue_job = AsyncMock(return_value=mock_job)

    service = ArqTaskQueueService(pool=mock_pool)
    result = await service.enqueue_task("ping_task", "hello", param1=42)

    assert result == "job-abc-123"
    mock_pool.enqueue_job.assert_awaited_once_with(
        "ping_task",
        "hello",
        _defer_by=None,
        param1=42,
    )


@pytest.mark.asyncio
async def test_arq_task_queue_enqueue_with_defer_by():
    mock_pool = MagicMock()
    mock_job = MagicMock()
    mock_job.job_id = "job-def-456"
    mock_pool.enqueue_job = AsyncMock(return_value=mock_job)

    service = ArqTaskQueueService(pool=mock_pool)
    result = await service.enqueue_task("ping_task", defer_by=15)

    assert result == "job-def-456"
    mock_pool.enqueue_job.assert_awaited_once_with(
        "ping_task",
        _defer_by=timedelta(seconds=15),
    )


@pytest.mark.asyncio
async def test_arq_task_queue_enqueue_returns_none_raises_error():
    mock_pool = MagicMock()
    mock_pool.enqueue_job = AsyncMock(return_value=None)

    service = ArqTaskQueueService(pool=mock_pool)
    with pytest.raises(TaskQueueError, match="was not enqueued"):
        await service.enqueue_task("ping_task")


@pytest.mark.asyncio
async def test_arq_task_queue_enqueue_exception_translated():
    mock_pool = MagicMock()
    mock_pool.enqueue_job = AsyncMock(
        side_effect=ConnectionError("Redis connection lost")
    )

    service = ArqTaskQueueService(pool=mock_pool)
    with pytest.raises(TaskQueueError, match="Failed to enqueue task 'ping_task'"):
        await service.enqueue_task("ping_task")
