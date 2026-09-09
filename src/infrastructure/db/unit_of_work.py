from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Any, TypeVar, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.interfaces.i_unit_of_work import IUnitOfWork

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
    ) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._repo_cache: dict[Any, Any] = {}

    @property
    def session(self) -> AsyncSession:
        """Access the active transaction's AsyncSession."""
        if self._session is None:
            raise RuntimeError(
                "Unit of Work is not active. Access session only within an 'async with uow:' context."
            )
        return self._session

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
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        try:
            if exc_type is not None:
                await self.rollback()
            else:
                await self.commit()
        except Exception:
            await self.rollback()
            raise
        finally:
            if self._session is not None:
                await self._session.close()
                self._session = None
                self._repo_cache.clear()


    async def commit(self) -> None:
        if self._session is not None:
            await self._session.commit()

    async def rollback(self) -> None:
        if self._session is not None:
            await self._session.rollback()


__all__ = ["SqlUnitOfWork"]
