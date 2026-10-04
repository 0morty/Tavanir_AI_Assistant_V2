from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.infrastructure.db.repositories.sql.checkpoint_repository import (
    SqlCheckpointRepository,
)
from src.infrastructure.db.repositories.sql.skipped_suggestion_repository import (
    SqlSkippedSuggestionRepository,
)
from src.infrastructure.db.repositories.sql.suggestion_repository import (
    SqlSuggestionRepository,
)
from src.infrastructure.db.sql_models.skipped_suggestion_model import (
    SkippedSuggestionModel,
)
from src.infrastructure.db.unit_of_work import SqlUnitOfWork
from tests.database_fixtures import clean_db_session

from src.application.dtos import SkippedRecordDTO
from src.domain.entities import (
    CommitteeEvaluation,
    Suggestion,
    SuggestionContent,
)
from src.domain.enums import SuggestionStatus


@pytest.mark.asyncio
async def test_checkpoint_repository_crud(
    session_factory: async_sessionmaker[AsyncSession],
):
    async with clean_db_session(session_factory) as session:
        repo = SqlCheckpointRepository(session=session)

        # 1. Non-existent checkpoint returns None
        initial = await repo.get_checkpoint("test_job")
        assert initial is None

        # 2. Save new checkpoint
        await repo.save_checkpoint(
            job_name="test_job", offset=150, last_id="20000//96", total_processed=150
        )
        await session.commit()

        cp = await repo.get_checkpoint("test_job")
        assert cp is not None
        assert cp.last_offset == 150
        assert cp.last_processed_id == "20000//96"
        assert cp.total_processed == 150

        # 3. Upsert checkpoint with updated watermark
        await repo.save_checkpoint(
            job_name="test_job", offset=300, last_id="20002//97", total_processed=300
        )
        await session.commit()

        updated_cp = await repo.get_checkpoint("test_job")
        assert updated_cp is not None
        assert updated_cp.last_offset == 300
        assert updated_cp.last_processed_id == "20002//97"
        assert updated_cp.total_processed == 300

        # 4. Clear checkpoint
        await repo.clear_checkpoint("test_job")
        await session.commit()

        cleared_cp = await repo.get_checkpoint("test_job")
        assert cleared_cp is None


@pytest.mark.asyncio
async def test_skipped_suggestion_repository_save_batch(
    session_factory: async_sessionmaker[AsyncSession],
):
    async with clean_db_session(session_factory) as session:
        repo = SqlSkippedSuggestionRepository(session=session)

        records = [
            SkippedRecordDTO(
                suggestion_id="err-1",
                reason="Invalid status ID 999",
                error_type="InvalidStatusIdError",
            ),
            SkippedRecordDTO(
                suggestion_id="err-2",
                reason="Empty title",
                error_type="InvalidSuggestionContentError",
            ),
        ]

        await repo.save_batch(records)
        await session.commit()

        stmt = select(SkippedSuggestionModel).order_by(SkippedSuggestionModel.id.asc())
        result = await session.execute(stmt)
        persisted = result.scalars().all()

        assert len(persisted) == 2
        assert persisted[0].suggestion_id == "err-1"
        assert persisted[0].reason == "Invalid status ID 999"
        assert persisted[0].error_type == "InvalidStatusIdError"
        assert persisted[1].suggestion_id == "err-2"


@pytest.mark.asyncio
async def test_unit_of_work_integrates_new_repositories(
    session_factory: async_sessionmaker[AsyncSession],
):
    uow = SqlUnitOfWork(
        session_factory=session_factory,
        suggestion_repo_factory=SqlSuggestionRepository,
        checkpoint_repo_factory=SqlCheckpointRepository,
        skipped_repo_factory=SqlSkippedSuggestionRepository,
    )

    async with clean_db_session(session_factory):
        pass

    async with uow:
        assert isinstance(uow.checkpoints, SqlCheckpointRepository)
        assert isinstance(uow.skipped_suggestions, SqlSkippedSuggestionRepository)

        await uow.checkpoints.save_checkpoint(
            job_name="uow_job", offset=500, last_id="20005//92", total_processed=500
        )
        await uow.skipped_suggestions.save_batch(
            [
                SkippedRecordDTO(
                    suggestion_id="sk-1", reason="error", error_type="ValueError"
                )
            ]
        )
        await uow.commit()

    async with uow:
        cp = await uow.checkpoints.get_checkpoint("uow_job")
        assert cp is not None
        assert cp.last_offset == 500
        assert cp.last_processed_id == "20005//92"


@pytest.mark.asyncio
async def test_suggestion_repository_delete_batch(
    session_factory: async_sessionmaker[AsyncSession],
):
    async with clean_db_session(session_factory) as session:
        repo = SqlSuggestionRepository(session=session)

        sug1 = Suggestion(
            id="sug-batch-1",
            content=SuggestionContent(
                title="عنوان اول پیش‌نویس",
                problem="مشکل افت ولتاژ در پست انتقال",
                solution="نصب خازن موازی در باس اصلی",
            ),
            evaluation=CommitteeEvaluation(
                status=SuggestionStatus.APPROVED, scrutiny=None, description=None
            ),
            date=None,
            context_title=None,
        )
        sug2 = Suggestion(
            id="sug-batch-2",
            content=SuggestionContent(
                title="عنوان دوم پیش‌نویس",
                problem="تلفات حرارتی کابل‌های توزیع",
                solution="افزایش سطح مقطع هادی شبکه",
            ),
            evaluation=CommitteeEvaluation(
                status=SuggestionStatus.EXECUTED, scrutiny=None, description=None
            ),
            date=None,
            context_title=None,
        )
        sug3 = Suggestion(
            id="sug-batch-3",
            content=SuggestionContent(
                title="عنوان سوم پیش‌نویس",
                problem="نوسان شدید فرکانس ژنراتور",
                solution="تنظیم مجدد کنترل‌کننده گاورنر",
            ),
            evaluation=CommitteeEvaluation(
                status=SuggestionStatus.REJECTED, scrutiny=None, description=None
            ),
            date=None,
            context_title=None,
        )

        await repo.save_batch([sug1, sug2, sug3])
        await session.commit()

        # Delete batch containing sug1 and sug3
        await repo.delete_batch(["sug-batch-1", "sug-batch-3"])
        await session.commit()

        remaining_1 = await repo.get_by_id("sug-batch-1")
        remaining_2 = await repo.get_by_id("sug-batch-2")
        remaining_3 = await repo.get_by_id("sug-batch-3")

        assert remaining_1 is None
        assert remaining_2 is not None
        assert remaining_3 is None
