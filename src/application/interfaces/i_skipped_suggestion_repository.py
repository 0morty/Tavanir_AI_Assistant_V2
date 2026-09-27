from abc import ABC, abstractmethod
from collections.abc import Sequence

from src.application.dtos import SkippedRecordDTO


class ISkippedSuggestionRepository(ABC):
    """
    Repository port for persisting audit records of corrupted or invalid
    historical suggestions skipped during ETL ingestion.
    """

    @abstractmethod
    async def save_batch(self, skipped_records: Sequence[SkippedRecordDTO]) -> None:
        """
        Batch persist skipped suggestion audit records.
        """
        pass


__all__ = ["ISkippedSuggestionRepository"]
