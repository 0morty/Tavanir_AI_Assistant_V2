from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities import OutboxEvent
from src.domain.enums import OutboxEventStatus, OutboxEventType, OutboxResourceType
from src.domain.interfaces.i_outbox_repository import IOutboxRepository
from src.infrastructure.db.repositories.sql.base_sql_repository import BaseSqlRepository
from src.infrastructure.db.sql_models.outbox_event_model import OutboxEventModel

logger = logging.getLogger(__name__)


class SqlOutboxRepository(
    BaseSqlRepository[OutboxEvent, OutboxEventModel], IOutboxRepository
):
    """
    SQLAlchemy-backed implementation of IOutboxRepository.
    Enforces ACID append boundaries and concurrency-safe event consumption.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(
            session=session,
            entity_class=OutboxEvent,
            model_class=OutboxEventModel,
        )

    def _to_entity(self, model: OutboxEventModel) -> OutboxEvent:
        return OutboxEvent(
            id=model.id,
            resource_type=OutboxResourceType(model.resource_type),
            resource_id=model.resource_id,
            event_type=OutboxEventType(model.event_type),
            version=model.version,
            payload=model.payload,
            status=OutboxEventStatus(model.status),
            retry_count=model.retry_count,
            last_error=model.last_error,
            locked_at=model.locked_at,
            created_at=model.created_at,
            processed_at=model.processed_at,
        )

    def _to_model(self, entity: OutboxEvent) -> OutboxEventModel:
        return OutboxEventModel(
            id=entity.id,
            resource_type=str(entity.resource_type),
            resource_id=entity.resource_id,
            event_type=str(entity.event_type),
            version=entity.version,
            payload=entity.payload,
            status=str(entity.status),
            retry_count=entity.retry_count,
            last_error=entity.last_error,
            locked_at=entity.locked_at,
            created_at=entity.created_at,
            processed_at=entity.processed_at,
        )

    async def append(self, event: OutboxEvent) -> None:
        """Appends a new outbox event to the ledger within the current transaction."""
        model = self._to_model(event)
        self._session.add(model)
        await self._session.flush()

    async def get_by_id(self, event_id: UUID) -> OutboxEvent | None:
        """Fetches an outbox event by ID without locking."""
        stmt = select(OutboxEventModel).where(OutboxEventModel.id == event_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model is not None else None

    async def get_for_processing(self, event_id: UUID) -> OutboxEvent | None:
        """
        Attempts to claim an outbox event for processing using row-level locking
        (FOR UPDATE SKIP LOCKED). Sets locked_at and status = 'PROCESSING'.
        """
        stmt = (
            select(OutboxEventModel)
            .where(OutboxEventModel.id == event_id)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None

        now = datetime.now(timezone.utc)
        model.locked_at = now
        model.status = "PROCESSING"
        await self._session.flush()
        return self._to_entity(model)

    async def update_status(
        self,
        event_id: UUID,
        status: OutboxEventStatus | str,
        error: str | None = None,
        retry_count: int | None = None,
    ) -> None:
        """Updates status, last_error, processed_at timestamps and retry counts."""
        status_str = status.value if hasattr(status, "value") else str(status)
        values: dict = {
            "status": status_str,
            "last_error": error,
        }
        if status_str in (OutboxEventStatus.COMPLETED, OutboxEventStatus.SUPERSEDED):
            values["processed_at"] = datetime.now(timezone.utc)
            values["locked_at"] = None
        elif status_str == OutboxEventStatus.PENDING:
            values["locked_at"] = None

        if retry_count is not None:
            values["retry_count"] = retry_count

        stmt = (
            update(OutboxEventModel)
            .where(OutboxEventModel.id == event_id)
            .values(**values)
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def fetch_stale_events(
        self, stuck_before: datetime, limit: int = 100
    ) -> list[OutboxEvent]:
        """Fetches events stuck in 'PROCESSING' whose lock has expired."""
        stmt = (
            select(OutboxEventModel)
            .where(
                OutboxEventModel.status == "PROCESSING",
                OutboxEventModel.locked_at < stuck_before,
            )
            .order_by(OutboxEventModel.locked_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def fetch_pending_events(
        self, created_before: datetime, limit: int = 100
    ) -> list[OutboxEvent]:
        """Fetches un-enqueued events in 'PENDING' state older than threshold."""
        stmt = (
            select(OutboxEventModel)
            .where(
                OutboxEventModel.status == "PENDING",
                OutboxEventModel.created_at < created_before,
            )
            .order_by(OutboxEventModel.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def fetch_failed_for_retry(
        self, created_after: datetime, max_retries: int = 20, limit: int = 100
    ) -> list[OutboxEvent]:
        """Fetches 'FAILED' events eligible for extended outage retry."""
        stmt = (
            select(OutboxEventModel)
            .where(
                OutboxEventModel.status == "FAILED",
                OutboxEventModel.created_at >= created_after,
                OutboxEventModel.retry_count < max_retries,
            )
            .order_by(OutboxEventModel.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def prune_completed(self, before: datetime) -> int:
        """Prunes 'COMPLETED' and 'SUPERSEDED' events older than given timestamp."""
        stmt = delete(OutboxEventModel).where(
            OutboxEventModel.status.in_(("COMPLETED", "SUPERSEDED")),
            OutboxEventModel.processed_at < before,
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount or 0


__all__ = ["SqlOutboxRepository"]
