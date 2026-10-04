"""Real Postgres checks for non-destructive fixture cleanup and role restrictions."""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.database_fixtures import clean_db_session, isolated_sql_sessions
from tests.database_safety import verify_postgres_connection

pytestmark = [pytest.mark.db, pytest.mark.asyncio, pytest.mark.usefixtures("postgres_test_database")]


async def _insert(connection, identifier):
    await connection.execute(text("""
        INSERT INTO suggestions (id, title, problem, solution, status_id)
        VALUES (:id, 'protected test content', 'test problem', 'test solution', 3)
    """), {"id": identifier})


@pytest.mark.parametrize("abort", [False, True], ids=["normal-exit", "exception-exit"])
async def test_fixture_commits_are_rolled_back_and_unrelated_rows_survive(test_database_config, abort):
    from src.infrastructure.db import create_db_engine
    config = test_database_config
    engine = create_db_engine(config.postgres_url)
    sentinel = "test-protected-" + uuid4().hex
    temporary = "test-rollback-" + uuid4().hex
    try:
        async with engine.begin() as connection:
            await verify_postgres_connection(connection, config)
            await _insert(connection, sentinel)
        async with engine.connect() as connection:
            original = (await connection.execute(text("SELECT * FROM suggestions WHERE id=:id"), {"id": sentinel})).mappings().one()

        async def exercise():
            async with isolated_sql_sessions(config) as factory:
                async with clean_db_session(factory) as session:
                    await _insert(session, temporary)
                    await session.commit()  # The behavior that formerly escaped test cleanup.
                async with clean_db_session(factory) as session:
                    assert await session.scalar(text("SELECT count(*) FROM suggestions WHERE id=:id"), {"id": temporary}) == 1
                    assert await session.scalar(text("SELECT count(*) FROM suggestions WHERE id=:id"), {"id": sentinel}) == 1
                async with engine.connect() as independent:
                    assert await independent.scalar(text("SELECT count(*) FROM suggestions WHERE id=:id"), {"id": temporary}) == 0
                if abort:
                    raise RuntimeError("simulated failed test after explicit commit")
        if abort:
            with pytest.raises(RuntimeError, match="simulated failed test"):
                await exercise()
        else:
            await exercise()
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT count(*) FROM suggestions WHERE id=:id"), {"id": temporary}) == 0
            after = (await connection.execute(text("SELECT * FROM suggestions WHERE id=:id"), {"id": sentinel})).mappings().one()
            assert dict(after) == dict(original)
    finally:
        # Exact owned IDs only, after the identity guard above. No table-wide cleanup.
        async with engine.begin() as connection:
            await verify_postgres_connection(connection, config)
            await connection.execute(text("DELETE FROM suggestions WHERE id IN (:sentinel, :temporary)"),
                                     {"sentinel": sentinel, "temporary": temporary})
        await engine.dispose()


async def test_restricted_test_role_cannot_rewrite_environment_marker(test_database_config):
    from src.infrastructure.db import create_db_engine
    engine = create_db_engine(test_database_config.postgres_url)
    try:
        async with engine.connect() as connection:
            await verify_postgres_connection(connection, test_database_config)
            await connection.rollback()
            with pytest.raises(DBAPIError):
                await connection.execute(text("UPDATE public.test_environment_guard SET environment_id='invalid'"))
            await connection.rollback()
            await verify_postgres_connection(connection, test_database_config)
    finally:
        await engine.dispose()
