from __future__ import annotations

from src.containers import Container
from src.infrastructure.configs.settings import redis_settings, worker_settings

from src.infrastructure.services.task_queue.arq_task_queue import ArqTaskQueueService


def test_settings_loaded():
    assert redis_settings.REDIS_HOST is not None
    assert redis_settings.REDIS_PORT == 7379
    assert worker_settings.JOB_TIMEOUT == 300
    assert worker_settings.HEALTH_CHECK_INTERVAL == 10


def test_container_providers_registered():
    container = Container()

    # Verify providers exist on Container
    assert hasattr(container, "arq_redis_pool")
    assert hasattr(container, "task_queue_service")

    # Verify task_queue_service provider is configured with ArqTaskQueueService
    provider = container.task_queue_service
    assert provider.cls is ArqTaskQueueService
