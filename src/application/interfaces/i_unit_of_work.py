from __future__ import annotations

from abc import ABC, abstractmethod
from types import TracebackType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.application.interfaces.i_checkpoint_repository import ICheckpointRepository
    from src.application.interfaces.i_skipped_suggestion_repository import (
        ISkippedSuggestionRepository,
    )
    from src.domain.interfaces.i_outbox_repository import IOutboxRepository
    from src.domain.interfaces.i_suggestion_repository import ISuggestionRepository


class IUnitOfWork(ABC):
    """
    Abstract Unit of Work (UoW) port conforming to Cosmic Python & PoEAA.
    Guarantees atomic transaction demarcation across repository operations
    without coupling the application layer to database-specific session types.

    Safe-by-default: Rolls back uncommitted changes upon context exit.
    Mutating operations must explicitly call commit() to persist state.
    """

    async def __aenter__(self) -> IUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.rollback()

    @property
    @abstractmethod
    def suggestions(self) -> ISuggestionRepository:
        """Suggestion repository port bound to this transactional boundary."""
        pass

    @property
    @abstractmethod
    def checkpoints(self) -> ICheckpointRepository:
        """Checkpoint repository port bound to this transactional boundary."""
        pass

    @property
    @abstractmethod
    def skipped_suggestions(self) -> ISkippedSuggestionRepository:
        """Skipped suggestions repository port bound to this transactional boundary."""
        pass

    @property
    @abstractmethod
    def outbox(self) -> IOutboxRepository:
        """Outbox repository port bound to this transactional boundary."""
        pass

    @abstractmethod
    async def commit(self) -> None:
        """Persist all staged mutations within this transactional unit."""
        pass

    @abstractmethod
    async def rollback(self) -> None:
        """Discard all staged mutations within this transactional unit."""
        pass

    @abstractmethod
    async def try_acquire_advisory_lock(self, lock_key: int) -> bool:
        """
        Attempt to acquire a transaction-scoped advisory mutex
        for the given 64-bit integer lock key.

        Args:
            lock_key: Deterministic 64-bit signed integer key.

        Returns:
            True if the lock was successfully acquired for this transaction.
            False if another concurrent transaction currently holds the lock.
        """
        pass


__all__ = ["IUnitOfWork"]
