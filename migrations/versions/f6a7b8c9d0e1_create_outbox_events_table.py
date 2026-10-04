"""create_outbox_events_table

Revision ID: f6a7b8c9d0e1
Revises: e4f5a6b7c8d9
Create Date: 2026-10-04 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: str | Sequence[str] | None = "e4f5a6b7c8d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema to include transactional outbox_events table."""
    op.create_table(
        "outbox_events",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("resource_type", sa.String(length=50), nullable=False),
        sa.Column("resource_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        sa.Column(
            "retry_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_events")),
    )
    op.create_index(
        "idx_outbox_events_pending",
        "outbox_events",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.create_index(
        "idx_outbox_events_stuck",
        "outbox_events",
        ["locked_at"],
        unique=False,
        postgresql_where=sa.text("status = 'PROCESSING'"),
    )
    op.create_index(
        "idx_outbox_events_failed",
        "outbox_events",
        ["created_at", "retry_count"],
        unique=False,
        postgresql_where=sa.text("status = 'FAILED'"),
    )
    op.create_index(
        "idx_outbox_events_resource",
        "outbox_events",
        ["resource_id", "resource_type", "version"],
        unique=False,
    )
    op.create_index(
        "idx_outbox_events_prune",
        "outbox_events",
        ["processed_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('COMPLETED', 'SUPERSEDED')"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "idx_outbox_events_prune",
        table_name="outbox_events",
        postgresql_where=sa.text("status IN ('COMPLETED', 'SUPERSEDED')"),
    )
    op.drop_index(
        "idx_outbox_events_resource",
        table_name="outbox_events",
    )
    op.drop_index(
        "idx_outbox_events_failed",
        table_name="outbox_events",
        postgresql_where=sa.text("status = 'FAILED'"),
    )
    op.drop_index(
        "idx_outbox_events_stuck",
        table_name="outbox_events",
        postgresql_where=sa.text("status = 'PROCESSING'"),
    )
    op.drop_index(
        "idx_outbox_events_pending",
        table_name="outbox_events",
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.drop_table("outbox_events")
