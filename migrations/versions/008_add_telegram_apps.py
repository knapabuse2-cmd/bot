"""Add telegram_apps table for multiple API credentials.

This migration adds support for using multiple Telegram API applications
to distribute accounts across different api_id/api_hash pairs.

Recommendation: 20-30 accounts per API ID to avoid detection.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create telegram_apps table
    op.create_table(
        "telegram_apps",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("api_id", sa.Integer(), nullable=False),
        sa.Column("api_hash", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("max_accounts", sa.Integer(), nullable=False, server_default="25"),
        sa.Column("current_account_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("api_id", name="uq_telegram_app_api_id"),
    )
    op.create_index("ix_telegram_apps_is_active", "telegram_apps", ["is_active"])

    # Add telegram_app_id to accounts
    op.add_column(
        "accounts",
        sa.Column(
            "telegram_app_id",
            sa.String(length=36),
            sa.ForeignKey("telegram_apps.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_accounts_telegram_app_id", "accounts", ["telegram_app_id"])


def downgrade() -> None:
    op.drop_index("ix_accounts_telegram_app_id", table_name="accounts")
    op.drop_column("accounts", "telegram_app_id")

    op.drop_index("ix_telegram_apps_is_active", table_name="telegram_apps")
    op.drop_table("telegram_apps")
