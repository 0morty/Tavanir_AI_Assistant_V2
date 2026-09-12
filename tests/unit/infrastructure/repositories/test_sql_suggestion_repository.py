from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.infrastructure.configs.settings import db_settings
from src.infrastructure.db import create_db_engine, create_session_factory
from src.infrastructure.db.repositories.sql.suggestion_repository import (
    SqlSuggestionRepository,
)
from src.infrastructure.db.sql_models.base import Base
from src.infrastructure.db.unit_of_work import SqlUnitOfWork

from src.domain.entities import (
    CommitteeEvaluation,
    ShamsiDate,
    Suggestion,
    SuggestionContent,
)
from src.domain.enums import SuggestionStatus


@pytest.fixture
def session_factory() -> async_sessionmaker[AsyncSession]:
    """Create session factory bound to PostgreSQL engine."""
    engine = create_db_engine(db_settings.POSTGRES_URL)
    return create_session_factory(engine)


@asynccontextmanager
async def clean_db_session(session_factory: async_sessionmaker[AsyncSession]):
    """Async context manager that ensures table schema exists and cleans data."""
    async with session_factory() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)
        await session.execute(text("DELETE FROM suggestions;"))
        await session.commit()

    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.execute(text("DELETE FROM suggestions;"))
            await session.commit()


def _create_sample_suggestion(
    suggestion_id: str = "SUG-TEST-001",
    status: SuggestionStatus = SuggestionStatus.APPROVED,
    title: str = "بهینه‌سازی شبکه فوق توزیع",
    shamsi_date: str | None = "1402/08/15",
) -> Suggestion:
    return Suggestion(
        id=suggestion_id,
        content=SuggestionContent(
            title=title,
            problem="افت ولتاژ در ساعات پیک بار در پست انتقال",
            solution="نصب بانک خازنی هوشمند و کنترل خودکار تپ چنجر",
        ),
        evaluation=CommitteeEvaluation(
            status=status,
            scrutiny="بررسی فنی توسط کمیته تخصصی انتقال تایید گردید",
            description="مصوبه شماره ۲۳۸ مورخ ۱۴۰۲/۰۸/۱۰",
        ),
        date=ShamsiDate(shamsi_date) if shamsi_date else None,
        context_title="معاونت انتقال و تجارت خارجی",
    )


# --- Mapping Tests (Pure Unit Tests, No DB needed) ---


def test_mapper_roundtrip():
    mock_session = MagicMock()
    repo = SqlSuggestionRepository(session=mock_session)
    original = _create_sample_suggestion()

    model = repo._to_model(original)
    assert model.id == original.id
    assert model.title == original.content.title
    assert model.problem == original.content.problem
    assert model.solution == original.content.solution
    assert model.status_id == original.evaluation.status.status_id
    assert model.scrutiny == original.evaluation.scrutiny
    assert model.description == original.evaluation.description
    assert model.shamsi_date == str(original.date)
    assert model.context_title == original.context_title

    hydrated = repo._to_entity(model)
    assert hydrated.id == original.id
    assert hydrated.content == original.content
    assert hydrated.evaluation == original.evaluation
    assert hydrated.date == original.date
    assert hydrated.context_title == original.context_title


def test_mapper_with_nullable_fields():
    mock_session = MagicMock()
    repo = SqlSuggestionRepository(session=mock_session)
    minimal_suggestion = Suggestion(
        id="SUG-MINIMAL",
        content=SuggestionContent(
            title="عنوان بدون شرح مشکل و راهکار",
            problem=None,
            solution=None,
        ),
        evaluation=CommitteeEvaluation(
            status=SuggestionStatus.NOT_ACCEPTED,
            scrutiny=None,
            description=None,
        ),
        date=None,
        context_title=None,
    )

    model = repo._to_model(minimal_suggestion)
    assert model.problem is None
    assert model.solution is None
    assert model.scrutiny is None
    assert model.description is None
    assert model.shamsi_date is None
    assert model.context_title is None

    hydrated = repo._to_entity(model)
    assert hydrated.id == "SUG-MINIMAL"
    assert hydrated.content.problem is None
    assert hydrated.content.solution is None
    assert hydrated.evaluation.status == SuggestionStatus.NOT_ACCEPTED
    assert hydrated.date is None
    assert hydrated.context_title is None


# --- PostgreSQL Repository Tests ---


@pytest.mark.asyncio
async def test_save_and_get_by_id(session_factory: async_sessionmaker[AsyncSession]):
    async with clean_db_session(session_factory) as db_session:
        repo = SqlSuggestionRepository(session=db_session)
        suggestion = _create_sample_suggestion("SUG-001")

        await repo.save(suggestion)
        await db_session.commit()

        retrieved = await repo.get_by_id("SUG-001")
        assert retrieved is not None
        assert retrieved.id == "SUG-001"
        assert retrieved.content.title == suggestion.content.title
        assert retrieved.content.problem == suggestion.content.problem
        assert retrieved.content.solution == suggestion.content.solution
        assert retrieved.evaluation.status == SuggestionStatus.APPROVED
        assert retrieved.date == suggestion.date
        assert retrieved.context_title == "معاونت انتقال و تجارت خارجی"


@pytest.mark.asyncio
async def test_get_by_id_not_found(session_factory: async_sessionmaker[AsyncSession]):
    async with clean_db_session(session_factory) as db_session:
        repo = SqlSuggestionRepository(session=db_session)
        result = await repo.get_by_id("NON-EXISTENT-ID")
        assert result is None


@pytest.mark.asyncio
async def test_save_upsert_existing(session_factory: async_sessionmaker[AsyncSession]):
    async with clean_db_session(session_factory) as db_session:
        repo = SqlSuggestionRepository(session=db_session)
        suggestion = _create_sample_suggestion("SUG-UPSERT")

        await repo.save(suggestion)
        await db_session.commit()

        # Update fields and re-save (Upsert should update in-place without duplicate error)
        updated_suggestion = Suggestion(
            id="SUG-UPSERT",
            content=SuggestionContent(
                title="عنوان ویرایش شده",
                problem="مشکل به روز شده",
                solution="راهکار نهایی",
            ),
            evaluation=CommitteeEvaluation(
                status=SuggestionStatus.EXECUTED,
                scrutiny="تایید نهایی پس از تست میدانی",
                description="مصوبه اجرایی",
            ),
            date=ShamsiDate("1403/01/10"),
            context_title="امور دیسپاچینگ ملی",
        )

        await repo.save(updated_suggestion)
        await db_session.commit()

        retrieved = await repo.get_by_id("SUG-UPSERT")
        assert retrieved is not None
        assert retrieved.content.title == "عنوان ویرایش شده"
        assert retrieved.evaluation.status == SuggestionStatus.EXECUTED
        assert str(retrieved.date) == "1403/01/10"
        assert retrieved.context_title == "امور دیسپاچینگ ملی"


@pytest.mark.asyncio
async def test_save_batch_and_get_by_ids(
    session_factory: async_sessionmaker[AsyncSession],
):
    async with clean_db_session(session_factory) as db_session:
        repo = SqlSuggestionRepository(session=db_session)
        suggestions = [
            _create_sample_suggestion(f"BATCH-{i}", status=SuggestionStatus.PENDING)
            for i in range(1, 6)
        ]

        await repo.save_batch(suggestions)
        await db_session.commit()

        # Batch retrieve subset preserving order
        requested_ids = ["BATCH-4", "BATCH-2", "BATCH-99"]
        hydrated = await repo.get_by_ids(requested_ids)

        assert len(hydrated) == 2
        assert hydrated[0].id == "BATCH-4"
        assert hydrated[1].id == "BATCH-2"

        # Empty list handling
        empty_result = await repo.get_by_ids([])
        assert empty_result == []


@pytest.mark.asyncio
async def test_delete(session_factory: async_sessionmaker[AsyncSession]):
    async with clean_db_session(session_factory) as db_session:
        repo = SqlSuggestionRepository(session=db_session)
        suggestion = _create_sample_suggestion("SUG-DEL")

        await repo.save(suggestion)
        await db_session.commit()

        assert await repo.get_by_id("SUG-DEL") is not None

        await repo.delete("SUG-DEL")
        await db_session.commit()

        assert await repo.get_by_id("SUG-DEL") is None


@pytest.mark.asyncio
async def test_uow_integration(session_factory: async_sessionmaker[AsyncSession]):
    async with clean_db_session(session_factory):
        pass  # Just ensure table is created and empty

    uow = SqlUnitOfWork(session_factory=session_factory)
    suggestion = _create_sample_suggestion("UOW-001")

    # Successful transactional commit via uow.suggestions
    async with uow:
        await uow.suggestions.save(suggestion)

    # Verify persistence in separate session
    async with session_factory() as session:
        repo = SqlSuggestionRepository(session=session)
        persisted = await repo.get_by_id("UOW-001")
        assert persisted is not None
        assert persisted.id == "UOW-001"

    # Transactional rollback on exception
    with pytest.raises(RuntimeError, match="Rollback trigger"):
        async with uow:
            await uow.suggestions.save(_create_sample_suggestion("UOW-ROLLBACK"))
            raise RuntimeError("Rollback trigger")

    async with session_factory() as session:
        repo = SqlSuggestionRepository(session=session)
        assert await repo.get_by_id("UOW-ROLLBACK") is None
