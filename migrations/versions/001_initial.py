"""Initial schema.

This migration is intended to represent a *clean baseline* matching the
current ORM models.

Historically the repository contained an out-of-date initial migration and a
second migration with broken revision references. This file supersedes the old
version.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Proxies
    op.create_table(
        "proxies",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("proxy_type", sa.String(length=20), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("password", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("assigned_account_id", sa.String(length=36), nullable=True),
        sa.Column("last_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_check_latency_ms", sa.Integer(), nullable=True),
        sa.Column("fail_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_proxies_status", "proxies", ["status"])
    op.create_index("ix_proxies_assigned_account_id", "proxies", ["assigned_account_id"])

    # Campaigns
    op.create_table(
        "campaigns",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("owner_telegram_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False),
        # Goal
        sa.Column("goal_target_message", sa.Text(), nullable=True),
        sa.Column("goal_target_action", sa.String(length=255), nullable=True),
        sa.Column("goal_target_url", sa.String(length=2048), nullable=True),
        sa.Column("goal_min_messages_before_goal", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("goal_max_messages_before_goal", sa.Integer(), nullable=False, server_default="10"),
        # Prompt
        sa.Column("prompt_system_prompt", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("prompt_first_message_template", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("prompt_goal_hints", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("prompt_forbidden_topics", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("prompt_language", sa.String(length=10), nullable=False, server_default=sa.text("'ru'")),
        sa.Column("prompt_tone", sa.String(length=50), nullable=False, server_default=sa.text("'friendly'")),
        # Stats + settings
        sa.Column("stats", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("account_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("ai_model", sa.String(length=100), nullable=False, server_default=sa.text("'gpt-4o-mini'")),
        sa.Column("ai_temperature", sa.Float(), nullable=False, server_default="0.7"),
        sa.Column("ai_max_tokens", sa.Integer(), nullable=False, server_default="500"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_campaigns_status", "campaigns", ["status"])

    # Accounts
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("phone", sa.String(length=50), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("bio", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("session_data", sa.LargeBinary(), nullable=True),
        sa.Column("proxy_id", sa.String(length=36), sa.ForeignKey("proxies.id"), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("campaign_id", sa.String(length=36), sa.ForeignKey("campaigns.id"), nullable=True),
        # Schedule
        sa.Column("schedule_start_time", sa.String(length=8), nullable=False, server_default=sa.text("'09:00'")),
        sa.Column("schedule_end_time", sa.String(length=8), nullable=False, server_default=sa.text("'21:00'")),
        sa.Column("schedule_active_days", sa.JSON(), nullable=False, server_default=sa.text("'[0,1,2,3,4,5,6]'")),
        sa.Column("schedule_timezone", sa.String(length=64), nullable=False, server_default=sa.text("'UTC'")),
        # Limits
        sa.Column("limits", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        # Counters
        sa.Column("hourly_messages_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("daily_conversations_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_messages_sent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_conversations_started", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_activity", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_hourly_reset", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_daily_reset", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("phone", name="uq_accounts_phone"),
        sa.UniqueConstraint("telegram_id", name="uq_accounts_telegram_id"),
    )
    op.create_index("ix_accounts_status", "accounts", ["status"])
    op.create_index("ix_accounts_campaign_id", "accounts", ["campaign_id"])

    # Targets
    op.create_table(
        "user_targets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("campaign_id", sa.String(length=36), sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("assigned_account_id", sa.String(length=36), sa.ForeignKey("accounts.id"), nullable=True),
        # Cross-reference to dialogue (no FK to avoid circular dependency)
        sa.Column("dialogue_id", sa.String(length=36), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(length=50), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("notes", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("contact_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_contact_attempt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_contact_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fail_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_user_targets_campaign_id", "user_targets", ["campaign_id"])
    op.create_index("ix_user_targets_status", "user_targets", ["status"])
    op.create_index("ix_user_targets_assigned_account_id", "user_targets", ["assigned_account_id"])
    op.create_index("ix_user_targets_scheduled_contact_at", "user_targets", ["scheduled_contact_at"])
    op.create_index("ix_user_targets_telegram_id", "user_targets", ["telegram_id"])
    op.create_index("ix_user_targets_username", "user_targets", ["username"])
    op.create_unique_constraint(
        "uq_user_targets_campaign_telegram",
        "user_targets",
        ["campaign_id", "telegram_id"],
    )

    # Dialogues
    op.create_table(
        "dialogues",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("account_id", sa.String(length=36), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("campaign_id", sa.String(length=36), sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column("target_user_id", sa.String(length=36), sa.ForeignKey("user_targets.id"), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_username", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("goal_message_sent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("goal_message_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("last_user_response_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sentiment_score", sa.Float(), nullable=True),
        sa.Column("interest_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("link_sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("creative_sent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("fail_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("account_id", "telegram_user_id", name="uq_dialogues_account_user"),
    )
    op.create_index("ix_dialogues_account_id", "dialogues", ["account_id"])
    op.create_index("ix_dialogues_campaign_id", "dialogues", ["campaign_id"])
    op.create_index("ix_dialogues_target_user_id", "dialogues", ["target_user_id"])
    op.create_index("ix_dialogues_status", "dialogues", ["status"])
    op.create_index("ix_dialogues_next_action_at", "dialogues", ["next_action_at"])

    # Messages
    op.create_table(
        "messages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("dialogue_id", sa.String(length=36), sa.ForeignKey("dialogues.id"), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("ai_generated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_follow_up", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_messages_dialogue_id", "messages", ["dialogue_id"])
    op.create_index("ix_messages_timestamp", "messages", ["timestamp"])


def downgrade() -> None:
    op.drop_index("ix_messages_timestamp", table_name="messages")
    op.drop_index("ix_messages_dialogue_id", table_name="messages")
    op.drop_table("messages")

    op.drop_index("ix_dialogues_next_action_at", table_name="dialogues")
    op.drop_index("ix_dialogues_status", table_name="dialogues")
    op.drop_index("ix_dialogues_target_user_id", table_name="dialogues")
    op.drop_index("ix_dialogues_campaign_id", table_name="dialogues")
    op.drop_index("ix_dialogues_account_id", table_name="dialogues")
    op.drop_table("dialogues")

    op.drop_constraint("uq_user_targets_campaign_telegram", "user_targets", type_="unique")
    op.drop_index("ix_user_targets_username", table_name="user_targets")
    op.drop_index("ix_user_targets_telegram_id", table_name="user_targets")
    op.drop_index("ix_user_targets_scheduled_contact_at", table_name="user_targets")
    op.drop_index("ix_user_targets_assigned_account_id", table_name="user_targets")
    op.drop_index("ix_user_targets_status", table_name="user_targets")
    op.drop_index("ix_user_targets_campaign_id", table_name="user_targets")
    op.drop_table("user_targets")

    op.drop_index("ix_accounts_campaign_id", table_name="accounts")
    op.drop_index("ix_accounts_status", table_name="accounts")
    op.drop_table("accounts")

    op.drop_index("ix_campaigns_status", table_name="campaigns")
    op.drop_table("campaigns")

    op.drop_index("ix_proxies_assigned_account_id", table_name="proxies")
    op.drop_index("ix_proxies_status", table_name="proxies")
    op.drop_table("proxies")
