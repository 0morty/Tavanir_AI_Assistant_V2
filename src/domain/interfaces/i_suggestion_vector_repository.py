from abc import abstractmethod
from collections.abc import Sequence

from src.domain.entities import (
    DenseVector,
    SparseVector,
    SuggestionChunkMetadata,
    SuggestionSearchResult,
)
from src.domain.enums import SuggestionChunkType, SuggestionStatus
from src.domain.interfaces.i_vector_repository import IVectorRepository


class ISuggestionVectorRepository(IVectorRepository[SuggestionChunkMetadata]):
    """
    Vector repository port for historical employee suggestions (ADR-001, ADR-002).
    Operates on `tavanir_suggestion_v1` collection in Qdrant.
    """

    @abstractmethod
    async def search_suggestions(
        self,
        dense_vector: DenseVector,
        sparse_vector: SparseVector,
        limit: int = 10,
        chunk_types: Sequence[SuggestionChunkType] | None = None,
        statuses: Sequence[SuggestionStatus] | None = None,
        context_title: str | None = None,
        score_threshold: float | None = None,
    ) -> list[SuggestionSearchResult]:
        """
        Execute hybrid search across suggestion child chunks using RRF fusion.

        Args:
            dense_vector: Semantic query embedding.
            sparse_vector: Lexical query sparse term-weights (BM25).
            limit: Maximum candidate child chunks to return.
            chunk_types: Optional filter on chunk types (e.g. [SOLUTION] for duplicate detection).
            statuses: Optional filter on committee evaluation statuses (e.g. [APPROVED, EXECUTED]).
            context_title: Optional filter on organizational department / context.
            score_threshold: Minimum similarity score threshold.

        Returns:
            List of scored candidate suggestion chunks.

        Raises:
            VectorSearchError: If vector query execution fails.
        """
        pass


__all__ = ["ISuggestionVectorRepository"]
