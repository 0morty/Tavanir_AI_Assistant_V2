from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from arq import Retry
from src.infrastructure.tasks.outbox_tasks import process_outbox_event_task


@pytest.mark.asyncio
async def test_process_outbox_event_task_success():
    event_id = str(uuid4())
    mock_use_case = AsyncMock()
    mock_container = MagicMock()
    mock_container.process_outbox_event_use_case.return_value = mock_use_case

    ctx = {"di_container": mock_container, "job_try": 1}
    await process_outbox_event_task(ctx, event_id)

    mock_use_case.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_outbox_event_task_maps_exception_to_arq_retry():
    event_id = str(uuid4())
    mock_use_case = AsyncMock()
    mock_use_case.execute.side_effect = RuntimeError("Temporary vector DB partition")
    mock_container = MagicMock()
    mock_container.process_outbox_event_use_case.return_value = mock_use_case

    ctx = {"di_container": mock_container, "job_try": 2}

    with pytest.raises(Retry) as exc_info:
        await process_outbox_event_task(ctx, event_id)

    # Retry delay for attempt 2 is 2.0 * (2 ** (2 - 1)) = 4.0s (4000ms in arq)
    assert exc_info.value.defer_score in (4000, 4.0)
