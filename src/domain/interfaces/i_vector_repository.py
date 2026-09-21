from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Generic, TypeVar

from src.domain.entities import Chunk

TMetadata = TypeVar("TMetadata")


class IVectorRepository(ABC, Generic[TMetadata]):
    """
    Abstract Port for vector database persistence and lifecycle management.

    Handles collection provisioning, chunk upsert, and zero-downtime
    reindexing via staging lifecycles (Write-Before-Delete pattern).
    """

    @abstractmethod
    async def provision_collection(self, dense_dimension: int | None = None) -> None:
        """
        Ensure the vector collection, vector configurations (dense + sparse),
        and payload indexes exist in the vector store.
        """
        pass

    @abstractmethod
    async def upsert_chunk(self, chunk: Chunk[TMetadata]) -> None:
        """
        Persist or update a single chunk in the vector store.

        Raises:
            VectorStorageError: If storage operation fails.
        """
        pass

    @abstractmethod
    async def upsert_chunks_batch(self, chunks: Sequence[Chunk[TMetadata]]) -> None:
        """
        Batch persist or update multiple chunks in the vector store.

        Raises:
            VectorStorageError: If batch storage operation fails.
        """
        pass

    @abstractmethod
    async def delete_chunks_by_parent_id(self, parent_id: str) -> None:
        """
        Delete all vector chunks associated with a specific parent entity.

        Raises:
            VectorStorageError: If deletion fails.
        """
        pass

    @abstractmethod
    async def delete_chunks_by_parent_ids(self, parent_ids: Sequence[str]) -> None:
        """
        Batch delete all vector chunks associated with a list of parent entities.

        Raises:
            VectorStorageError: If deletion fails.
        """
        pass

    @abstractmethod
    async def delete_staging_chunks(self, parent_id: str) -> None:
        """
        Delete staging chunks (chunk_status=STAGING) for a parent entity.

        Raises:
            VectorStorageError: If deletion fails.
        """
        pass

    @abstractmethod
    async def activate_staging_chunks(self, parent_id: str) -> None:
        """
        Execute atomic zero-downtime promotion for a parent entity's chunks:
        1. Demote ACTIVE chunks to DEPRECATED.
        2. Promote STAGING chunks to ACTIVE.

        Raises:
            VectorStorageError: If payload update fails.
        """
        pass

    @abstractmethod
    async def activate_staging_chunks_batch(self, parent_ids: Sequence[str]) -> None:
        """
        Execute atomic zero-downtime promotion for multiple parent entities:
        1. Demote ACTIVE chunks to DEPRECATED.
        2. Promote STAGING chunks to ACTIVE.

        Raises:
            VectorStorageError: If payload update fails.
        """
        pass

    @abstractmethod
    async def delete_deprecated_chunks(self, parent_id: str) -> None:
        """
        Delete deprecated chunks (chunk_status=DEPRECATED) for a parent entity.

        Raises:
            VectorStorageError: If cleanup fails.
        """
        pass

    @abstractmethod
    async def delete_chunks_by_ids(self, chunk_ids: Sequence[str]) -> None:
        """
        Delete an exact list of chunk IDs by point primary key.
        Essential for compensating failed staging batches without touching active chunks.

        Raises:
            VectorStorageError: If deletion fails.
        """
        pass

    @abstractmethod
    async def delete_superseded_chunks(
        self, parent_id: str, active_chunk_ids: Sequence[str]
    ) -> None:
        """
        Delete all chunks for a parent entity that are NOT in the active_chunk_ids list.
        Executes zero-blackout cutover without state-machine race conditions.

        Raises:
            VectorStorageError: If cleanup fails.
        """
        pass


__all__ = ["IVectorRepository"]
