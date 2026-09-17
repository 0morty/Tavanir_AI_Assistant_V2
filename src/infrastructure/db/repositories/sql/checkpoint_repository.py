from __future__ import annotations

import logging

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.dtos import CheckpointData
from src.application.interfaces.i_checkpoint_repository import ICheckpointRepository
from src.infrastructure.db.sql_models.checkpoint_model import CheckpointModel

logger = logging.getLogger(__name__)


class SqlCheckpointRepository(ICheckpointRepository):
    """
    PostgreSQL repository implementation for tracking ETL batch ingestion watermarks.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_checkpoint(self, job_name: str) -> CheckpointData | None:
        """Fetch the last saved checkpoint for a given job."""
        stmt = select(CheckpointModel).where(CheckpointModel.job_name == job_name)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return CheckpointData(
            last_offset=model.last_offset,
            last_processed_id=model.last_processed_id,
            total_processed=model.total_processed,
        )

    async def save_checkpoint(
        self, job_name: str, offset: int, last_id: str | None, total_processed: int
    ) -> None:
        """Persist or update the watermark progress for a given job."""
        stmt = pg_insert(CheckpointModel).values(
            job_name=job_name,
            last_offset=offset,
            last_processed_id=last_id,
            total_processed=total_processed,
        )
        upsert_stmt = stmt.on_conflict_do_update(
            index_elements=[CheckpointModel.job_name],
            set_={
                "last_offset": stmt.excluded.last_offset,
                "last_processed_id": stmt.excluded.last_processed_id,
                "total_processed": stmt.excluded.total_processed,
                "updated_at": func.now(),
            },
        )
        await self._session.execute(upsert_stmt)
        logger.debug(
            f"Updated ingestion checkpoint for '{job_name}': offset={offset}, last_id={last_id}, total={total_processed}"
        )

    async def clear_checkpoint(self, job_name: str) -> None:
        """Reset/clear the checkpoint watermark for a given job."""
        stmt = delete(CheckpointModel).where(CheckpointModel.job_name == job_name)
        await self._session.execute(stmt)
        logger.info(f"Cleared ingestion checkpoint for '{job_name}'")


__all__ = ["SqlCheckpointRepository"]
