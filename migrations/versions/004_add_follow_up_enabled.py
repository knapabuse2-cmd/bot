"""Add follow_up_enabled setting to campaigns.

Adds a flag to control whether follow-up messages are sent for a campaign,
independent of the campaign's active/paused status.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns(table_name)]
    return column_name in cols


def upgrade() -> None:
    # Add follow_up_enabled column to campaigns table
    if not _has_column("campaigns", "sending_follow_up_enabled"):
        op.add_column(
            "campaigns",
            sa.Column("sending_follow_up_enabled", sa.Boolean(), nullable=False, server_default="true"),
        )


def downgrade() -> None:
    if _has_column("campaigns", "sending_follow_up_enabled"):
        op.drop_column("campaigns", "sending_follow_up_enabled")
