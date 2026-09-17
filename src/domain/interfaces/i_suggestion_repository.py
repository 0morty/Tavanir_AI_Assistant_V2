from abc import ABC, abstractmethod
from collections.abc import Sequence

from src.domain.entities import Suggestion


class ISuggestionRepository(ABC):
    """
    Relational repository port for historical suggestion master entities (PostgreSQL).
    Acts as the authoritative System of Record (ADR-002).
    """

    @abstractmethod
    async def get_by_id(self, suggestion_id: str) -> Suggestion | None:
        """Fetch a single suggestion by its primary key identifier."""
        pass

    @abstractmethod
    async def get_by_ids(self, suggestion_ids: Sequence[str]) -> list[Suggestion]:
        """
        Batch fetch suggestions by their primary key identifiers.
        Essential for on-demand parent hydration after Max-Passage Pooling (MaxP).
        """
        pass

    @abstractmethod
    async def save(self, suggestion: Suggestion) -> None:
        """Persist or update a single suggestion record in SQL."""
        pass

    @abstractmethod
    async def save_batch(self, suggestions: Sequence[Suggestion]) -> None:
        """Batch persist or update multiple suggestion records in SQL."""
        pass

    @abstractmethod
    async def delete(self, suggestion_id: str) -> None:
        """Delete a suggestion record by its identifier."""
        pass

    @abstractmethod
    async def delete_batch(self, suggestion_ids: Sequence[str]) -> None:
        """Batch delete suggestion records by identifiers for compensating rollbacks."""
        pass


__all__ = ["ISuggestionRepository"]
