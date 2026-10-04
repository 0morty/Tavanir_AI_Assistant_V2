import inspect
import logging
from uuid import UUID

from arq import Retry

logger = logging.getLogger(__name__)


async def process_outbox_event_task(ctx: dict, event_id: str) -> None:
    """
    Razor-thin ARQ worker adapter for outbox event execution.
    Resolves ProcessOutboxEventUseCase from DI container and triggers execution.
    On failure, computes exponential backoff and raises arq.Retry.
    """
    container = ctx["di_container"]
    use_case = container.process_outbox_event_use_case()
    if inspect.isawaitable(use_case):
        use_case = await use_case
    attempt = ctx.get("job_try", 1)

    try:
        await use_case.execute(UUID(event_id))
    except Exception as exc:
        delay = min(2.0 * (2 ** (attempt - 1)), 60.0)
        logger.warning(
            "Outbox task %s failed attempt %d, retrying in %.1fs: %s",
            event_id,
            attempt,
            delay,
            exc,
        )
        raise Retry(defer=delay) from exc


__all__ = ["process_outbox_event_task"]
