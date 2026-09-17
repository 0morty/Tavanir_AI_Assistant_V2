from __future__ import annotations

from collections.abc import Sequence

import pytest
from src.application.interfaces.i_dense_embedder import IDenseEmbedder
from src.application.interfaces.i_sparse_embedder import ISparseEmbedder
from src.application.services.hybrid_embedding_service import (
    ChunkEmbeddingService,
    HybridEmbeddingService,
)

from src.application.exceptions import EmbedderAPIError, SparseEmbedderError
from src.domain.entities import (
    Chunk,
    QueryEmbedding,
    SparseVector,
    SuggestionChunkMetadata,
)
from src.domain.enums import SuggestionChunkType, SuggestionStatus


class FakeDenseEmbedder(IDenseEmbedder):
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.embedded_docs: list[Sequence[str]] = []
        self.embedded_queries: list[str] = []

    @property
    def embedding_dimension(self) -> int:
        return 768

    async def embed_documents(
        self, texts: Sequence[str], truncate: bool = True
    ) -> list[list[float]]:
        if self.should_fail:
            raise EmbedderAPIError("Dense API failed")
        self.embedded_docs.append(texts)
        return [[0.1 * (i + 1)] * 768 for i in range(len(texts))]

    async def embed_query(self, query: str, truncate: bool = True) -> list[float]:
        if self.should_fail:
            raise EmbedderAPIError("Dense query API failed")
        self.embedded_queries.append(query)
        return [0.9] * 768


class FakeSparseEmbedder(ISparseEmbedder):
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.embedded_docs: list[Sequence[str]] = []
        self.embedded_queries: list[str] = []

    async def embed_document(self, text: str) -> SparseVector:
        return SparseVector(indices=[1], values=[1.0])

    async def embed_documents(self, texts: Sequence[str]) -> list[SparseVector]:
        if self.should_fail:
            raise SparseEmbedderError("Sparse embedding failed")
        self.embedded_docs.append(texts)
        return [
            SparseVector(indices=[i + 1], values=[1.0 + i]) for i in range(len(texts))
        ]

    async def embed_query(self, query: str) -> SparseVector:
        if self.should_fail:
            raise SparseEmbedderError("Sparse query failed")
        self.embedded_queries.append(query)
        return SparseVector(indices=[99], values=[2.5])


def _create_sample_chunks() -> list[Chunk[SuggestionChunkMetadata]]:
    return [
        Chunk[SuggestionChunkMetadata](
            chunk_id="chunk-1",
            parent_id="sugg-1",
            content="Title text",
            metadata=SuggestionChunkMetadata(
                chunk_type=SuggestionChunkType.TITLE,
                sub_index=0,
                status=SuggestionStatus.APPROVED,
            ),
        ),
        Chunk[SuggestionChunkMetadata](
            chunk_id="chunk-2",
            parent_id="sugg-1",
            content="Problem text",
            metadata=SuggestionChunkMetadata(
                chunk_type=SuggestionChunkType.PROBLEM,
                sub_index=1,
                status=SuggestionStatus.APPROVED,
            ),
        ),
    ]


@pytest.mark.asyncio
async def test_embed_chunks_success():
    dense = FakeDenseEmbedder()
    sparse = FakeSparseEmbedder()
    service = HybridEmbeddingService(dense_embedder=dense, sparse_embedder=sparse)

    chunks = _create_sample_chunks()
    assert chunks[0].dense_vector is None
    assert chunks[0].sparse_vector is None

    result = await service.embed_chunks(chunks)

    assert len(result) == 2
    assert result == chunks
    assert result[0] is chunks[0]
    assert result[1] is chunks[1]
    assert result[0].dense_vector == [0.1] * 768
    assert result[0].sparse_vector == SparseVector(indices=[1], values=[1.0])
    assert result[1].dense_vector == [0.2] * 768
    assert result[1].sparse_vector == SparseVector(indices=[2], values=[2.0])

    assert len(dense.embedded_docs) == 1
    assert dense.embedded_docs[0] == ["Title text", "Problem text"]
    assert len(sparse.embedded_docs) == 1
    assert sparse.embedded_docs[0] == ["Title text", "Problem text"]


@pytest.mark.asyncio
async def test_embed_chunks_empty():
    dense = FakeDenseEmbedder()
    sparse = FakeSparseEmbedder()
    service = ChunkEmbeddingService(dense_embedder=dense, sparse_embedder=sparse)

    result = await service.embed_chunks([])

    assert result == []
    assert len(dense.embedded_docs) == 0
    assert len(sparse.embedded_docs) == 0


@pytest.mark.asyncio
async def test_embed_chunks_dense_error_propagates():
    dense = FakeDenseEmbedder(should_fail=True)
    sparse = FakeSparseEmbedder()
    service = HybridEmbeddingService(dense_embedder=dense, sparse_embedder=sparse)

    chunks = _create_sample_chunks()
    with pytest.raises(EmbedderAPIError, match="Dense API failed"):
        await service.embed_chunks(chunks)


@pytest.mark.asyncio
async def test_embed_chunks_sparse_error_propagates():
    dense = FakeDenseEmbedder()
    sparse = FakeSparseEmbedder(should_fail=True)
    service = HybridEmbeddingService(dense_embedder=dense, sparse_embedder=sparse)

    chunks = _create_sample_chunks()
    with pytest.raises(SparseEmbedderError, match="Sparse embedding failed"):
        await service.embed_chunks(chunks)


@pytest.mark.asyncio
async def test_embed_query_success():
    dense = FakeDenseEmbedder()
    sparse = FakeSparseEmbedder()
    service = HybridEmbeddingService(dense_embedder=dense, sparse_embedder=sparse)

    query_emb = await service.embed_query("شبکه توزیع برق")

    assert isinstance(query_emb, QueryEmbedding)
    assert query_emb.text == "شبکه توزیع برق"
    assert query_emb.dense_vector == [0.9] * 768
    assert query_emb.sparse_vector == SparseVector(indices=[99], values=[2.5])
    assert dense.embedded_queries == ["شبکه توزیع برق"]
    assert sparse.embedded_queries == ["شبکه توزیع برق"]
