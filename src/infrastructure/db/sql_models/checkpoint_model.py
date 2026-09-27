from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.db.sql_models.base import Base


class CheckpointModel(Base):
    """
    PostgreSQL ORM model for recording ETL ingestion watermark progress.
    Keyed by unique job name to isolate multi-tenant or multi-pipeline runs.
    """

    __tablename__ = "ingestion_checkpoints"

    job_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_offset: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_processed_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    total_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )


__all__ = ["CheckpointModel"]
