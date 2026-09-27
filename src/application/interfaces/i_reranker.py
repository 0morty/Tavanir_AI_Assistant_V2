from abc import ABC, abstractmethod
from collections.abc import Sequence

from src.application.dtos import RerankCandidate, RerankedCandidate


class IReranker(ABC):
    """
    Abstract Port for cross-encoder reranking over retrieved candidates.

    Purely decoupled from vector stores, relational databases, and suggestion entities.
    Operates on pre-normalized text inputs.
    """

    @abstractmethod
    async def rerank(
        self,
        normalized_query: str,
        candidates: Sequence[RerankCandidate],
        *,
        top_n: int | None = None,
    ) -> list[RerankedCandidate]:
        """
        Reranks a sequence of candidates against a normalized query.

        Args:
            normalized_query: Pre-normalized query text.
            candidates: Retrieved candidates with baseline RRF ranks and scores.
            top_n: Maximum candidates to return. Clamped gracefully to min(top_n, len(candidates)).
                   If None, returns all candidates reranked.

        Returns:
            Ranked list of candidates sorted by rerank_score descending.
            Ties broken by retrieval_rank ascending.

        Raises:
            ValueError: If normalized_query is blank, duplicate candidate IDs exist, or top_n <= 0.
            RerankerBaseError: Subtypes raised for configuration, network, or upstream errors.
        """
        pass
