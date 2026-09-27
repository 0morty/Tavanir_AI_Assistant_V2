from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import TypeVar

from src.application.interfaces.i_dense_embedder import IDenseEmbedder
from src.application.interfaces.i_hybrid_embedding_service import (
    IHybridEmbeddingService,
)
from src.application.interfaces.i_sparse_embedder import ISparseEmbedder
from src.domain.entities import Chunk, QueryEmbedding

TMetadata = TypeVar("TMetadata")


class HybridEmbeddingService(IHybridEmbeddingService):
    """
    Application service that orchestrates hybrid (dense + sparse) vector embeddings.
    Extracts text content from domain chunks, executes concurrent embedding via IDenseEmbedder
    and ISparseEmbedder ports, and hydrates vector attributes directly onto domain entities.
    """

    def __init__(
        self,
        dense_embedder: IDenseEmbedder,
        sparse_embedder: ISparseEmbedder,
    ) -> None:
        self._dense_embedder = dense_embedder
        self._sparse_embedder = sparse_embedder

    async def embed_chunks(
        self, chunks: Sequence[Chunk[TMetadata]]
    ) -> list[Chunk[TMetadata]]:
        """
        Concurrently generates dense and sparse vector embeddings for all chunks,
        hydrating their `dense_vector` and `sparse_vector` attributes in place,
        and returning the hydrated list of chunks.
        """
        chunks_list = chunks if isinstance(chunks, list) else list(chunks)
        if not chunks_list:
            return []

        texts = [chunk.content for chunk in chunks_list]

        dense_vectors, sparse_vectors = await asyncio.gather(
            self._dense_embedder.embed_documents(texts),
            self._sparse_embedder.embed_documents(texts),
        )

        for chunk, dense_vec, sparse_vec in zip(
            chunks_list, dense_vectors, sparse_vectors, strict=True
        ):
            chunk.dense_vector = dense_vec
            chunk.sparse_vector = sparse_vec

        return chunks_list

    async def embed_query(self, query: str) -> QueryEmbedding:
        """
        Concurrently generates dense and sparse vector embeddings for a search query.
        """
        dense_vector, sparse_vector = await asyncio.gather(
            self._dense_embedder.embed_query(query),
            self._sparse_embedder.embed_query(query),
        )

        return QueryEmbedding(
            text=query,
            dense_vector=dense_vector,
            sparse_vector=sparse_vector,
        )


ChunkEmbeddingService = HybridEmbeddingService

__all__ = ["HybridEmbeddingService", "ChunkEmbeddingService"]
