from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities import (
    CommitteeEvaluation,
    ShamsiDate,
    Suggestion,
    SuggestionContent,
)
from src.domain.enums import SuggestionStatus
from src.domain.interfaces.i_suggestion_repository import ISuggestionRepository
from src.infrastructure.db.repositories.sql.base_sql_repository import BaseSqlRepository
from src.infrastructure.db.sql_models.suggestion_model import SuggestionModel

logger = logging.getLogger(__name__)


class SqlSuggestionRepository(
    BaseSqlRepository[Suggestion, SuggestionModel], ISuggestionRepository
):
    """
    PostgreSQL repository implementation for employee suggestions (ADR-002).
    Acts as the authoritative System of Record.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(
            session=session,
            entity_class=Suggestion,
            model_class=SuggestionModel,
        )

    def _to_entity(self, model: SuggestionModel) -> Suggestion:
        """Map SQLAlchemy model to rich domain entity."""
        return Suggestion(
            id=model.id,
            content=SuggestionContent(
                title=model.title,
                problem=model.problem,
                solution=model.solution,
            ),
            evaluation=CommitteeEvaluation(
                status=SuggestionStatus.from_id(model.status_id),
                scrutiny=model.scrutiny,
                description=model.description,
            ),
            date=ShamsiDate(model.shamsi_date) if model.shamsi_date else None,
            context_title=model.context_title,
        )

    def _to_model(self, entity: Suggestion) -> SuggestionModel:
        """Map domain entity to SQLAlchemy model."""
        return SuggestionModel(
            id=entity.id,
            title=entity.content.title,
            problem=entity.content.problem,
            solution=entity.content.solution,
            status_id=entity.evaluation.status.status_id,
            scrutiny=entity.evaluation.scrutiny,
            description=entity.evaluation.description,
            shamsi_date=str(entity.date) if entity.date else None,
            context_title=entity.context_title,
        )

    def _entity_to_dict(self, entity: Suggestion) -> dict[str, Any]:
        """Flatten domain entity to dictionary for PostgreSQL upsert values."""
        return {
            "id": entity.id,
            "title": entity.content.title,
            "problem": entity.content.problem,
            "solution": entity.content.solution,
            "status_id": entity.evaluation.status.status_id,
            "scrutiny": entity.evaluation.scrutiny,
            "description": entity.evaluation.description,
            "shamsi_date": str(entity.date) if entity.date else None,
            "context_title": entity.context_title,
        }

    async def get_by_id(self, suggestion_id: str) -> Suggestion | None:
        """Fetch a single suggestion by its primary key identifier."""
        stmt = select(SuggestionModel).where(SuggestionModel.id == suggestion_id)
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_ids(self, suggestion_ids: Sequence[str]) -> list[Suggestion]:
        """
        Batch fetch suggestions by their primary key identifiers.
        Preserves candidate order after Max-Passage Pooling (MaxP).
        """
        if not suggestion_ids:
            return []

        # Deduplicate while preserving input ranking order
        unique_ids = list(dict.fromkeys(suggestion_ids))
        stmt = select(SuggestionModel).where(SuggestionModel.id.in_(unique_ids))
        result = await self.session.execute(stmt)
        models = result.scalars().all()

        entity_map = {model.id: self._to_entity(model) for model in models}
        return [entity_map[sid] for sid in unique_ids if sid in entity_map]

    async def save(self, suggestion: Suggestion) -> None:
        """Persist or update a single suggestion record in PostgreSQL via atomic upsert."""
        values = self._entity_to_dict(suggestion)
        stmt = pg_insert(SuggestionModel).values(values)
        upsert_stmt = stmt.on_conflict_do_update(
            index_elements=[SuggestionModel.id],
            set_={
                "title": stmt.excluded.title,
                "problem": stmt.excluded.problem,
                "solution": stmt.excluded.solution,
                "status_id": stmt.excluded.status_id,
                "scrutiny": stmt.excluded.scrutiny,
                "description": stmt.excluded.description,
                "shamsi_date": stmt.excluded.shamsi_date,
                "context_title": stmt.excluded.context_title,
                "updated_at": func.now(),
            },
        )
        await self.session.execute(upsert_stmt)

    async def save_batch(self, suggestions: Sequence[Suggestion]) -> None:
        """Batch persist or update multiple suggestions in a single atomic SQL statement."""
        if not suggestions:
            return

        values_list = [self._entity_to_dict(s) for s in suggestions]
        stmt = pg_insert(SuggestionModel).values(values_list)
        upsert_stmt = stmt.on_conflict_do_update(
            index_elements=[SuggestionModel.id],
            set_={
                "title": stmt.excluded.title,
                "problem": stmt.excluded.problem,
                "solution": stmt.excluded.solution,
                "status_id": stmt.excluded.status_id,
                "scrutiny": stmt.excluded.scrutiny,
                "description": stmt.excluded.description,
                "shamsi_date": stmt.excluded.shamsi_date,
                "context_title": stmt.excluded.context_title,
                "updated_at": func.now(),
            },
        )
        await self.session.execute(upsert_stmt)

    async def delete(self, suggestion_id: str) -> None:
        """Delete a suggestion record by its identifier."""
        stmt = delete(SuggestionModel).where(SuggestionModel.id == suggestion_id)
        await self.session.execute(stmt)


__all__ = ["SqlSuggestionRepository"]
