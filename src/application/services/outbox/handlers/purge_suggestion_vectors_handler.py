from __future__ import annotations

import logging

from src.application.interfaces.i_outbox_event_handler import IOutboxEventHandler
from src.application.interfaces.i_unit_of_work import IUnitOfWork
from src.domain.entities import OutboxEvent
from src.domain.enums import OutboxEventStatus
from src.domain.interfaces.i_suggestion_vector_repository import (
    ISuggestionVectorRepository,
)

logger = logging.getLogger(__name__)


class PurgeSuggestionVectorsHandler(IOutboxEventHandler):
    """
    Projection strategy for soft-deleted suggestions (F-10 & F-11 resolution).
    Purges all vector chunks from Qdrant without ever running reverse compensation.
    Guarded by supersede check to avoid purging new PUT updates.
    """

    def __init__(self, vector_repo: ISuggestionVectorRepository) -> None:
        self._vector_repo = vector_repo

    async def handle(self, event: OutboxEvent, uow: IUnitOfWork) -> None:
        suggestion = await uow.suggestions.get_by_id(
            event.resource_id, include_deleted=True
        )
        if (
            suggestion is not None
            and not suggestion.is_deleted
            and suggestion.version > event.version
        ):
            logger.info(
                "Delete outbox event superseded by newer active PUT (event_v=%d, sql_v=%d)",
                event.version,
                suggestion.version,
                extra={"resource_id": event.resource_id, "event_id": str(event.id)},
            )
            event.status = OutboxEventStatus.SUPERSEDED
            return

        await self._vector_repo.delete_chunks_by_parent_id(event.resource_id)
        logger.info(
            "Successfully purged all vector points for suggestion %s (event_v=%d)",
            event.resource_id,
            event.version,
        )


__all__ = ["PurgeSuggestionVectorsHandler"]
