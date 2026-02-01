"""add_is_premium column

Revision ID: 005
Revises: 004
Create Date: 2026-01-07 21:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    # Add is_premium column with server default for existing rows
    op.add_column('accounts', sa.Column('is_premium', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column('accounts', 'is_premium')
