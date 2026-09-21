from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

from src.application.dtos import RawSuggestionDataDTO


class IHistoricalSuggestionExtractor(ABC):
    """
    Application port for streaming historical suggestions and committee evaluations
    from the legacy data store using offset-based pagination.
    """

    @abstractmethod
    def stream_suggestions(
        self, batch_size: int, start_offset: int = 0
    ) -> AsyncGenerator[list[RawSuggestionDataDTO], None]:
        """
        Stream batches of historical suggestion records starting from `start_offset`.

        Args:
            batch_size: Number of suggestions to fetch per query page.
            start_offset: Zero-based row offset from which to begin streaming.

        Yields:
            List of raw suggestion DTOs for the current page.
        """
        pass


__all__ = ["IHistoricalSuggestionExtractor"]
