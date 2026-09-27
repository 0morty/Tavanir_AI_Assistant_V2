from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TypeVar

from src.domain.entities import Chunk, QueryEmbedding

TMetadata = TypeVar("TMetadata")


class IHybridEmbeddingService(ABC):
    """
    Application port for hybrid (dense + sparse) embedding generation.
    Decouples use cases from raw string extraction, embedder concurrency,
    and vector attachment onto domain entities.
    """

    @abstractmethod
    async def embed_chunks(
        self, chunks: Sequence[Chunk[TMetadata]]
    ) -> list[Chunk[TMetadata]]:
        """
        Concurrently generates dense and sparse vector embeddings for all chunks,
        hydrating their `dense_vector` and `sparse_vector` attributes in place,
        and returning the hydrated list of chunks.

        Args:
            chunks: Sequence of domain chunk entities to embed.

        Returns:
            List of hydrated chunks with attached dense and sparse vectors.
        """
        pass

    @abstractmethod
    async def embed_query(self, query: str) -> QueryEmbedding:
        """
        Concurrently generates dense and sparse vector embeddings for a search query.

        Args:
            query: The user query text.

        Returns:
            Domain QueryEmbedding carrying text, dense vector, and sparse vector.
        """
        pass


# Alias for chunk-centric consumption
IChunkEmbeddingService = IHybridEmbeddingService

__all__ = ["IHybridEmbeddingService", "IChunkEmbeddingService"]
