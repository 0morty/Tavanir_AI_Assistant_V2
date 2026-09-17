from abc import ABC, abstractmethod

from src.application.dtos import CheckpointData


class ICheckpointRepository(ABC):
    """
    Repository port for tracking and persisting ETL batch ingestion watermarks.
    """

    @abstractmethod
    async def get_checkpoint(self, job_name: str) -> CheckpointData | None:
        """
        Fetch the last saved checkpoint for a given ingestion job.
        Returns None if no previous checkpoint exists (fresh run).
        """
        pass

    @abstractmethod
    async def save_checkpoint(
        self, job_name: str, offset: int, last_id: str | None, total_processed: int
    ) -> None:
        """
        Persist or update the watermark progress for a given ingestion job.
        """
        pass

    @abstractmethod
    async def clear_checkpoint(self, job_name: str) -> None:
        """
        Reset/clear the checkpoint watermark for a given ingestion job.
        """
        pass


__all__ = ["ICheckpointRepository"]

