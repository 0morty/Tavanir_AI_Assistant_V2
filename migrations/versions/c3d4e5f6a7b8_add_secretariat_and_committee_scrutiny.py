"""add_secretariat_and_committee_scrutiny

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-19 10:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        'suggestions',
        'scrutiny',
        new_column_name='committee_scrutiny',
        existing_type=sa.Text(),
        existing_nullable=True,
    )
    op.add_column(
        'suggestions',
        sa.Column('committee_scrutiny_id', sa.SmallInteger(), nullable=True)
    )
    op.add_column(
        'suggestions',
        sa.Column('secretariat_scrutiny_id', sa.SmallInteger(), nullable=True)
    )
    op.add_column(
        'suggestions',
        sa.Column('secretariat_scrutiny', sa.Text(), nullable=True)
    )
    op.add_column(
        'suggestions',
        sa.Column('secretariat_comment', sa.Text(), nullable=True)
    )
    op.create_index(
        op.f('ix_suggestions_committee_scrutiny_id'),
        'suggestions',
        ['committee_scrutiny_id'],
        unique=False
    )
    op.create_index(
        op.f('ix_suggestions_secretariat_scrutiny_id'),
        'suggestions',
        ['secretariat_scrutiny_id'],
        unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_suggestions_secretariat_scrutiny_id'), table_name='suggestions')
    op.drop_index(op.f('ix_suggestions_committee_scrutiny_id'), table_name='suggestions')
    op.drop_column('suggestions', 'secretariat_comment')
    op.drop_column('suggestions', 'secretariat_scrutiny')
    op.drop_column('suggestions', 'secretariat_scrutiny_id')
    op.drop_column('suggestions', 'committee_scrutiny_id')
    op.alter_column(
        'suggestions',
        'committee_scrutiny',
        new_column_name='scrutiny',
        existing_type=sa.Text(),
        existing_nullable=True,
    )

