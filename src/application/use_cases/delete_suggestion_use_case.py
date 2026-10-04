from __future__ import annotations

from uuid import uuid4

import structlog

from src.application.dtos import DeleteSuggestionResponseDTO
from src.application.interfaces import ITaskQueueService, IUnitOfWork
from src.application.utils.advisory_lock import suggestion_id_to_lock_key
from src.domain.entities import OutboxEvent
from src.domain.enums import OutboxEventType, OutboxResourceType
from src.domain.exceptions import (
    SuggestionNotFoundError,
    SuggestionProcessingConflictError,
)

logger = structlog.get_logger(__name__)


class DeleteSuggestionUseCase:
    """
    Orchestrates single suggestion soft deletion via Transactional Outbox (ADR-001, ADR-002).
    Saves soft-deletion and appends SUGGESTION_DELETED outbox event within a single atomic
    PostgreSQL transaction, permanently eliminating split-brain delete compensations (F-10 & F-11).
    """

    def __init__(
        self,
        uow: IUnitOfWork,
        task_queue: ITaskQueueService,
    ) -> None:
        self._uow = uow
        self._task_queue = task_queue

    async def execute(self, suggestion_id: str) -> DeleteSuggestionResponseDTO:
        lock_key = suggestion_id_to_lock_key(suggestion_id)
        already_deleted = False

        event_id = uuid4()

        async with self._uow as uow:
            locked = await uow.try_acquire_advisory_lock(lock_key)
            if not locked:
                raise SuggestionProcessingConflictError(
                    f"Suggestion '{suggestion_id}' is currently being modified by another operation.",
                    pointer="/data/suggestionId",
                )

            suggestion = await uow.suggestions.get_by_id(
                suggestion_id, include_deleted=True
            )
            if suggestion is None:
                raise SuggestionNotFoundError(
                    f"Suggestion with ID '{suggestion_id}' not found.",
                    pointer="/data/suggestionId",
                )

            if suggestion.is_deleted:
                already_deleted = True
            else:
                new_version = suggestion.version + 1
                await uow.suggestions.soft_delete(suggestion_id)
                event = OutboxEvent(
                    id=event_id,
                    resource_type=OutboxResourceType.SUGGESTION,
                    resource_id=suggestion_id,
                    event_type=OutboxEventType.SUGGESTION_DELETED,
                    version=new_version,
                    payload={"suggestion_id": suggestion_id, "version": new_version},
                )
                await uow.outbox.append(event)
                await uow.commit()

        # Idempotent no-op if already soft-deleted
        if already_deleted:
            await logger.ainfo(
                "Suggestion was already soft-deleted; returning idempotent response",
                suggestion_id=suggestion_id,
            )
            return DeleteSuggestionResponseDTO(
                suggestion_id=suggestion_id,
                status="DELETED",
            )

        # Asynchronous Dispatch via ARQ (fire-and-forget buffer)
        try:
            await self._task_queue.enqueue_task(
                "process_outbox_event_task",
                event_id=str(event_id),
                deduplication_id=str(event_id),
            )
        except Exception as queue_err:
            await logger.awarning(
                "Failed to enqueue delete outbox event to Redis; sweeper will recover it",
                event_id=str(event_id),
                error=str(queue_err),
            )

        await logger.ainfo(
            "Suggestion soft-deleted with outbox event",
            suggestion_id=suggestion_id,
            event_id=str(event_id),
        )

        return DeleteSuggestionResponseDTO(
            suggestion_id=suggestion_id,
            status="DELETED",
        )


__all__ = ["DeleteSuggestionUseCase"]
