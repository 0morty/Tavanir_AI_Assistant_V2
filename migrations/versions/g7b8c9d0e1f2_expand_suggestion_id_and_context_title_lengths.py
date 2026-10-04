"""expand_suggestion_id_and_context_title_lengths

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-10-04 16:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "g7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Expand suggestion id to 128 chars and context_title to 512 chars."""
    op.alter_column(
        "suggestions",
        "id",
        type_=sa.String(length=128),
        existing_type=sa.String(length=64),
        existing_nullable=False,
    )
    op.alter_column(
        "suggestions",
        "context_title",
        type_=sa.String(length=512),
        existing_type=sa.String(length=255),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Revert suggestion id and context_title lengths."""
    op.alter_column(
        "suggestions",
        "context_title",
        type_=sa.String(length=255),
        existing_type=sa.String(length=512),
        existing_nullable=True,
    )
    op.alter_column(
        "suggestions",
        "id",
        type_=sa.String(length=64),
        existing_type=sa.String(length=128),
        existing_nullable=False,
    )
