from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.infrastructure.configs.settings import db_settings


def create_db_engine(
    url: str | None = None,
    pool_size: int | None = None,
    max_overflow: int | None = None,
    pool_timeout: float | None = None,
    pool_recycle: int | None = None,
    pool_pre_ping: bool | None = None,
) -> AsyncEngine:
    """
    Constructs an asynchronous SQLAlchemy engine configured for PostgreSQL.
    Default pooling arguments are read from DBSettings.
    """
    engine_url = url or db_settings.POSTGRES_URL
    return create_async_engine(
        engine_url,
        pool_size=pool_size or db_settings.DB_POOL_SIZE,
        max_overflow=max_overflow or db_settings.DB_MAX_OVERFLOW,
        pool_timeout=pool_timeout or db_settings.DB_POOL_TIMEOUT,
        pool_recycle=pool_recycle or db_settings.DB_POOL_RECYCLE,
        pool_pre_ping=(
            db_settings.DB_POOL_PRE_PING if pool_pre_ping is None else pool_pre_ping
        ),
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """
    Constructs an async_sessionmaker bound to the given AsyncEngine.
    expire_on_commit is set to False to allow post-commit entity access.
    """
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


__all__ = ["create_db_engine", "create_session_factory"]
