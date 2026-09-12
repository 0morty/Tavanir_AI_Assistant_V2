from __future__ import annotations

from sqlalchemy import CheckConstraint, Index, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.db.sql_models.base import Base, TimestampMixin


class SuggestionModel(Base, TimestampMixin):
    """
    PostgreSQL ORM model for employee suggestions (ADR-002).
    Acts as the authoritative System of Record.
    """

    __tablename__ = "suggestions"
    __table_args__ = (
        CheckConstraint(
            "status_id >= 1 AND status_id <= 5",
            name="ck_suggestions_status_id",
        ),
        Index("ix_suggestions_status_context", "status_id", "context_title"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    problem: Mapped[str | None] = mapped_column(Text, nullable=True)
    solution: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_id: Mapped[int] = mapped_column(SmallInteger, nullable=False, index=True)
    scrutiny: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    shamsi_date: Mapped[str | None] = mapped_column(
        String(10), nullable=True, index=True
    )
    context_title: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )


__all__ = ["SuggestionModel"]
