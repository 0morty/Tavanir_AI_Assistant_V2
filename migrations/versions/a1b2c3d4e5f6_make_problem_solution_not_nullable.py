"""make_problem_solution_not_nullable

Revision ID: a1b2c3d4e5f6
Revises: fd89a3de9dea
Create Date: 2026-09-13 13:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "fd89a3de9dea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Backfill any existing NULL rows before enforcing NOT NULL
    op.execute("UPDATE suggestions SET problem = 'نامشخص' WHERE problem IS NULL")
    op.execute("UPDATE suggestions SET solution = 'نامشخص' WHERE solution IS NULL")

    # 2. Alter columns to NOT NULL
    op.alter_column("suggestions", "problem", existing_type=sa.Text(), nullable=False)
    op.alter_column("suggestions", "solution", existing_type=sa.Text(), nullable=False)


def downgrade() -> None:
    op.alter_column("suggestions", "solution", existing_type=sa.Text(), nullable=True)
    op.alter_column("suggestions", "problem", existing_type=sa.Text(), nullable=True)
