from __future__ import annotations

import structlog

from src.application.dtos import DeleteSuggestionResponseDTO
from src.application.interfaces import IUnitOfWork
from src.application.utils.advisory_lock import suggestion_id_to_lock_key
from src.domain.exceptions import (
    SuggestionNotFoundError,
    SuggestionProcessingConflictError,
)
from src.domain.interfaces import ISuggestionVectorRepository

logger = structlog.get_logger(__name__)


class DeleteSuggestionUseCase:
    """
    Orchestrates single suggestion soft deletion with advisory locking,
    idempotent re-entry, Qdrant vector purge, and compensating SQL restoration.

    Workflow:
    1. Acquire 64-bit PostgreSQL transaction advisory lock.
    2. Read record state:
       - If not found -> SuggestionNotFoundError (404).
       - If already soft-deleted -> Return success immediately (idempotent 200).
    3. Execute SQL soft-delete (sets is_deleted = True, updated_at = NOW()) and commit.
    4. Physically purge vector points for parent_id from Qdrant.
    5. If Qdrant purge fails, execute compensating SQL restoration (is_deleted = False)
       with re-acquired advisory lock so the suggestion remains consistently active.
    """

    def __init__(
        self,
        uow: IUnitOfWork,
        vector_repo: ISuggestionVectorRepository,
    ) -> None:
        self._uow = uow
        self._vector_repo = vector_repo

    async def execute(self, suggestion_id: str) -> DeleteSuggestionResponseDTO:
        lock_key = suggestion_id_to_lock_key(suggestion_id)
        already_deleted = False

        # Step 1-3: Guarded SQL soft-delete
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
                await uow.suggestions.soft_delete(suggestion_id)
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

        # Step 4: Physically purge vector chunks from Qdrant
        # FIXME: [Architectural Tech Debt - Dual-Store Deletion Consistency via Transactional Outbox]
        # In a distributed dual-store architecture (PostgreSQL + Qdrant), committing SQL first and then
        # executing synchronous vector deletion introduces split-brain exposure:
        # 1. The PostgreSQL transaction-scoped advisory lock releases immediately upon commit in Step 3.
        # 2. While Qdrant is being contacted in Step 4, a concurrent operation could modify or recreate chunks.
        # 3. If Qdrant fails, compensating restoration attempts to undo the soft-delete in PostgreSQL,
        #    which itself can fail or race with concurrent writes.
        # Target Architecture:
        #   Implement Transactional Outbox pattern for vector operations. Soft-deletion records a
        #   reconciliation event (`VectorPurgeEvent`) in PostgreSQL within the same atomic transaction.
        #   An asynchronous ARQ/Redis worker picks up the event, executes idempotent Qdrant purges with
        #   exponential backoff and dead-letter queues, guaranteeing 100% eventual consistency without
        #   needing synchronous rollbacks.
        # Current Mitigation:
        #   Re-acquire the advisory lock during compensating restoration in Step 5 and increment the
        #   optimistic version token so downstream observers detect the state restoration.
        try:
            await self._vector_repo.delete_chunks_by_parent_id(suggestion_id)
        except Exception as qdrant_err:
            await logger.aerror(
                "Qdrant vector purge failed during soft-delete; executing compensating SQL restoration",
                suggestion_id=suggestion_id,
                error=str(qdrant_err),
                exc_info=True,
            )

            # Step 5: Compensating SQL restoration (Guarded with advisory lock re-acquisition)
            try:
                async with self._uow as comp_uow:
                    locked = await comp_uow.try_acquire_advisory_lock(lock_key)
                    if not locked:
                        await logger.acritical(
                            "Failed to acquire advisory lock during compensating SQL restoration; potential concurrent collision",
                            suggestion_id=suggestion_id,
                        )

                    record = await comp_uow.suggestions.get_by_id(
                        suggestion_id, include_deleted=True
                    )
                    if record is not None:
                        record.restore()
                        record.increment_version()
                        await comp_uow.suggestions.save(record)
                        await comp_uow.commit()

                await logger.ainfo(
                    "Compensating SQL restoration succeeded",
                    suggestion_id=suggestion_id,
                )
            except Exception as comp_err:
                await logger.acritical(
                    "Compensating SQL restoration failed! System in inconsistent state",
                    suggestion_id=suggestion_id,
                    error=str(comp_err),
                    exc_info=True,
                )

            raise qdrant_err

        await logger.ainfo(
            "Suggestion soft-deleted successfully and vector chunks purged",
            suggestion_id=suggestion_id,
        )

        return DeleteSuggestionResponseDTO(
            suggestion_id=suggestion_id,
            status="DELETED",
        )


__all__ = ["DeleteSuggestionUseCase"]
