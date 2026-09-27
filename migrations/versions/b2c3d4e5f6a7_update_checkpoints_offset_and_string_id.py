"""update_checkpoints_offset_and_string_id

Revision ID: b2c3d4e5f6a7
Revises: 950cffb2c67c
Create Date: 2026-09-16 09:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = '950cffb2c67c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'ingestion_checkpoints',
        sa.Column('last_offset', sa.BigInteger(), nullable=False, server_default='0')
    )
    op.alter_column(
        'ingestion_checkpoints',
        'last_processed_id',
        existing_type=sa.BigInteger(),
        type_=sa.String(length=100),
        nullable=True,
        postgresql_using='last_processed_id::text'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        'ingestion_checkpoints',
        'last_processed_id',
        existing_type=sa.String(length=100),
        type_=sa.BigInteger(),
        nullable=False,
        postgresql_using='last_processed_id::bigint'
    )
    op.drop_column('ingestion_checkpoints', 'last_offset')
