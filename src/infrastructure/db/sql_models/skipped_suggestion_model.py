from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.db.sql_models.base import Base


class SkippedSuggestionModel(Base):
    """
    PostgreSQL ORM audit model for tracking legacy suggestions that failed
    data normalization, validation, or chunking invariants.
    """

    __tablename__ = "skipped_suggestions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    suggestion_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    error_type: Mapped[str] = mapped_column(String(100), nullable=False)
    skipped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )


__all__ = ["SkippedSuggestionModel"]
