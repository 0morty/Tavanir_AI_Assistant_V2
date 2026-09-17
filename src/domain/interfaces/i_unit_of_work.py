from __future__ import annotations

from abc import ABC, abstractmethod
from types import TracebackType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.application.interfaces.i_checkpoint_repository import ICheckpointRepository
    from src.application.interfaces.i_skipped_suggestion_repository import (
        ISkippedSuggestionRepository,
    )
    from src.domain.interfaces.i_suggestion_repository import ISuggestionRepository


class IUnitOfWork(ABC):
    """
    Abstract Unit of Work (UoW) port conforming to Cosmic Python & PoEAA.
    Guarantees atomic transaction demarcation across repository operations
    without coupling the domain layer to database-specific session types.

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

    @abstractmethod
    async def commit(self) -> None:
        """Persist all staged mutations within this transactional unit."""
        pass

    @abstractmethod
    async def rollback(self) -> None:
        """Discard all staged mutations within this transactional unit."""
        pass


__all__ = ["IUnitOfWork"]
