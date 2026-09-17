from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Any, TypeVar, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.interfaces.i_checkpoint_repository import ICheckpointRepository
from src.application.interfaces.i_skipped_suggestion_repository import (
    ISkippedSuggestionRepository,
)
from src.domain.interfaces.i_suggestion_repository import ISuggestionRepository
from src.domain.interfaces.i_unit_of_work import IUnitOfWork
from src.infrastructure.db.repositories.sql.checkpoint_repository import (
    SqlCheckpointRepository,
)
from src.infrastructure.db.repositories.sql.skipped_suggestion_repository import (
    SqlSkippedSuggestionRepository,
)
from src.infrastructure.db.repositories.sql.suggestion_repository import (
    SqlSuggestionRepository,
)

RepoT = TypeVar("RepoT")


class SqlUnitOfWork(IUnitOfWork):
    """
    SQLAlchemy-backed implementation of the Unit of Work pattern.
    Manages session lifecycle, atomic transaction boundaries, and provides
    dynamic repository resolution with per-transaction caching.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | Callable[[], AsyncSession],
        suggestion_repo_factory: Callable[
            [AsyncSession], ISuggestionRepository
        ] = SqlSuggestionRepository,
        checkpoint_repo_factory: Callable[
            [AsyncSession], ICheckpointRepository
        ] = SqlCheckpointRepository,
        skipped_repo_factory: Callable[
            [AsyncSession], ISkippedSuggestionRepository
        ] = SqlSkippedSuggestionRepository,
    ) -> None:
        self._session_factory = session_factory
        self._suggestion_repo_factory = suggestion_repo_factory
        self._checkpoint_repo_factory = checkpoint_repo_factory
        self._skipped_repo_factory = skipped_repo_factory
        self._session: AsyncSession | None = None
        self._repo_cache: dict[Any, Any] = {}
        self._committed = False

    @property
    def session(self) -> AsyncSession:
        """Access the active transaction's AsyncSession."""
        if self._session is None:
            raise RuntimeError(
                "Unit of Work is not active. Access session only within an 'async with uow:' context."
            )
        return self._session

    @property
    def suggestions(self) -> ISuggestionRepository:
        """Access the suggestion repository bound to the active transaction."""
        return self.get_repository(self._suggestion_repo_factory)

    @property
    def checkpoints(self) -> ICheckpointRepository:
        """Access the checkpoint repository bound to the active transaction."""
        return self.get_repository(self._checkpoint_repo_factory)

    @property
    def skipped_suggestions(self) -> ISkippedSuggestionRepository:
        """Access the skipped suggestions repository bound to the active transaction."""
        return self.get_repository(self._skipped_repo_factory)

    def get_repository(self, repo_cls: Callable[[AsyncSession], RepoT]) -> RepoT:
        """
        Instantiate or return a cached repository bound to the current transaction session.
        Allows repositories to be added to use cases with zero modifications to UoW core.
        """
        if self._session is None:
            raise RuntimeError(
                "Unit of Work is not active. Retrieve repositories only within an 'async with uow:' context."
            )

        if repo_cls not in self._repo_cache:
            self._repo_cache[repo_cls] = repo_cls(self._session)
        return cast(RepoT, self._repo_cache[repo_cls])

    async def __aenter__(self) -> SqlUnitOfWork:
        self._session = self._session_factory()
        self._repo_cache.clear()
        self._committed = False
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        try:
            if exc_type is not None or not self._committed:
                await self.rollback()
        finally:
            if self._session is not None:
                await self._session.close()
                self._session = None
                self._repo_cache.clear()

    async def commit(self) -> None:
        if self._session is not None and not self._committed:
            await self._session.commit()
            self._committed = True

    async def rollback(self) -> None:
        if self._session is not None and not self._committed:
            await self._session.rollback()


__all__ = ["SqlUnitOfWork"]
