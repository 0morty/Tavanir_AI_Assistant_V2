from abc import ABC, abstractmethod
from collections.abc import Sequence


class IDenseEmbedder(ABC):
    """
    Abstract interface (Port) for generating dense vector embeddings.

    This service operates purely on strings and mathematical vectors,
    remaining completely decoupled from domain entities.
    """

    @property
    @abstractmethod
    def embedding_dimension(self) -> int:
        """
        Returns the dimensional size of the vectors produced by this embedder
        (e.g., 768, 1024, 1536). Used for Vector DB collection validation.
        """
        pass

    @abstractmethod
    async def embed_documents(
        self, texts: Sequence[str], truncate: bool = True
    ) -> list[list[float]]:
        """
        Generates embeddings for a batch of document texts.

        Args:
            texts: A sequence of raw strings to be embedded.
            truncate: If True, safely truncates texts exceeding the model's context window.

        Returns:
            A list of dense vectors (lists of floats), matching the input order.
            Returns an empty list if `texts` is empty.
        """
        pass

    @abstractmethod
    async def embed_query(self, query: str, truncate: bool = True) -> list[float]:
        """
        Generates an embedding for a search query (Asymmetric Query mode).

        Args:
            query: The user's search query string.
            truncate: If True, safely truncates queries exceeding the model's context window.

        Returns:
            A single dense vector (list of floats).
        """
        pass
