from abc import ABC, abstractmethod
from typing import Generic, TypeAlias, TypeVar

from src.domain.entities import (
    Chunk,
    RegulatoryChunkMetadata,
    RegulatoryDocument,
    Suggestion,
    SuggestionChunkMetadata,
)

TDoc = TypeVar("TDoc")
TMetadata = TypeVar("TMetadata")


class IChunkingStrategy(ABC, Generic[TDoc, TMetadata]):
    """
    Abstract Strategy Port for decomposing documents into strongly-typed vector chunks.
    """

    @abstractmethod
    async def chunk(self, document: TDoc) -> list[Chunk[TMetadata]]:
        """
        Decompose a domain document entity into a list of vector search chunks.

        Args:
            document: Domain document entity to decompose.

        Returns:
            List of strongly-typed Chunk objects ready for vector embedding and storage.

        Raises:
            ChunkingError: If chunking fails or invariants are violated.
        """
        pass


# Type-specialized Strategy Ports
ISuggestionChunker: TypeAlias = IChunkingStrategy[Suggestion, SuggestionChunkMetadata]
IRegulatoryChunker: TypeAlias = IChunkingStrategy[
    RegulatoryDocument, RegulatoryChunkMetadata
]

__all__ = [
    "IChunkingStrategy",
    "ISuggestionChunker",
    "IRegulatoryChunker",
]
