from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.infrastructure.db.repositories.sql.suggestion_repository import (
    SqlSuggestionRepository,
)
from src.infrastructure.db.unit_of_work import SqlUnitOfWork
from tests.database_fixtures import clean_db_session

from src.domain.entities import (
    CommitteeEvaluation,
    SecretariatEvaluation,
    ShamsiDate,
    Suggestion,
    SuggestionContent,
)
from src.domain.enums import (
    CommitteeScrutiny,
    SecretariatScrutiny,
    SuggestionStatus,
)
from src.domain.exceptions import SuggestionAlreadyExistsError


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
            scrutiny=CommitteeScrutiny.APPROVED,
            description="مصوبه شماره ۲۳۸ مورخ ۱۴۰۲/۰۸/۱۰",
            scrutiny_id=0,
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
    assert model.committee_scrutiny == "تایید"
    assert model.description == original.evaluation.description
    assert model.shamsi_date == str(original.date)
    assert model.context_title == original.context_title

    hydrated = repo._to_entity(model)
    assert hydrated.id == original.id
    assert hydrated.content == original.content
    assert hydrated.evaluation == original.evaluation
    assert hydrated.date == original.date
    assert hydrated.context_title == original.context_title


def test_mapper_roundtrip_with_secretariat_and_committee_scrutiny():
    mock_session = MagicMock()
    repo = SqlSuggestionRepository(session=mock_session)

    sugg = Suggestion(
        id="SUG-ENRICHED-01",
        content=SuggestionContent(
            title="طرح جامع اصلاح سیستم سرمایش",
            problem="افزایش دمای ترانس‌های فوق توزیع",
            solution="نصب فن‌های هوشمند و رادیاتورهای کمکی",
        ),
        evaluation=CommitteeEvaluation(
            status=SuggestionStatus.APPROVED,
            scrutiny=CommitteeScrutiny.APPROVED,
            description="مصوب جلسه شماره ۱۲ کارگروه بهینه‌سازی.",
            scrutiny_id=0,
        ),
        secretariat_evaluation=SecretariatEvaluation(
            scrutiny=SecretariatScrutiny.REFER_TO_COMMITTEE,
            comment="پس از تایید اولیه، جهت ارزیابی نهایی به کارگروه ارسال شد.",
            scrutiny_id=3,
        ),
        date=ShamsiDate("1402/09/20"),
        context_title="معاونت بهره‌برداری",
    )

    model = repo._to_model(sugg)
    assert model.committee_scrutiny_id == 0
    assert model.committee_scrutiny == "تایید"
    assert model.description == "مصوب جلسه شماره ۱۲ کارگروه بهینه‌سازی."
    assert model.secretariat_scrutiny_id == 3
    assert model.secretariat_scrutiny == "ارجاع به کمیته"
    assert (
        model.secretariat_comment
        == "پس از تایید اولیه، جهت ارزیابی نهایی به کارگروه ارسال شد."
    )

    hydrated = repo._to_entity(model)
    assert hydrated.id == sugg.id
    assert hydrated.evaluation.status == SuggestionStatus.APPROVED
    assert hydrated.evaluation.scrutiny == CommitteeScrutiny.APPROVED
    assert hydrated.evaluation.scrutiny_id == 0
    assert hydrated.evaluation.description == "مصوب جلسه شماره ۱۲ کارگروه بهینه‌سازی."
    assert hydrated.secretariat_evaluation is not None
    assert (
        hydrated.secretariat_evaluation.scrutiny
        == SecretariatScrutiny.REFER_TO_COMMITTEE
    )
    assert hydrated.secretariat_evaluation.scrutiny_id == 3
    assert (
        hydrated.secretariat_evaluation.comment
        == "پس از تایید اولیه، جهت ارزیابی نهایی به کارگروه ارسال شد."
    )


def test_mapper_with_nullable_fields():
    mock_session = MagicMock()
    repo = SqlSuggestionRepository(session=mock_session)
    minimal_suggestion = Suggestion(
        id="SUG-MINIMAL",
        content=SuggestionContent(
            title="عنوان بدون شرح مشکل و راهکار",
            problem="شرح مشکل معتبر است",
            solution="ارائه راهکار معتبر است",
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
    assert model.problem == "شرح مشکل معتبر است"
    assert model.solution == "ارائه راهکار معتبر است"
    assert model.committee_scrutiny is None
    assert model.description is None
    assert model.shamsi_date is None
    assert model.context_title is None

    hydrated = repo._to_entity(model)
    assert hydrated.id == "SUG-MINIMAL"
    assert hydrated.content.problem == "شرح مشکل معتبر است"
    assert hydrated.content.solution == "ارائه راهکار معتبر است"
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
                scrutiny=CommitteeScrutiny.ACCEPTED_AS_EXECUTED_SUGGESTION,
                description="مصوبه اجرایی",
                scrutiny_id=4,
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
        await uow.commit()

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


@pytest.mark.asyncio
async def test_save_and_retrieve_with_scrutiny_and_secretariat_columns(
    session_factory: async_sessionmaker[AsyncSession],
):
    async with clean_db_session(session_factory) as db_session:
        repo = SqlSuggestionRepository(session=db_session)

        sugg = Suggestion(
            id="SUG-DB-SCRUTINY-01",
            content=SuggestionContent(
                title="طرح ارتقای سطح ایمنی پست‌ها",
                problem="خطرات ناشی از خطای اپراتوری در مانورها",
                solution="استقرار سیستم قفل‌های اینترلاک هوشمند الکترومکانیکی",
            ),
            evaluation=CommitteeEvaluation(
                status=SuggestionStatus.APPROVED,
                scrutiny=CommitteeScrutiny.APPROVED,
                description="مصوب جلسه شماره ۸۸ با تامین اعتبار اولیه.",
                scrutiny_id=0,
            ),
            secretariat_evaluation=SecretariatEvaluation(
                scrutiny=SecretariatScrutiny.REFER_TO_COMMITTEE,
                comment="پرونده تکمیل و به کمیته ارجاع شد.",
                scrutiny_id=3,
            ),
            date=ShamsiDate("1402/10/01"),
            context_title="ایمنی و بهداشت",
        )

        await repo.save(sugg)
        await db_session.commit()

        retrieved = await repo.get_by_id("SUG-DB-SCRUTINY-01")
        assert retrieved is not None
        assert retrieved.id == "SUG-DB-SCRUTINY-01"
        assert retrieved.evaluation.scrutiny == CommitteeScrutiny.APPROVED
        assert retrieved.evaluation.scrutiny_id == 0
        assert (
            retrieved.evaluation.description
            == "مصوب جلسه شماره ۸۸ با تامین اعتبار اولیه."
        )
        assert retrieved.secretariat_evaluation is not None
        assert (
            retrieved.secretariat_evaluation.scrutiny
            == SecretariatScrutiny.REFER_TO_COMMITTEE
        )
        assert retrieved.secretariat_evaluation.scrutiny_id == 3
        assert (
            retrieved.secretariat_evaluation.comment
            == "پرونده تکمیل و به کمیته ارجاع شد."
        )


@pytest.mark.asyncio
async def test_upsert_updates_scrutiny_columns(
    session_factory: async_sessionmaker[AsyncSession],
):
    async with clean_db_session(session_factory) as db_session:
        repo = SqlSuggestionRepository(session=db_session)

        initial = Suggestion(
            id="SUG-DB-UPSERT-02",
            content=SuggestionContent(
                title="طرح اولیه",
                problem="مشکل اولیه",
                solution="راهکار اولیه",
            ),
            evaluation=CommitteeEvaluation(
                status=SuggestionStatus.PENDING,
                scrutiny=None,
                description=None,
                scrutiny_id=None,
            ),
            secretariat_evaluation=None,
            date=ShamsiDate("1402/01/01"),
            context_title="حوزه ستادی",
        )
        await repo.save(initial)
        await db_session.commit()

        # Upsert with committee decision and secretariat comment
        updated = Suggestion(
            id="SUG-DB-UPSERT-02",
            content=SuggestionContent(
                title="طرح اولیه ویرایش شده",
                problem="مشکل اولیه",
                solution="راهکار اولیه",
            ),
            evaluation=CommitteeEvaluation(
                status=SuggestionStatus.REJECTED,
                scrutiny=CommitteeScrutiny.REJECTED,
                description="فاقد اولویت اجرایی در سال جاری.",
                scrutiny_id=1,
            ),
            secretariat_evaluation=SecretariatEvaluation(
                scrutiny=SecretariatScrutiny.OUT_OF_FRAMEWORK,
                comment="موضوع در حیطه اختیارات شرکت نیست.",
                scrutiny_id=0,
            ),
            date=ShamsiDate("1402/01/01"),
            context_title="حوزه ستادی",
        )
        await repo.save(updated)
        await db_session.commit()

        retrieved = await repo.get_by_id("SUG-DB-UPSERT-02")
        assert retrieved is not None
        assert retrieved.evaluation.status == SuggestionStatus.REJECTED
        assert retrieved.evaluation.scrutiny == CommitteeScrutiny.REJECTED
        assert retrieved.evaluation.scrutiny_id == 1
        assert retrieved.evaluation.description == "فاقد اولویت اجرایی در سال جاری."
        assert retrieved.secretariat_evaluation is not None
        assert (
            retrieved.secretariat_evaluation.scrutiny
            == SecretariatScrutiny.OUT_OF_FRAMEWORK
        )
        assert retrieved.secretariat_evaluation.scrutiny_id == 0
        assert (
            retrieved.secretariat_evaluation.comment
            == "موضوع در حیطه اختیارات شرکت نیست."
        )


@pytest.mark.asyncio
async def test_insert_suggestion_success(session_factory: async_sessionmaker[AsyncSession]):
    async with clean_db_session(session_factory) as db_session:
        repo = SqlSuggestionRepository(session=db_session)
        sugg = _create_sample_suggestion(suggestion_id="SUG-DB-INSERT-01")
        await repo.insert(sugg)
        await db_session.commit()

        retrieved = await repo.get_by_id("SUG-DB-INSERT-01")
        assert retrieved is not None
        assert retrieved.id == "SUG-DB-INSERT-01"


@pytest.mark.asyncio
async def test_insert_suggestion_duplicate_raises_already_exists(session_factory: async_sessionmaker[AsyncSession]):
    async with clean_db_session(session_factory) as db_session:
        repo = SqlSuggestionRepository(session=db_session)
        sugg = _create_sample_suggestion(suggestion_id="SUG-DB-INSERT-DUP")
        await repo.insert(sugg)
        await db_session.commit()

        with pytest.raises(SuggestionAlreadyExistsError) as exc_info:
            await repo.insert(sugg)

        assert "already exists" in str(exc_info.value)
        assert exc_info.value.pointer == "/data/suggestionId"

