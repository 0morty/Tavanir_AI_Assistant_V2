from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from src.domain.entities import (
    DenseVector,
    RegulatoryChunk,
    RegulatoryChunkMetadata,
    RegulatorySearchResult,
    SparseVector,
)
from src.domain.enums import AuthorityLevel, ChunkStatus, RegulatoryDocumentType
from src.domain.exceptions import VectorSearchError
from src.domain.interfaces.i_regulatory_vector_repository import (
    IRegulatoryVectorRepository,
)
from src.infrastructure.configs.settings import embedding_settings, qdrant_settings
from src.infrastructure.db.repositories.qdrant.base import QdrantBaseVectorRepository
from src.infrastructure.db.repositories.qdrant.payload_schemas import (
    RegulatoryChunkPayloadDTO,
)

logger = logging.getLogger(__name__)


class QdrantRegulatoryRepository(
    QdrantBaseVectorRepository[RegulatoryChunkMetadata], IRegulatoryVectorRepository
):
    """
    Qdrant vector repository implementation for regulatory knowledge (ADR-001, ADR-003).
    Operates on `tavanir_regulatory_knowledge_v1` collection.
    """

    def __init__(
        self,
        client: AsyncQdrantClient,
        collection_name: str = qdrant_settings.QDRANT_REGULATORY_COLLECTION,
        dense_vector_name: str = qdrant_settings.QDRANT_DENSE_VECTOR_NAME,
        sparse_vector_name: str = qdrant_settings.QDRANT_SPARSE_VECTOR_NAME,
        default_dense_dim: int = embedding_settings.EMBEDDING_DIMENSION,
        batch_size: int = qdrant_settings.QDRANT_BATCH_SIZE,
        dense_score_threshold: float | None = qdrant_settings.QDRANT_DENSE_SCORE_THRESHOLD,
        sparse_score_threshold: float | None = qdrant_settings.QDRANT_SPARSE_SCORE_THRESHOLD,
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

    def _build_payload(self, chunk: RegulatoryChunk) -> dict[str, Any]:
        return RegulatoryChunkPayloadDTO.from_domain(chunk).model_dump(
            exclude_none=True
        )

    def _to_search_result(self, point: models.ScoredPoint) -> RegulatorySearchResult:
        return RegulatoryChunkPayloadDTO.model_validate(
            point.payload or {}
        ).to_domain(score=point.score)

    def _get_payload_schema_definitions(
        self,
    ) -> dict[str, models.PayloadSchemaType | models.TextIndexParams]:
        return {
            "parent_id": models.PayloadSchemaType.KEYWORD,
            "chunk_status": models.PayloadSchemaType.KEYWORD,
            "document_type": models.PayloadSchemaType.KEYWORD,
            "authority_level": models.PayloadSchemaType.KEYWORD,
            "is_binding": models.PayloadSchemaType.BOOL,
        }

    async def search_regulatory_documents(
        self,
        dense_vector: DenseVector,
        sparse_vector: SparseVector,
        limit: int = 10,
        document_types: Sequence[RegulatoryDocumentType] | None = None,
        is_binding: bool | None = None,
        authority_level: AuthorityLevel | None = None,
        exclude_chunk_ids: Sequence[str] | None = None,
        score_threshold: float | None = None,
    ) -> list[RegulatorySearchResult]:
        """
        Execute hybrid search across regulatory knowledge chunks using RRF fusion.
        """
        try:
            must_conditions: list[models.Condition] = [
                models.FieldCondition(
                    key="chunk_status",
                    match=models.MatchValue(value=ChunkStatus.ACTIVE.value),
                )
            ]

            if document_types:
                must_conditions.append(
                    models.FieldCondition(
                        key="document_type",
                        match=models.MatchAny(any=[d.value for d in document_types]),
                    )
                )

            if is_binding is not None:
                must_conditions.append(
                    models.FieldCondition(
                        key="is_binding",
                        match=models.MatchValue(value=is_binding),
                    )
                )

            if authority_level is not None:
                must_conditions.append(
                    models.FieldCondition(
                        key="authority_level",
                        match=models.MatchValue(value=authority_level.value),
                    )
                )

            must_not_conditions: list[models.Condition] = []
            if exclude_chunk_ids:
                must_not_conditions.append(
                    models.HasIdCondition(has_id=list(exclude_chunk_ids))
                )

            qdrant_filter = models.Filter(
                must=must_conditions,
                must_not=must_not_conditions if must_not_conditions else None,
            )

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
                f"Failed to execute search_regulatory_documents in '{self._collection_name}': {e}",
                exc_info=True,
            )
            raise VectorSearchError(
                f"Failed to execute search_regulatory_documents: {e}"
            ) from e


__all__ = ["QdrantRegulatoryRepository"]
