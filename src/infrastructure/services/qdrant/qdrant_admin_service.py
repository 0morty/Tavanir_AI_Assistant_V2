from __future__ import annotations

import asyncio

import structlog
from qdrant_client import AsyncQdrantClient, models

from src.application.interfaces.i_qdrant_admin_service import IQdrantAdminService

logger = structlog.get_logger(__name__)


class QdrantAdminService(IQdrantAdminService):
    """
    Qdrant implementation of cluster and collection administrative operations.
    Encapsulates low-level driver calls, optimizer configurations, and atomic alias cutover (ADR-001).
    """

    def __init__(self, client: AsyncQdrantClient) -> None:
        self._client = client

    async def wait_until_ready(self, max_retries: int = 10, delay: float = 2.0) -> None:
        """
        Poll Qdrant cluster readiness until reachable or max retries exceeded.
        """
        for attempt in range(1, max_retries + 1):
            try:
                await self._client.get_collections()
                await logger.ainfo("qdrant_cluster_ready", attempt=attempt)
                return
            except Exception as e:
                await logger.awarning(
                    "qdrant_not_ready_yet",
                    attempt=attempt,
                    max_retries=max_retries,
                    error=str(e),
                )
                await asyncio.sleep(delay)

        raise ConnectionError(
            f"Failed to connect to Qdrant cluster after {max_retries} attempts."
        )

    async def delete_collection_if_exists(self, collection_name: str) -> None:
        """
        Idempotently delete a collection if it exists on the cluster.
        """
        if await self._client.collection_exists(collection_name):
            await logger.ainfo("deleting_qdrant_collection", collection=collection_name)
            await self._client.delete_collection(collection_name)
            await logger.ainfo("deleted_qdrant_collection", collection=collection_name)

    async def set_indexing_threshold(
        self, collection_name: str, threshold: int
    ) -> None:
        """
        Configure optimizer indexing_threshold for the collection.
        """
        await logger.ainfo(
            "updating_qdrant_indexing_threshold",
            collection=collection_name,
            threshold=threshold,
        )
        await self._client.update_collection(
            collection_name=collection_name,
            optimizer_config=models.OptimizersConfigDiff(indexing_threshold=threshold),
        )

    async def wait_for_indexing_settled(
        self, collection_name: str, max_checks: int = 60, interval: float = 2.0
    ) -> None:
        """
        Poll collection status until status is GREEN and background optimizers finish.
        """
        await logger.ainfo(
            "waiting_for_qdrant_indexing_settled", collection=collection_name
        )
        for check in range(1, max_checks + 1):
            info = await self._client.get_collection(collection_name)
            status_str = str(getattr(info, "status", "")).lower()
            opt_status_str = str(getattr(info, "optimizer_status", "")).lower()
            if "green" in status_str and (
                "ok" in opt_status_str or not getattr(info, "optimizer_status", None)
            ):
                await logger.ainfo(
                    "qdrant_indexing_settled",
                    collection=collection_name,
                    status=status_str,
                    optimizer_status=opt_status_str,
                    checks=check,
                )
                return
            await asyncio.sleep(interval)

        await logger.awarning(
            "qdrant_indexing_settle_timeout",
            collection=collection_name,
            max_checks=max_checks,
        )

    async def switch_alias(self, alias_name: str, target_collection: str) -> None:
        """
        Atomically points alias_name to target_collection.
        """
        try:
            aliases_response = await self._client.get_aliases()
            existing_alias_names = {a.alias_name for a in aliases_response.aliases}

            operations: list[models.AliasOperations] = []

            if alias_name in existing_alias_names:
                operations.append(
                    models.DeleteAliasOperation(
                        delete_alias=models.DeleteAlias(alias_name=alias_name)
                    )
                )

            operations.append(
                models.CreateAliasOperation(
                    create_alias=models.CreateAlias(
                        collection_name=target_collection, alias_name=alias_name
                    )
                )
            )

            await self._client.update_collection_aliases(
                change_aliases_operations=operations
            )
            await logger.ainfo(
                "qdrant_alias_updated",
                alias=alias_name,
                target_collection=target_collection,
            )
        except Exception as e:
            await logger.aerror(
                "qdrant_alias_update_failed",
                alias=alias_name,
                target_collection=target_collection,
                error=str(e),
                exc_info=True,
            )
            raise


__all__ = ["QdrantAdminService"]
