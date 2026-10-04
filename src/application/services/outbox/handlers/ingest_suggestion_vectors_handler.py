from __future__ import annotations

import logging

from src.application.interfaces.i_hybrid_embedding_service import (
    IHybridEmbeddingService,
)
from src.application.interfaces.i_outbox_event_handler import IOutboxEventHandler
from src.application.interfaces.i_text_normalizer import ITextNormalizer
from src.application.interfaces.i_unit_of_work import IUnitOfWork
from src.domain.entities import OutboxEvent
from src.domain.enums import ChunkStatus
from src.domain.interfaces.i_chunking_strategy import ISuggestionChunker
from src.domain.interfaces.i_suggestion_vector_repository import (
    ISuggestionVectorRepository,
)

logger = logging.getLogger(__name__)


class IngestSuggestionVectorsHandler(IOutboxEventHandler):
    """
    Projection strategy for newly ingested suggestions (0 -> 1 initialization).
    Cleans any residual orphan staging points from aborted prior attempts,
    generates hybrid embeddings, and directly upserts chunks as ACTIVE.
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
                "Cannot ingest vectors: Suggestion not found in SQL",
                extra={"resource_id": event.resource_id, "event_id": str(event.id)},
            )
            return

        if suggestion.is_deleted:
            logger.info(
                "Skipping vector ingestion: Suggestion is soft-deleted",
                extra={"resource_id": event.resource_id, "event_id": str(event.id)},
            )
            return

        # 1. Clean orphan points left from aborted prior ingestion attempts
        await self._vector_repo.delete_chunks_by_parent_id(event.resource_id)

        # 2. Chunk suggestion
        chunks = await self._chunker.chunk(suggestion)
        if not chunks:
            logger.warning(
                "Suggestion chunker produced zero chunks for ingestion",
                extra={"resource_id": event.resource_id},
            )
            return

        for chunk in chunks:
            chunk.version = event.version
            chunk.chunk_status = ChunkStatus.ACTIVE

        # 3. Generate dense + sparse embeddings concurrently
        await self._embedding_service.embed_chunks(chunks)

        # 4. Upsert active points directly to Qdrant
        await self._vector_repo.upsert_chunks_batch(chunks)
        logger.info(
            "Successfully projected %d active vectors for suggestion %s (v=%d)",
            len(chunks),
            event.resource_id,
            event.version,
        )


__all__ = ["IngestSuggestionVectorsHandler"]
