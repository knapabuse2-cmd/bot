"""Add daily_reset_hour to accounts and warmups.

Each account/warmup gets a randomized reset hour (0-23) to avoid all accounts
resetting their daily counters at the same time (UTC midnight). This prevents
synchronized activity spikes that could be detected by Telegram's anti-spam.

The reset hour is generated deterministically from the account_id hash,
ensuring consistency across restarts while distributing resets evenly.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add daily_reset_hour to accounts table
    op.add_column(
        "accounts",
        sa.Column("daily_reset_hour", sa.Integer(), nullable=False, server_default="0"),
    )

    # Add daily_reset_hour to account_warmups table
    op.add_column(
        "account_warmups",
        sa.Column("daily_reset_hour", sa.Integer(), nullable=False, server_default="0"),
    )

    # Initialize reset hours based on account ID hash
    # This distributes accounts evenly across 24 hours
    op.execute("""
        UPDATE accounts
        SET daily_reset_hour = (
            ('x' || substring(md5(id::text) from 1 for 2))::bit(8)::int % 24
        )
    """)

    op.execute("""
        UPDATE account_warmups
        SET daily_reset_hour = (
            ('x' || substring(md5(account_id::text) from 1 for 2))::bit(8)::int % 24
        )
    """)


def downgrade() -> None:
    op.drop_column("account_warmups", "daily_reset_hour")
    op.drop_column("accounts", "daily_reset_hour")
