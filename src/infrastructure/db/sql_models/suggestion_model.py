from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
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
        Index(
            "ix_suggestions_active",
            "id",
            postgresql_where=text("is_deleted = FALSE"),
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    problem: Mapped[str] = mapped_column(Text, nullable=False)
    solution: Mapped[str] = mapped_column(Text, nullable=False)
    status_id: Mapped[int] = mapped_column(SmallInteger, nullable=False, index=True)
    committee_scrutiny: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    committee_scrutiny_id: Mapped[int | None] = mapped_column(
        SmallInteger, nullable=True, index=True
    )
    secretariat_scrutiny_id: Mapped[int | None] = mapped_column(
        SmallInteger, nullable=True, index=True
    )
    secretariat_scrutiny: Mapped[str | None] = mapped_column(Text, nullable=True)
    secretariat_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    shamsi_date: Mapped[str | None] = mapped_column(
        String(10), nullable=True, index=True
    )
    context_title: Mapped[str | None] = mapped_column(
        String(512), nullable=True, index=True
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    version: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False, server_default="1"
    )


__all__ = ["SuggestionModel"]
