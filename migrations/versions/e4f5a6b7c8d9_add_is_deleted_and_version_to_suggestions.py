"""add_is_deleted_and_version_to_suggestions

Revision ID: e4f5a6b7c8d9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-20 10:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "suggestions",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "suggestions",
        sa.Column(
            "version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_suggestions_active",
        "suggestions",
        ["id"],
        unique=False,
        postgresql_where=sa.text("is_deleted = FALSE"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_suggestions_active",
        table_name="suggestions",
        postgresql_where=sa.text("is_deleted = FALSE"),
    )
    op.drop_column("suggestions", "version")
    op.drop_column("suggestions", "is_deleted")
