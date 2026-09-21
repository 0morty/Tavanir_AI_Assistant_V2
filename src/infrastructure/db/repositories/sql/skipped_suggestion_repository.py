from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.dtos import SkippedRecordDTO
from src.application.interfaces.i_skipped_suggestion_repository import (
    ISkippedSuggestionRepository,
)
from src.infrastructure.db.sql_models.skipped_suggestion_model import (
    SkippedSuggestionModel,
)

logger = logging.getLogger(__name__)


class SqlSkippedSuggestionRepository(ISkippedSuggestionRepository):
    """
    PostgreSQL repository implementation for persisting audit records of corrupted
    or invalid historical suggestions skipped during ETL ingestion.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_batch(self, skipped_records: Sequence[SkippedRecordDTO]) -> None:
        """Batch persist skipped suggestion audit records."""
        if not skipped_records:
            return

        models = [
            SkippedSuggestionModel(
                suggestion_id=record.suggestion_id,
                reason=record.reason,
                error_type=record.error_type,
            )
            for record in skipped_records
        ]
        self._session.add_all(models)
        logger.debug(f"Staged {len(models)} skipped suggestion audit records")


__all__ = ["SqlSkippedSuggestionRepository"]
