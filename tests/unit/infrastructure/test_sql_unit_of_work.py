from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.orm import Mapped, mapped_column
from src.infrastructure.db.repositories.sql.base_sql_repository import BaseSqlRepository
from src.infrastructure.db.sql_models.base import Base
from src.infrastructure.db.unit_of_work import SqlUnitOfWork


# --- Dummy Domain Entity & Model for Unit Testing ---
@dataclasses.dataclass
class DummyEntity:
    id: str
    name: str


class DummyModel(Base):
    __tablename__ = "dummy_test_table"
    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column()


class DummyRepository(BaseSqlRepository[DummyEntity, DummyModel]):
    def __init__(self, session):
        super().__init__(session, DummyEntity, DummyModel)


# --- Tests ---
@pytest.mark.asyncio
async def test_uow_implicit_commit_on_clean_exit():
    mock_session = AsyncMock()
    mock_session_factory = MagicMock(return_value=mock_session)

    uow = SqlUnitOfWork(session_factory=mock_session_factory)

    async with uow:
        assert uow.session is mock_session

    mock_session.commit.assert_awaited_once()
    mock_session.rollback.assert_not_awaited()
    mock_session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_uow_rollback_on_exception():
    mock_session = AsyncMock()
    mock_session_factory = MagicMock(return_value=mock_session)

    uow = SqlUnitOfWork(session_factory=mock_session_factory)

    with pytest.raises(ValueError, match="Something failed"):
        async with uow:
            raise ValueError("Something failed")

    mock_session.rollback.assert_awaited_once()
    mock_session.commit.assert_not_awaited()
    mock_session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_uow_get_repository_lazy_instantiation_and_caching():
    mock_session = AsyncMock()
    mock_session_factory = MagicMock(return_value=mock_session)

    uow = SqlUnitOfWork(session_factory=mock_session_factory)

    # Calling outside of context must fail
    with pytest.raises(RuntimeError, match="Unit of Work is not active"):
        uow.get_repository(DummyRepository)

    async with uow:
        repo1 = uow.get_repository(DummyRepository)
        repo2 = uow.get_repository(DummyRepository)

        assert isinstance(repo1, DummyRepository)
        assert repo1.session is mock_session
        assert repo1 is repo2  # Cached instance within same transaction


@pytest.mark.asyncio
async def test_uow_suggestions_property_uses_injected_factory():
    mock_session = AsyncMock()
    mock_session_factory = MagicMock(return_value=mock_session)
    mock_repo = MagicMock()
    mock_repo_factory = MagicMock(return_value=mock_repo)

    uow = SqlUnitOfWork(
        session_factory=mock_session_factory,
        suggestion_repo_factory=mock_repo_factory,
    )

    async with uow:
        repo = uow.suggestions
        assert repo is mock_repo
        mock_repo_factory.assert_called_once_with(mock_session)


def test_base_sql_repository_mapping():

    mock_session = MagicMock()
    repo = DummyRepository(mock_session)

    # Test _to_model
    entity = DummyEntity(id="d1", name="test_entity")
    model = repo._to_model(entity)
    assert isinstance(model, DummyModel)
    assert model.id == "d1"
    assert model.name == "test_entity"

    # Test _to_entity
    hydrated_entity = repo._to_entity(model)
    assert isinstance(hydrated_entity, DummyEntity)
    assert hydrated_entity.id == "d1"
    assert hydrated_entity.name == "test_entity"
