from abc import ABC, abstractmethod
from collections.abc import Sequence

from src.domain.entities import SparseVector


class ISparseEmbedder(ABC):
    """
    Abstract interface (Port) for generating sparse vector embeddings (e.g., Persian BM25).

    Sparse embeddings capture lexical/term-based relevance using weighted tokens.
    Because BM25 treats the indexed document corpus differently than the search query
    (especially under Qdrant's models.Modifier.IDF mode), this interface enforces distinct
    methods for documents and queries.
    """

    @abstractmethod
    async def embed_document(self, text: str) -> SparseVector:
        """
        Generate sparse vector embedding for a single document text chunk.
        Applies full Term Frequency (TF) saturation weighting.

        Args:
            text: Input text to embed.

        Returns:
            SparseVector: The structured, deterministically ordered indices and TF values.

        Raises:
            SparseEmbedderError: If embedding generation fails.
        """
        pass

    @abstractmethod
    async def embed_documents(self, texts: Sequence[str]) -> list[SparseVector]:
        """
        Generate sparse embeddings for a batch of document text chunks.

        Args:
            texts: Sequence of input texts.

        Returns:
            list[SparseVector]: List of sparse vectors matching input order.
            Returns an empty list if `texts` is empty.

        Raises:
            SparseEmbedderError: If batch embedding fails.
        """
        pass

    @abstractmethod
    async def embed_query(self, query: str) -> SparseVector:
        """
        Generate sparse vector embedding for a search query.
        Assigns flat weights (1.0) to unique tokens to ensure proper BM25 dot-product
        matching against Qdrant collections configured with models.Modifier.IDF.

        Args:
            query: The user's search query string.

        Returns:
            SparseVector: Structured indices and flat weights (1.0).
            Returns an empty SparseVector if query is empty or whitespace.

        Raises:
            SparseEmbedderError: If query embedding fails.
        """
        pass
