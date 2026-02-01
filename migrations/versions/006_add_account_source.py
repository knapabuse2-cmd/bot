"""add_account_source column

Revision ID: 006
Revises: 005
Create Date: 2026-01-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    # Add source column to track how account was added (phone, json_session, tdata)
    # Default to 'phone' for existing accounts
    op.add_column('accounts', sa.Column('source', sa.String(50), nullable=False, server_default='phone'))


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column('accounts', 'source')
