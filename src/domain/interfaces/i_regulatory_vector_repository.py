from abc import abstractmethod
from collections.abc import Sequence

from src.domain.entities import (
    DenseVector,
    RegulatoryChunkMetadata,
    RegulatorySearchResult,
    SparseVector,
)
from src.domain.enums import AuthorityLevel, RegulatoryDocumentType
from src.domain.interfaces.i_vector_repository import IVectorRepository


class IRegulatoryVectorRepository(IVectorRepository[RegulatoryChunkMetadata]):
    """
    Vector repository port for regulatory knowledge (ADR-001, ADR-003).
    Operates on `tavanir_regulatory_knowledge_v1` collection in Qdrant.
    """

    @abstractmethod
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

        Args:
            dense_vector: Semantic query embedding.
            sparse_vector: Lexical query sparse term-weights (BM25).
            limit: Maximum candidate regulatory chunks to return.
            document_types: Optional filter by document type (statute, regulation, etc.).
            is_binding: Optional filter for mandatory laws vs advisory guidance.
            authority_level: Optional filter by authority level (binding vs guidance).
            exclude_chunk_ids: Optional IDs to exclude (used in Hop-1 multi-hop to prevent self-retrieval).
            score_threshold: Minimum similarity score threshold.

        Returns:
            List of scored candidate regulatory chunks (including raw tables in parent_content).

        Raises:
            VectorSearchError: If vector query execution fails.
        """
        pass


__all__ = ["IRegulatoryVectorRepository"]
