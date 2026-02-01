"""Add UNIQUE constraint on accounts.proxy_id.

Enforces 1:1 relationship between accounts and proxies — each proxy can only
be assigned to a single account.  This prevents accidental proxy sharing which
would correlate multiple Telegram sessions to the same IP address.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_account_proxy_id",
        "accounts",
        ["proxy_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_account_proxy_id", "accounts", type_="unique")
