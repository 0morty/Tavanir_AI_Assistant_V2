from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.db.sql_models.base import Base


class OutboxEventModel(Base):
    """
    PostgreSQL ORM model for transactional outbox events.
    Serves as the durable ledger for asynchronous projections to external stores (e.g. Qdrant).
    """

    __tablename__ = "outbox_events"
    __table_args__ = (
        Index(
            "idx_outbox_events_pending",
            "created_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index(
            "idx_outbox_events_stuck",
            "locked_at",
            postgresql_where=text("status = 'PROCESSING'"),
        ),
        Index(
            "idx_outbox_events_failed",
            "created_at",
            "retry_count",
            postgresql_where=text("status = 'FAILED'"),
        ),
        Index(
            "idx_outbox_events_resource",
            "resource_id",
            "resource_type",
            "version",
        ),
        Index(
            "idx_outbox_events_prune",
            "processed_at",
            postgresql_where=text("status IN ('COMPLETED', 'SUPERSEDED')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="PENDING",
        server_default=text("'PENDING'"),
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


__all__ = ["OutboxEventModel"]
