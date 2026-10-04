from __future__ import annotations

import pytest
from sqlalchemy import text
from src.containers import Container
from src.infrastructure.db.repositories.sql.base_sql_repository import BaseSqlRepository
from src.infrastructure.db.unit_of_work import SqlUnitOfWork

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("postgres_test_database")]


class IntegrationTestRepo(BaseSqlRepository):
    async def ping(self) -> int:
        result = await self.session.execute(text("SELECT 42"))
        return result.scalar_one()


@pytest.mark.asyncio
async def test_live_postgres_unit_of_work_lifecycle():
    container = Container()
    uow = container.unit_of_work()
    assert isinstance(uow, SqlUnitOfWork)


    # 1. Test clean execution and implicit commit on live Postgres
    async with uow:
        result = await uow.session.execute(text("SELECT 1"))
        assert result.scalar_one() == 1

        # 2. Test dynamic get_repository bound to live session
        repo = uow.get_repository(IntegrationTestRepo)
        assert isinstance(repo, IntegrationTestRepo)
        val = await repo.ping()
        assert val == 42


@pytest.mark.asyncio
async def test_live_postgres_unit_of_work_rollback_on_error():
    container = Container()
    uow = container.unit_of_work()
    assert isinstance(uow, SqlUnitOfWork)


    with pytest.raises(RuntimeError, match="Simulated failure"):
        async with uow:
            await uow.session.execute(text("SELECT 1"))
            raise RuntimeError("Simulated failure")

    # Verify session was closed and reset
    with pytest.raises(RuntimeError, match="Unit of Work is not active"):
        _ = uow.session
