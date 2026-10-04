from __future__ import annotations

from abc import ABC, abstractmethod

from src.application.interfaces.i_unit_of_work import IUnitOfWork
from src.domain.entities import OutboxEvent


class IOutboxEventHandler(ABC):
    """Port for single-purpose projection strategies handling specific outbox event types."""

    @abstractmethod
    async def handle(self, event: OutboxEvent, uow: IUnitOfWork) -> None:
        """Executes the projection strategy for a specific outbox event."""
        pass


__all__ = ["IOutboxEventHandler"]
