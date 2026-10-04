"""Restricted, marker-verified database fixtures and rollback-only SQL cleanup."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.database_safety import (
    assert_application_settings,
    verify_postgres_connection,
    verify_qdrant_client,
)


def _require_live_database(request):
    if not request.config.getoption("run_db_tests"):
        pytest.skip(
            "Real database tests require --run-db-tests and dedicated test services"
        )


@pytest_asyncio.fixture
async def postgres_test_database(request, test_database_config):
    _require_live_database(request)
    from src.infrastructure.db import create_db_engine

    from src.infrastructure.configs import settings

    assert_application_settings(settings, test_database_config)
    engine = create_db_engine(test_database_config.postgres_url)
    try:
        async with engine.connect() as connection:
            await verify_postgres_connection(connection, test_database_config)
        yield test_database_config
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(request, test_database_config):
    """Commits release SAVEPOINTs; only fixture rollback ends the outer transaction."""
    _require_live_database(request)
    async with isolated_sql_sessions(test_database_config) as factory:
        yield factory


@asynccontextmanager
async def isolated_sql_sessions(test_database_config):
    """Public test seam for verifying rollback, including explicit repository commits."""
    from src.infrastructure.db import create_db_engine
    from src.infrastructure.db.sql_models import Base

    from src.infrastructure.configs import settings

    assert_application_settings(settings, test_database_config)
    engine = create_db_engine(test_database_config.postgres_url)
    try:
        async with engine.connect() as connection:
            await verify_postgres_connection(connection, test_database_config)
            await (
                connection.rollback()
            )  # End the read-only identity check's implicit transaction.
            transaction = await connection.begin()
            try:
                await connection.run_sync(Base.metadata.create_all)
                yield async_sessionmaker(
                    bind=connection,
                    class_=AsyncSession,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                )
            finally:
                if transaction.is_active:
                    await transaction.rollback()
    finally:
        await engine.dispose()


@asynccontextmanager
async def clean_db_session(factory: async_sessionmaker[AsyncSession]):
    """Compatibility helper: a session scope; never deletes tables or commits cleanup."""
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def qdrant_test_database(request, test_database_config):
    _require_live_database(request)
    from qdrant_client import AsyncQdrantClient

    from src.infrastructure.configs import settings

    assert_application_settings(settings, test_database_config)
    client = AsyncQdrantClient(
        url=test_database_config.qdrant_url, api_key=test_database_config.q_api_key
    )
    try:
        await verify_qdrant_client(client, test_database_config)
        yield test_database_config
    finally:
        await client.close()


@pytest_asyncio.fixture(scope="session")
async def seeded_test_databases(request, test_database_config):
    """Ensures test databases are seeded with the golden benchmark dataset."""
    _require_live_database(request)
    from tests.support.seeding.seeder import TestDatabaseSeeder

    seeder = TestDatabaseSeeder(test_database_config)
    await seeder.seed()
    yield test_database_config

