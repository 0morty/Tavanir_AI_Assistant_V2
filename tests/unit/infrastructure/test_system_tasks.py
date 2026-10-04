from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.infrastructure.tasks.system_tasks import ping_task

from src.infrastructure.tasks.cron_tasks import worker_heartbeat_cron
from src.worker import WorkerSettings, shutdown, startup


@pytest.mark.asyncio
async def test_ping_task_execution():
    ctx = {"job_id": "test-job-999"}
    result = await ping_task(ctx, message="antigravity")

    assert result["status"] == "ok"
    assert result["echo"] == "antigravity"
    assert result["job_id"] == "test-job-999"


@pytest.mark.asyncio
async def test_ping_task_default_message():
    ctx = {}
    result = await ping_task(ctx)

    assert result["status"] == "ok"
    assert result["echo"] == "pong"
    assert result["job_id"] is None


@pytest.mark.asyncio
async def test_worker_heartbeat_cron_with_container():
    mock_container = MagicMock()
    ctx = {"di_container": mock_container}

    # Should execute cleanly without raising
    await worker_heartbeat_cron(ctx)


@pytest.mark.asyncio
async def test_worker_heartbeat_cron_without_container():
    ctx = {}
    # Should handle missing container gracefully without crashing
    await worker_heartbeat_cron(ctx)


@pytest.mark.asyncio
async def test_worker_startup_and_shutdown(monkeypatch):
    mock_container_cls = MagicMock()
    mock_container_instance = MagicMock()
    mock_container_instance.init_resources = AsyncMock()
    mock_container_instance.shutdown_resources = AsyncMock()
    mock_container_cls.return_value = mock_container_instance

    monkeypatch.setattr("src.worker.Container", mock_container_cls)

    ctx = {}
    await startup(ctx)

    assert "di_container" in ctx
    mock_container_instance.init_resources.assert_awaited_once()

    await shutdown(ctx)
    mock_container_instance.shutdown_resources.assert_awaited_once()


def test_worker_settings_configuration():
    assert len(WorkerSettings.functions) >= 1
    assert any(
        getattr(f, "name", getattr(f, "__name__", "")) == "ping_task"
        for f in WorkerSettings.functions
    )
    assert len(WorkerSettings.cron_jobs) >= 1
    assert WorkerSettings.health_check_key == "arq:health-check"
    assert WorkerSettings.health_check_interval > 0
    assert WorkerSettings.job_timeout > 0
    assert WorkerSettings.max_tries > 0
    assert WorkerSettings.max_jobs > 0
