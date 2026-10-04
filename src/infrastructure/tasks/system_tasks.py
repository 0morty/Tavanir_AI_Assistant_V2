from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


async def ping_task(ctx: dict[str, Any], message: str = "pong") -> dict[str, Any]:
    """
    Dedicated background task for connectivity verification, latency diagnostic,
    and end-to-end task queue testing.
    """
    await logger.adebug(
        "Executing ping_task", message=message, job_id=ctx.get("job_id")
    )
    return {
        "status": "ok",
        "echo": message,
        "job_id": ctx.get("job_id"),
    }


__all__ = ["ping_task"]
