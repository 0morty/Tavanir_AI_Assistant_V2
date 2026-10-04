from __future__ import annotations

import logging
from uuid import UUID

from src.application.interfaces.i_unit_of_work import IUnitOfWork
from src.application.services.outbox.outbox_handler_registry import (
    OutboxHandlerRegistry,
)
from src.domain.enums import OutboxEventStatus

logger = logging.getLogger(__name__)


class ProcessOutboxEventUseCase:
    """
    Orchestration use case for transactional outbox event consumption.
    Manages event claiming (row-level locking), strategy resolution via registry,
    idempotent execution, and state machine transitions.
    """

    def __init__(
        self,
        uow: IUnitOfWork,
        registry: OutboxHandlerRegistry,
        max_immediate_retries: int = 5,
    ) -> None:
        self._uow = uow
        self._registry = registry
        self._max_immediate_retries = max_immediate_retries

    async def execute(self, event_id: UUID) -> None:
        """
        Executes the outbox event processing lifecycle for the given event ID.

        Args:
            event_id: UUID of the OutboxEvent to process.
        """
        # Step 1: Claim event with FOR UPDATE SKIP LOCKED
        async with self._uow:
            event = await self._uow.outbox.get_for_processing(event_id)
            if event is None:
                logger.debug(
                    "Outbox event %s could not be locked (already claimed or missing)",
                    event_id,
                )
                return
            await self._uow.commit()

        # Step 2: Resolve handler and execute strategy
        try:
            handler = self._registry.get_handler(event.event_type)
            async with self._uow:
                await handler.handle(event, self._uow)
                target_status = (
                    OutboxEventStatus.SUPERSEDED
                    if event.status == OutboxEventStatus.SUPERSEDED
                    else OutboxEventStatus.COMPLETED
                )
                await self._uow.outbox.update_status(
                    event_id=event.id,
                    status=target_status,
                    error=None,
                )
                await self._uow.commit()
            logger.info(
                "Outbox event %s processed successfully with status=%s",
                event_id,
                target_status,
            )
        except Exception as exc:
            logger.error(
                "Execution failed for outbox event %s: %s",
                event_id,
                exc,
                exc_info=True,
            )
            async with self._uow:
                new_retry_count = event.retry_count + 1
                new_status = (
                    OutboxEventStatus.FAILED
                    if new_retry_count >= self._max_immediate_retries
                    else OutboxEventStatus.PENDING
                )
                await self._uow.outbox.update_status(
                    event_id=event.id,
                    status=new_status,
                    error=str(exc),
                    retry_count=new_retry_count,
                )
                await self._uow.commit()
            raise


__all__ = ["ProcessOutboxEventUseCase"]
