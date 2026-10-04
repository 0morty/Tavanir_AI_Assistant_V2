from __future__ import annotations

import logging

from src.application.interfaces.i_hybrid_embedding_service import (
    IHybridEmbeddingService,
)
from src.application.interfaces.i_outbox_event_handler import IOutboxEventHandler
from src.application.interfaces.i_text_normalizer import ITextNormalizer
from src.application.interfaces.i_unit_of_work import IUnitOfWork
from src.domain.entities import OutboxEvent
from src.domain.enums import ChunkStatus, OutboxEventStatus
from src.domain.interfaces.i_chunking_strategy import ISuggestionChunker
from src.domain.interfaces.i_suggestion_vector_repository import (
    ISuggestionVectorRepository,
)

logger = logging.getLogger(__name__)


class UpdateSuggestionVectorsHandler(IOutboxEventHandler):
    """
    Projection strategy for updated suggestions (V -> V+1 cutover).
    Performs supersede check (F-12), stages new vectors, and executes
    strictly version-bounded idempotent cutover (F-01).
    """

    def __init__(
        self,
        chunker: ISuggestionChunker,
        embedding_service: IHybridEmbeddingService,
        vector_repo: ISuggestionVectorRepository,
        normalizer: ITextNormalizer,
    ) -> None:
        self._chunker = chunker
        self._embedding_service = embedding_service
        self._vector_repo = vector_repo
        self._normalizer = normalizer

    async def handle(self, event: OutboxEvent, uow: IUnitOfWork) -> None:
        suggestion = await uow.suggestions.get_by_id(event.resource_id)
        if suggestion is None:
            logger.warning(
                "Cannot update vectors: Suggestion not found in SQL",
                extra={"resource_id": event.resource_id, "event_id": str(event.id)},
            )
            return

        if suggestion.is_deleted:
            logger.info(
                "Skipping vector update: Suggestion is soft-deleted",
                extra={"resource_id": event.resource_id, "event_id": str(event.id)},
            )
            return

        # 1. Supersede Check (F-12)
        if suggestion.version > event.version:
            logger.info(
                "Outbox event superseded by newer version in SQL (event_v=%d, sql_v=%d)",
                event.version,
                suggestion.version,
                extra={"resource_id": event.resource_id, "event_id": str(event.id)},
            )
            event.status = OutboxEventStatus.SUPERSEDED
            return

        # 2. Chunk suggestion with STAGING status and exact version
        chunks = await self._chunker.chunk(suggestion)
        if not chunks:
            logger.warning(
                "Suggestion chunker produced zero chunks for update",
                extra={"resource_id": event.resource_id},
            )
            return

        for chunk in chunks:
            chunk.version = event.version
            chunk.chunk_status = ChunkStatus.STAGING

        # 3. Generate dense + sparse embeddings concurrently
        await self._embedding_service.embed_chunks(chunks)

        # 4. Upsert staging points into Qdrant
        await self._vector_repo.upsert_chunks_batch(chunks)

        # 5. Idempotent Atomic Cutover (F-01)
        # 5a. Promote staging points with version == event.version to ACTIVE
        await self._vector_repo.activate_version_chunks(
            parent_id=event.resource_id,
            target_version=event.version,
        )

        # 5b. Purge obsolete points with version < event.version
        await self._vector_repo.delete_obsolete_version_chunks(
            parent_id=event.resource_id,
            max_version_exclusive=event.version,
        )

        logger.info(
            "Successfully cut over %d vectors for suggestion %s to v=%d",
            len(chunks),
            event.resource_id,
            event.version,
        )


__all__ = ["UpdateSuggestionVectorsHandler"]
