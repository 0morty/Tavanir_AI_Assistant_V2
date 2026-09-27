from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from src.domain.entities import (
    DenseVector,
    SparseVector,
    SuggestionChunk,
    SuggestionChunkMetadata,
    SuggestionSearchResult,
)
from src.domain.enums import ChunkStatus, SuggestionChunkType, SuggestionStatus
from src.domain.exceptions import VectorSearchError
from src.domain.interfaces.i_suggestion_vector_repository import (
    ISuggestionVectorRepository,
)
from src.infrastructure.configs.settings import embedding_settings, qdrant_settings
from src.infrastructure.db.repositories.qdrant.base import QdrantBaseVectorRepository
from src.infrastructure.db.repositories.qdrant.payload_schemas import (
    SuggestionChunkPayloadDTO,
)

logger = logging.getLogger(__name__)


class QdrantSuggestionRepository(
    QdrantBaseVectorRepository[SuggestionChunkMetadata], ISuggestionVectorRepository
):
    """
    Qdrant vector repository implementation for employee suggestions (ADR-001, ADR-002).
    Operates on `tavanir_suggestion_v1` collection.
    """

    def __init__(
        self,
        client: AsyncQdrantClient,
        collection_name: str = qdrant_settings.QDRANT_SUGGESTION_COLLECTION,
        dense_vector_name: str = qdrant_settings.QDRANT_DENSE_VECTOR_NAME,
        sparse_vector_name: str = qdrant_settings.QDRANT_SPARSE_VECTOR_NAME,
        default_dense_dim: int = embedding_settings.EMBEDDING_DIMENSION,
        batch_size: int = qdrant_settings.QDRANT_BATCH_SIZE,
        dense_score_threshold: float
        | None = qdrant_settings.QDRANT_DENSE_SCORE_THRESHOLD,
        sparse_score_threshold: float
        | None = qdrant_settings.QDRANT_SPARSE_SCORE_THRESHOLD,
        max_retries: int = qdrant_settings.QDRANT_MAX_RETRIES,
        retry_base_delay: float = qdrant_settings.QDRANT_RETRY_BASE_DELAY,
        retry_max_delay: float = qdrant_settings.QDRANT_RETRY_MAX_DELAY,
    ) -> None:
        super().__init__(
            client=client,
            collection_name=collection_name,
            dense_vector_name=dense_vector_name,
            sparse_vector_name=sparse_vector_name,
            default_dense_dim=default_dense_dim,
            batch_size=batch_size,
            dense_score_threshold=dense_score_threshold,
            sparse_score_threshold=sparse_score_threshold,
            max_retries=max_retries,
            retry_base_delay=retry_base_delay,
            retry_max_delay=retry_max_delay,
        )

    def _build_payload(self, chunk: SuggestionChunk) -> dict[str, Any]:
        return SuggestionChunkPayloadDTO.from_domain(chunk).model_dump(
            exclude_none=True
        )

    def _to_search_result(self, point: models.ScoredPoint) -> SuggestionSearchResult:
        return SuggestionChunkPayloadDTO.model_validate(point.payload or {}).to_domain(
            score=point.score
        )

    def _get_payload_schema_definitions(
        self,
    ) -> dict[str, models.PayloadSchemaType | models.TextIndexParams]:
        return {
            "parent_id": models.PayloadSchemaType.KEYWORD,
            "chunk_status": models.PayloadSchemaType.KEYWORD,
            "chunk_type": models.PayloadSchemaType.KEYWORD,
            "status": models.PayloadSchemaType.KEYWORD,
            "committee_scrutiny": models.PayloadSchemaType.KEYWORD,
            "committee_scrutiny_id": models.PayloadSchemaType.INTEGER,
            "secretariat_scrutiny": models.PayloadSchemaType.KEYWORD,
            "secretariat_scrutiny_id": models.PayloadSchemaType.INTEGER,
        }

    async def search_suggestions(
        self,
        dense_vector: DenseVector,
        sparse_vector: SparseVector,
        limit: int = 10,
        chunk_types: Sequence[SuggestionChunkType] | None = None,
        statuses: Sequence[SuggestionStatus] | None = None,
        context_title: str | None = None,
        score_threshold: float | None = None,
    ) -> list[SuggestionSearchResult]:
        """
        Execute hybrid search across suggestion child chunks using RRF fusion.
        """
        try:
            conditions: list[models.Condition] = [
                models.FieldCondition(
                    key="chunk_status",
                    match=models.MatchValue(value=ChunkStatus.ACTIVE.value),
                )
            ]

            effective_chunk_types = (
                chunk_types
                if chunk_types is not None
                else [
                    SuggestionChunkType.TITLE,
                    SuggestionChunkType.PROBLEM,
                    SuggestionChunkType.SOLUTION,
                ]
            )

            if effective_chunk_types:
                conditions.append(
                    models.FieldCondition(
                        key="chunk_type",
                        match=models.MatchAny(
                            any=[t.value for t in effective_chunk_types]
                        ),
                    )
                )

            if statuses:
                conditions.append(
                    models.FieldCondition(
                        key="status",
                        match=models.MatchAny(any=[s.title_fa for s in statuses]),
                    )
                )

            if context_title:
                conditions.append(
                    models.FieldCondition(
                        key="context_title",
                        match=models.MatchValue(value=context_title),
                    )
                )

            qdrant_filter = models.Filter(must=conditions)

            prefetch = [
                models.Prefetch(
                    query=list(dense_vector),
                    using=self._dense_vector_name,
                    limit=limit * 2,
                    filter=qdrant_filter,
                    score_threshold=self._dense_score_threshold,
                ),
                models.Prefetch(
                    query=models.SparseVector(
                        indices=sparse_vector.indices,
                        values=sparse_vector.values,
                    ),
                    using=self._sparse_vector_name,
                    limit=limit * 2,
                    filter=qdrant_filter,
                    score_threshold=self._sparse_score_threshold,
                ),
            ]

            query_response = await self._client.query_points(
                collection_name=self._collection_name,
                prefetch=prefetch,
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=limit,
                score_threshold=score_threshold,
                with_payload=True,
                with_vectors=False,
            )

            return [self._to_search_result(point) for point in query_response.points]

        except Exception as e:
            logger.error(
                f"Failed to execute search_suggestions in '{self._collection_name}': {e}",
                exc_info=True,
            )
            raise VectorSearchError(f"Failed to execute search_suggestions: {e}") from e


__all__ = ["QdrantSuggestionRepository"]
