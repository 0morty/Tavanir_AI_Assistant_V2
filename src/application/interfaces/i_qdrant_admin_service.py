from __future__ import annotations

from abc import ABC, abstractmethod


class IQdrantAdminService(ABC):
    """
    Administrative port for Qdrant cluster, collection lifecycle, and optimizer operations.
    Decouples operational management from query and CLI presentation layers.
    """

    @abstractmethod
    async def wait_until_ready(self, max_retries: int = 10, delay: float = 2.0) -> None:
        """
        Poll Qdrant cluster readiness until reachable or max retries exceeded.

        Raises:
            ConnectionError: If the cluster cannot be reached within max_retries attempts.
        """
        pass

    @abstractmethod
    async def delete_collection_if_exists(self, collection_name: str) -> None:
        """
        Idempotently delete a collection if it currently exists on the cluster.
        """
        pass

    @abstractmethod
    async def set_indexing_threshold(
        self, collection_name: str, threshold: int
    ) -> None:
        """
        Configure optimizer indexing_threshold for the collection.
        Pass threshold=0 to disable indexing during bulk ingestion for maximum throughput.
        Pass threshold=20000 (or default) to re-enable HNSW indexing post-ingestion.
        """
        pass

    @abstractmethod
    async def wait_for_indexing_settled(
        self, collection_name: str, max_checks: int = 60, interval: float = 2.0
    ) -> None:
        """
        Poll collection status until status is GREEN and background optimizers finish.
        """
        pass

    @abstractmethod
    async def switch_alias(self, alias_name: str, target_collection: str) -> None:
        """
        Atomically bind or point a search alias to the target physical collection (ADR-001).
        If the alias already exists on another collection, it is atomically rerouted.
        """
        pass


__all__ = ["IQdrantAdminService"]
