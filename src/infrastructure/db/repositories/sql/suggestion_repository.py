from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

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
        com_scrutiny: CommitteeScrutiny | None = None
        if model.committee_scrutiny_id is not None:
            com_scrutiny = CommitteeScrutiny.from_code(model.committee_scrutiny_id)
        elif model.committee_scrutiny:
            com_scrutiny = CommitteeScrutiny.from_string(model.committee_scrutiny)

        sec_evaluation: SecretariatEvaluation | None = None
        if (
            model.secretariat_scrutiny is not None
            or model.secretariat_comment is not None
            or model.secretariat_scrutiny_id is not None
        ):
            sec_scrutiny: SecretariatScrutiny | None = None
            if model.secretariat_scrutiny_id is not None:
                sec_scrutiny = SecretariatScrutiny.from_code(
                    model.secretariat_scrutiny_id
                )
            elif model.secretariat_scrutiny:
                sec_scrutiny = SecretariatScrutiny.from_string(
                    model.secretariat_scrutiny
                )

            sec_evaluation = SecretariatEvaluation(
                scrutiny=sec_scrutiny,
                comment=model.secretariat_comment,
                scrutiny_id=model.secretariat_scrutiny_id,
            )

        return Suggestion(
            id=model.id,
            content=SuggestionContent(
                title=model.title,
                problem=model.problem,
                solution=model.solution,
            ),
            evaluation=CommitteeEvaluation(
                status=SuggestionStatus.from_id(model.status_id),
                scrutiny=com_scrutiny,
                description=model.description,
                scrutiny_id=model.committee_scrutiny_id,
            ),
            date=ShamsiDate(model.shamsi_date) if model.shamsi_date else None,
            context_title=model.context_title,
            secretariat_evaluation=sec_evaluation,
        )

    def _extract_evaluation_fields(
        self, entity: Suggestion
    ) -> tuple[str | None, int | None, str | None, str | None, int | None]:
        """Extract (com_title, com_id, sec_title, sec_comment, sec_id) from Suggestion."""
        com_title = (
            entity.evaluation.scrutiny.title_fa
            if entity.evaluation.scrutiny
            else None
        )
        com_id = (
            entity.evaluation.scrutiny.code
            if entity.evaluation.scrutiny
            else entity.evaluation.scrutiny_id
        )

        sec_title = None
        sec_comment = None
        sec_id = None
        if entity.secretariat_evaluation:
            sec = entity.secretariat_evaluation
            sec_title = (
                sec.scrutiny.title_fa
                if sec.scrutiny
                else None
            )
            sec_id = (
                sec.scrutiny.code
                if sec.scrutiny
                else sec.scrutiny_id
            )
            sec_comment = sec.comment

        return com_title, com_id, sec_title, sec_comment, sec_id

    def _to_model(self, entity: Suggestion) -> SuggestionModel:
        """Map domain entity to SQLAlchemy model."""
        com_title, com_id, sec_title, sec_comment, sec_id = self._extract_evaluation_fields(entity)
        return SuggestionModel(
            id=entity.id,
            title=entity.content.title,
            problem=entity.content.problem,
            solution=entity.content.solution,
            status_id=entity.evaluation.status.status_id,
            committee_scrutiny=com_title,
            description=entity.evaluation.description,
            committee_scrutiny_id=com_id,
            secretariat_scrutiny_id=sec_id,
            secretariat_scrutiny=sec_title,
            secretariat_comment=sec_comment,
            shamsi_date=str(entity.date) if entity.date else None,
            context_title=entity.context_title,
        )

    def _entity_to_dict(self, entity: Suggestion) -> dict[str, Any]:
        """Flatten domain entity to dictionary for PostgreSQL upsert values."""
        com_title, com_id, sec_title, sec_comment, sec_id = self._extract_evaluation_fields(entity)
        return {
            "id": entity.id,
            "title": entity.content.title,
            "problem": entity.content.problem,
            "solution": entity.content.solution,
            "status_id": entity.evaluation.status.status_id,
            "committee_scrutiny": com_title,
            "description": entity.evaluation.description,
            "committee_scrutiny_id": com_id,
            "secretariat_scrutiny_id": sec_id,
            "secretariat_scrutiny": sec_title,
            "secretariat_comment": sec_comment,
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
                "committee_scrutiny": stmt.excluded.committee_scrutiny,
                "description": stmt.excluded.description,
                "committee_scrutiny_id": stmt.excluded.committee_scrutiny_id,
                "secretariat_scrutiny_id": stmt.excluded.secretariat_scrutiny_id,
                "secretariat_scrutiny": stmt.excluded.secretariat_scrutiny,
                "secretariat_comment": stmt.excluded.secretariat_comment,
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

        # Deduplicate suggestions by ID to protect PostgreSQL from CardinalityViolation in multi-row ON CONFLICT
        unique_map = {s.id: s for s in suggestions}
        values_list = [self._entity_to_dict(s) for s in unique_map.values()]
        stmt = pg_insert(SuggestionModel).values(values_list)
        upsert_stmt = stmt.on_conflict_do_update(
            index_elements=[SuggestionModel.id],
            set_={
                "title": stmt.excluded.title,
                "problem": stmt.excluded.problem,
                "solution": stmt.excluded.solution,
                "status_id": stmt.excluded.status_id,
                "committee_scrutiny": stmt.excluded.committee_scrutiny,
                "description": stmt.excluded.description,
                "committee_scrutiny_id": stmt.excluded.committee_scrutiny_id,
                "secretariat_scrutiny_id": stmt.excluded.secretariat_scrutiny_id,
                "secretariat_scrutiny": stmt.excluded.secretariat_scrutiny,
                "secretariat_comment": stmt.excluded.secretariat_comment,
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

    async def delete_batch(self, suggestion_ids: Sequence[str]) -> None:
        """Batch delete suggestion records by identifiers for compensating rollbacks."""
        if not suggestion_ids:
            return
        stmt = delete(SuggestionModel).where(SuggestionModel.id.in_(suggestion_ids))
        await self.session.execute(stmt)


__all__ = ["SqlSuggestionRepository"]
