from __future__ import annotations

from uuid import uuid4

import pytest
from src.infrastructure.db.unit_of_work import SqlUnitOfWork

from src.domain.entities import (
    CommitteeEvaluation,
    OutboxEvent,
    Suggestion,
    SuggestionContent,
)
from src.domain.enums import SuggestionStatus

pytestmark = [
    pytest.mark.db,
    pytest.mark.asyncio,
    pytest.mark.usefixtures("postgres_test_database"),
]


async def test_suggestion_and_outbox_commit_together(session_factory):
    sugg_id = f"atomic-commit-{uuid4().hex[:8]}"
    event_id = uuid4()

    uow = SqlUnitOfWork(session_factory)
    async with uow:
        suggestion = Suggestion(
            id=sugg_id,
            content=SuggestionContent(
                title="پیشنهاد اتمیک",
                problem="مسئله آزمایشی",
                solution="راهکار آزمایشی",
            ),
            evaluation=CommitteeEvaluation(status=SuggestionStatus.APPROVED),
            version=1,
        )
        outbox_event = OutboxEvent(
            id=event_id,
            resource_type="SUGGESTION",
            resource_id=sugg_id,
            event_type="SUGGESTION_INGESTED",
            version=1,
            payload={"suggestion_id": sugg_id, "version": 1},
            status="PENDING",
        )

        await uow.suggestions.save(suggestion)
        await uow.outbox.append(outbox_event)
        await uow.commit()

    # Verify both are persisted
    async with uow:
        persisted_sugg = await uow.suggestions.get_by_id(sugg_id)
        persisted_event = await uow.outbox.get_by_id(event_id)

        assert persisted_sugg is not None
        assert persisted_sugg.id == sugg_id
        assert persisted_event is not None
        assert persisted_event.id == event_id
        assert persisted_event.resource_id == sugg_id


async def test_suggestion_and_outbox_rollback_together(session_factory):
    sugg_id = f"atomic-rollback-{uuid4().hex[:8]}"
    event_id = uuid4()

    uow = SqlUnitOfWork(session_factory)
    try:
        async with uow:
            suggestion = Suggestion(
                id=sugg_id,
                content=SuggestionContent(
                    title="پیشنهاد رول‌بک",
                    problem="مسئله",
                    solution="راهکار",
                ),
                evaluation=CommitteeEvaluation(status=SuggestionStatus.APPROVED),
                version=1,
            )
            outbox_event = OutboxEvent(
                id=event_id,
                resource_type="SUGGESTION",
                resource_id=sugg_id,
                event_type="SUGGESTION_INGESTED",
                version=1,
                payload={"suggestion_id": sugg_id, "version": 1},
                status="PENDING",
            )

            await uow.suggestions.save(suggestion)
            await uow.outbox.append(outbox_event)
            # Intentionally raise before commit to trigger rollback
            raise RuntimeError("Simulated transaction fault")
    except RuntimeError:
        pass

    # Verify neither was persisted
    async with uow:
        persisted_sugg = await uow.suggestions.get_by_id(sugg_id)
        persisted_event = await uow.outbox.get_by_id(event_id)

        assert persisted_sugg is None
        assert persisted_event is None
