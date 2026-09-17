from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any, TypeVar

import httpx
from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from src.domain.entities import Chunk, SearchResultChunk
from src.domain.enums import ChunkStatus
from src.domain.exceptions import (
    VectorCollectionProvisioningError,
    VectorStorageError,
)
from src.domain.interfaces.i_vector_repository import IVectorRepository

TMetadata = TypeVar("TMetadata")
logger = logging.getLogger(__name__)


class QdrantBaseVectorRepository(IVectorRepository[TMetadata], ABC):
    """
    Abstract Qdrant vector repository implementing core persistence,
    idempotent collection provisioning, and zero-downtime staging lifecycles.
    """

    def __init__(
        self,
        client: AsyncQdrantClient,
        collection_name: str,
        dense_vector_name: str = "dense",
        sparse_vector_name: str = "sparse",
        default_dense_dim: int = 768,
        batch_size: int = 64,
        dense_score_threshold: float | None = None,
        sparse_score_threshold: float | None = None,
        max_retries: int = 3,
        retry_base_delay: float = 0.5,
        retry_max_delay: float = 8.0,
    ) -> None:
        self._client = client
        self._collection_name = collection_name
        self._dense_vector_name = dense_vector_name
        self._sparse_vector_name = sparse_vector_name
        self._default_dense_dim = default_dense_dim
        self._batch_size = batch_size
        self._dense_score_threshold = dense_score_threshold
        self._sparse_score_threshold = sparse_score_threshold
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._retry_max_delay = retry_max_delay

    @property
    def collection_name(self) -> str:
        return self._collection_name

    @abstractmethod
    def _build_payload(self, chunk: Chunk[Any]) -> dict[str, Any]:
        """Serialize domain chunk metadata into a Qdrant-compatible dictionary."""
        pass

    @abstractmethod
    def _to_search_result(
        self, point: models.ScoredPoint
    ) -> SearchResultChunk[TMetadata]:
        """Convert a scored Qdrant point back into a domain SearchResultChunk."""
        pass

    @abstractmethod
    def _get_payload_schema_definitions(
        self,
    ) -> dict[str, models.PayloadSchemaType | models.TextIndexParams]:
        """Return the dictionary of field name to payload index schema for this collection."""
        pass

    def _to_point(self, chunk: Chunk[Any]) -> models.PointStruct:
        """Map domain Chunk to Qdrant PointStruct with named dense and sparse vectors."""
        vectors: dict[str, Any] = {}
        if chunk.dense_vector is not None:
            vectors[self._dense_vector_name] = list(chunk.dense_vector)
        if chunk.sparse_vector is not None:
            vectors[self._sparse_vector_name] = models.SparseVector(
                indices=chunk.sparse_vector.indices,
                values=chunk.sparse_vector.values,
            )

        payload = self._build_payload(chunk)
        return models.PointStruct(
            id=chunk.chunk_id,
            vector=vectors,
            payload=payload,
        )

    async def provision_collection(self, dense_dimension: int | None = None) -> None:
        """
        Idempotently create collection with dense (on-disk) and sparse vectors,
        and verify all required payload indexes.
        """
        dim = dense_dimension or self._default_dense_dim
        try:
            exists = await self._client.collection_exists(self._collection_name)
            if not exists:
                logger.info(
                    f"Creating collection '{self._collection_name}' with on-disk vectors (dim={dim})..."
                )
                await self._client.create_collection(
                    collection_name=self._collection_name,
                    vectors_config={
                        self._dense_vector_name: models.VectorParams(
                            size=dim,
                            distance=models.Distance.COSINE,
                            on_disk=True,
                        )
                    },
                    sparse_vectors_config={
                        self._sparse_vector_name: models.SparseVectorParams(
                            modifier=models.Modifier.IDF
                        )
                    },
                    on_disk_payload=True,
                )
                logger.info(
                    f"Collection '{self._collection_name}' created successfully."
                )
            else:
                logger.debug(
                    f"Collection '{self._collection_name}' already exists. Verifying payload storage and indexes."
                )
                try:
                    await self._client.update_collection(
                        collection_name=self._collection_name,
                        collection_params=models.CollectionParamsDiff(
                            on_disk_payload=True
                        ),
                    )
                except Exception as e:
                    logger.debug(
                        f"Could not update on_disk_payload for '{self._collection_name}': {e}"
                    )

            # Provision payload indexes
            indexes = self._get_payload_schema_definitions()
            for field_name, schema in indexes.items():
                try:
                    await self._client.create_payload_index(
                        collection_name=self._collection_name,
                        field_name=field_name,
                        field_schema=schema,
                    )
                    logger.debug(
                        f"Payload index ensured on '{self._collection_name}.{field_name}'"
                    )
                except UnexpectedResponse as e:
                    # Index exists or non-fatal conflict
                    logger.debug(
                        f"Payload index on '{self._collection_name}.{field_name}' already configured: {e}"
                    )
                except Exception as e:
                    logger.error(
                        f"Error ensuring index '{self._collection_name}.{field_name}': {e}",
                        exc_info=True,
                    )
                    raise

        except Exception as e:
            logger.error(
                f"Failed to provision collection '{self._collection_name}': {e}",
                exc_info=True,
            )
            raise VectorCollectionProvisioningError(
                f"Collection provisioning failed for '{self._collection_name}': {e}"
            ) from e

    async def upsert_chunk(self, chunk: Chunk[Any]) -> None:
        """Persist or update a single chunk in Qdrant."""
        try:
            point = self._to_point(chunk)
            await self._client.upsert(
                collection_name=self._collection_name, points=[point]
            )
            logger.debug(
                f"Upserted chunk '{chunk.chunk_id}' into '{self._collection_name}'"
            )
        except Exception as e:
            logger.error(
                f"Failed to upsert chunk '{chunk.chunk_id}' into '{self._collection_name}': {e}",
                exc_info=True,
            )
            raise VectorStorageError(
                f"Failed to upsert chunk '{chunk.chunk_id}': {e}"
            ) from e

    @staticmethod
    def _is_transient_error(exc: BaseException) -> bool:
        """
        Classify whether an exception during Qdrant operations is transient
        (retried with exponential jitter) or fatal (poison pill / cancellation).
        """
        if isinstance(exc, asyncio.CancelledError):
            return False

        if isinstance(
            exc,
            (
                httpx.ConnectError,
                httpx.TimeoutException,
                httpx.NetworkError,
                ResponseHandlingException,
            ),
        ):
            return True

        if isinstance(exc, UnexpectedResponse):
            # 429: Rate limit, 500/502/503/504: Server / Gateway Error
            return exc.status_code in (429, 500, 502, 503, 504)

        return False

    async def _upsert_slice_with_retry(
        self, points: list[models.PointStruct], slice_idx: int
    ) -> None:
        """Upsert a single batch slice with tenacity exponential backoff and jitter."""
        async for attempt in AsyncRetrying(
            retry=retry_if_exception(self._is_transient_error),
            wait=wait_exponential_jitter(
                initial=self._retry_base_delay,
                max=self._retry_max_delay,
                jitter=1.0,
            ),
            stop=stop_after_attempt(self._max_retries),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        ):
            with attempt:
                await self._client.upsert(
                    collection_name=self._collection_name, points=points
                )

    async def upsert_chunks_batch(self, chunks: Sequence[Chunk[Any]]) -> None:
        """Batch persist or update chunks in Qdrant with chunked slicing and slice-level retries."""
        if not chunks:
            return

        total_chunks = len(chunks)
        try:
            for i in range(0, total_chunks, self._batch_size):
                batch = chunks[i : i + self._batch_size]
                points = [self._to_point(chunk) for chunk in batch]
                slice_idx = (i // self._batch_size) + 1
                await self._upsert_slice_with_retry(points, slice_idx=slice_idx)
            logger.debug(
                f"Successfully upserted batch of {total_chunks} chunks into '{self._collection_name}'"
            )
        except Exception as e:
            logger.error(
                f"Failed to upsert batch into '{self._collection_name}': {e}",
                exc_info=True,
            )
            raise VectorStorageError(
                f"Failed to upsert batch of {total_chunks} chunks into '{self._collection_name}': {e}"
            ) from e

    async def delete_chunks_by_parent_id(self, parent_id: str) -> None:
        """Delete all chunks for a specific parent entity."""
        try:
            qdrant_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="parent_id", match=models.MatchValue(value=parent_id)
                    )
                ]
            )
            await self._client.delete(
                collection_name=self._collection_name,
                points_selector=models.FilterSelector(filter=qdrant_filter),
            )
            logger.debug(
                f"Deleted all chunks for parent_id='{parent_id}' from '{self._collection_name}'"
            )
        except Exception as e:
            logger.error(
                f"Failed to delete chunks for parent_id='{parent_id}' in '{self._collection_name}': {e}",
                exc_info=True,
            )
            raise VectorStorageError(
                f"Failed to delete chunks for parent_id='{parent_id}': {e}"
            ) from e

    async def delete_chunks_by_parent_ids(self, parent_ids: Sequence[str]) -> None:
        """Delete all chunks for a list of parent entities."""
        if not parent_ids:
            return
        try:
            qdrant_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="parent_id", match=models.MatchAny(any=list(parent_ids))
                    )
                ]
            )
            await self._client.delete(
                collection_name=self._collection_name,
                points_selector=models.FilterSelector(filter=qdrant_filter),
            )
            logger.debug(
                f"Deleted all chunks for {len(parent_ids)} parent_ids from '{self._collection_name}'"
            )
        except Exception as e:
            logger.error(
                f"Failed to delete chunks for {len(parent_ids)} parent_ids in '{self._collection_name}': {e}",
                exc_info=True,
            )
            raise VectorStorageError(
                f"Failed to delete chunks for {len(parent_ids)} parent_ids: {e}"
            ) from e

    async def delete_staging_chunks(self, parent_id: str) -> None:
        """Delete staging chunks (chunk_status=STAGING) for a parent entity."""
        try:
            qdrant_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="parent_id", match=models.MatchValue(value=parent_id)
                    ),
                    models.FieldCondition(
                        key="chunk_status",
                        match=models.MatchValue(value=ChunkStatus.STAGING.value),
                    ),
                ]
            )
            await self._client.delete(
                collection_name=self._collection_name,
                points_selector=models.FilterSelector(filter=qdrant_filter),
            )
            logger.debug(
                f"Deleted STAGING chunks for parent_id='{parent_id}' from '{self._collection_name}'"
            )
        except Exception as e:
            logger.error(
                f"Failed to delete STAGING chunks for parent_id='{parent_id}' in '{self._collection_name}': {e}",
                exc_info=True,
            )
            raise VectorStorageError(
                f"Failed to delete staging chunks for parent_id='{parent_id}': {e}"
            ) from e

    async def activate_staging_chunks(self, parent_id: str) -> None:
        """
        Execute atomic zero-downtime promotion for a parent entity:
        1. Demote ACTIVE chunks to DEPRECATED.
        2. Promote STAGING chunks to ACTIVE.
        """
        try:
            # Step 1: Active -> Deprecated
            await self._client.set_payload(
                collection_name=self._collection_name,
                payload={"chunk_status": ChunkStatus.DEPRECATED.value},
                points=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="parent_id", match=models.MatchValue(value=parent_id)
                        ),
                        models.FieldCondition(
                            key="chunk_status",
                            match=models.MatchValue(value=ChunkStatus.ACTIVE.value),
                        ),
                    ]
                ),
            )

            # Step 2: Staging -> Active
            await self._client.set_payload(
                collection_name=self._collection_name,
                payload={"chunk_status": ChunkStatus.ACTIVE.value},
                points=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="parent_id", match=models.MatchValue(value=parent_id)
                        ),
                        models.FieldCondition(
                            key="chunk_status",
                            match=models.MatchValue(value=ChunkStatus.STAGING.value),
                        ),
                    ]
                ),
            )
            logger.debug(
                f"Promoted STAGING chunks to ACTIVE for parent_id='{parent_id}' in '{self._collection_name}'"
            )
        except Exception as e:
            logger.error(
                f"Failed to activate staging chunks for parent_id='{parent_id}' in '{self._collection_name}': {e}",
                exc_info=True,
            )
            raise VectorStorageError(
                f"Failed to activate staging chunks for parent_id='{parent_id}': {e}"
            ) from e

    async def activate_staging_chunks_batch(self, parent_ids: Sequence[str]) -> None:
        """
        Execute atomic zero-downtime promotion for multiple parent entities:
        1. Demote ACTIVE chunks to DEPRECATED.
        2. Promote STAGING chunks to ACTIVE.
        """
        if not parent_ids:
            return
        try:
            # Step 1: Active -> Deprecated
            await self._client.set_payload(
                collection_name=self._collection_name,
                payload={"chunk_status": ChunkStatus.DEPRECATED.value},
                points=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="parent_id", match=models.MatchAny(any=list(parent_ids))
                        ),
                        models.FieldCondition(
                            key="chunk_status",
                            match=models.MatchValue(value=ChunkStatus.ACTIVE.value),
                        ),
                    ]
                ),
            )

            # Step 2: Staging -> Active
            await self._client.set_payload(
                collection_name=self._collection_name,
                payload={"chunk_status": ChunkStatus.ACTIVE.value},
                points=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="parent_id", match=models.MatchAny(any=list(parent_ids))
                        ),
                        models.FieldCondition(
                            key="chunk_status",
                            match=models.MatchValue(value=ChunkStatus.STAGING.value),
                        ),
                    ]
                ),
            )
            logger.debug(
                f"Promoted STAGING chunks to ACTIVE for {len(parent_ids)} parent_ids in '{self._collection_name}'"
            )
        except Exception as e:
            logger.error(
                f"Failed to activate staging chunks for {len(parent_ids)} parent_ids in '{self._collection_name}': {e}",
                exc_info=True,
            )
            raise VectorStorageError(
                f"Failed to activate staging chunks for {len(parent_ids)} parent_ids: {e}"
            ) from e

    async def delete_deprecated_chunks(self, parent_id: str) -> None:
        """Delete deprecated chunks (chunk_status=DEPRECATED) for a parent entity."""
        try:
            qdrant_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="parent_id", match=models.MatchValue(value=parent_id)
                    ),
                    models.FieldCondition(
                        key="chunk_status",
                        match=models.MatchValue(value=ChunkStatus.DEPRECATED.value),
                    ),
                ]
            )
            await self._client.delete(
                collection_name=self._collection_name,
                points_selector=models.FilterSelector(filter=qdrant_filter),
            )
            logger.debug(
                f"Deleted DEPRECATED chunks for parent_id='{parent_id}' from '{self._collection_name}'"
            )
        except Exception as e:
            logger.error(
                f"Failed to delete DEPRECATED chunks for parent_id='{parent_id}' in '{self._collection_name}': {e}",
                exc_info=True,
            )
            raise VectorStorageError(
                f"Failed to delete deprecated chunks for parent_id='{parent_id}': {e}"
            ) from e


__all__ = ["QdrantBaseVectorRepository"]
