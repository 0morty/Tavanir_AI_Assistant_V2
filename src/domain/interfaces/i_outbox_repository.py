from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from src.domain.entities import OutboxEvent
from src.domain.enums import OutboxEventStatus


class IOutboxRepository(ABC):
    """
    Port for transactional outbox persistence and status lifecycle management.
    """

    @abstractmethod
    async def append(self, event: OutboxEvent) -> None:
        """Appends a new outbox event to the ledger within the current transaction."""
        pass

    @abstractmethod
    async def get_by_id(self, event_id: UUID) -> OutboxEvent | None:
        """Fetches an outbox event by ID without locking."""
        pass

    @abstractmethod
    async def get_for_processing(self, event_id: UUID) -> OutboxEvent | None:
        """
        Attempts to claim an outbox event for processing using row-level locking
        (FOR UPDATE SKIP LOCKED).
        """
        pass

    @abstractmethod
    async def update_status(
        self,
        event_id: UUID,
        status: OutboxEventStatus | str,
        error: str | None = None,
        retry_count: int | None = None,
    ) -> None:
        """Updates the status, last_error, retry_count, and processed_at timestamps."""
        pass

    @abstractmethod
    async def fetch_stale_events(
        self, stuck_before: datetime, limit: int = 100
    ) -> list[OutboxEvent]:
        """Fetches events stuck in 'PROCESSING' whose lock has expired."""
        pass

    @abstractmethod
    async def fetch_pending_events(
        self, created_before: datetime, limit: int = 100
    ) -> list[OutboxEvent]:
        """Fetches un-enqueued events in 'PENDING' state older than threshold."""
        pass

    @abstractmethod
    async def fetch_failed_for_retry(
        self, created_after: datetime, max_retries: int = 20, limit: int = 100
    ) -> list[OutboxEvent]:
        """Fetches 'FAILED' events eligible for extended outage retry."""
        pass

    @abstractmethod
    async def prune_completed(self, before: datetime) -> int:
        """Prunes 'COMPLETED' and 'SUPERSEDED' events older than given timestamp."""
        pass


__all__ = ["IOutboxRepository"]
