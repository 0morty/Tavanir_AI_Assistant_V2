from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to sys.path to enable absolute imports
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from qdrant_client import AsyncQdrantClient
from src.containers import Container
from src.infrastructure.configs.settings import qdrant_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("provision_qdrant")


async def wait_for_qdrant_ready(
    client: AsyncQdrantClient, max_retries: int = 10, delay: float = 2.0
) -> None:
    """Poll Qdrant health until the cluster is ready or max retries are exceeded."""
    for attempt in range(1, max_retries + 1):
        try:
            await client.get_collections()
            logger.info(
                f"Successfully connected to Qdrant at {qdrant_settings.QDRANT_HOST}:{qdrant_settings.QDRANT_PORT}"
            )
            return
        except Exception as e:
            logger.warning(
                f"Attempt {attempt}/{max_retries}: Qdrant not ready yet ({e}). Retrying in {delay}s..."
            )
            await asyncio.sleep(delay)

    raise ConnectionError(
        f"Failed to connect to Qdrant at {qdrant_settings.QDRANT_HOST}:{qdrant_settings.QDRANT_PORT} "
        f"after {max_retries} attempts."
    )


async def main() -> None:
    logger.info("Starting Qdrant vector database provisioning...")
    logger.info(
        f"Target endpoint: {qdrant_settings.QDRANT_HOST}:{qdrant_settings.QDRANT_PORT} "
        f"(gRPC: {qdrant_settings.QDRANT_GRPC_PORT}, API Key configured: {bool(qdrant_settings.QDRANT_API_KEY)})"
    )

    container = Container()
    client = container.qdrant_client()
    try:
        await wait_for_qdrant_ready(client)

        # 1. ADR-001 & ADR-002: Historical Suggestions Collection
        suggestion_repo = container.suggestion_vector_repository()
        logger.info(
            f"Provisioning collection '{qdrant_settings.QDRANT_SUGGESTION_COLLECTION}' via {type(suggestion_repo).__name__}..."
        )
        await suggestion_repo.provision_collection()

        # 2. ADR-001 & ADR-003: Regulatory Knowledge Collection
        regulatory_repo = container.regulatory_vector_repository()
        logger.info(
            f"Provisioning collection '{qdrant_settings.QDRANT_REGULATORY_COLLECTION}' via {type(regulatory_repo).__name__}..."
        )
        await regulatory_repo.provision_collection()

        logger.info(
            "All Qdrant collections and payload indexes provisioned successfully!"
        )

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
