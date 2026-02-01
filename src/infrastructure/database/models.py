"""SQLAlchemy ORM models.

Important note about portability
-------------------------------
The production database is PostgreSQL, but the test-suite uses SQLite.
Historically the project used PostgreSQL-only types (UUID/ARRAY/JSONB) which
made tests and local development fail.

The models below use portable types (JSON + a GUID TypeDecorator) so they can
be created on SQLite while still using native UUID on PostgreSQL.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .connection import Base
from .types import GUID


class TelegramAppModel(Base):
    """Telegram API application credentials."""

    __tablename__ = "telegram_apps"

    id: Mapped[GUID] = mapped_column(GUID(), primary_key=True)

    api_id: Mapped[int] = mapped_column(Integer, nullable=False)
    api_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Limits
    max_accounts: Mapped[int] = mapped_column(Integer, nullable=False, default=25)
    current_account_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Metadata
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    accounts: Mapped[list["AccountModel"]] = relationship(
        back_populates="telegram_app",
        foreign_keys="AccountModel.telegram_app_id",
    )

    __table_args__ = (
        UniqueConstraint("api_id", name="uq_telegram_app_api_id"),
    )


class ProxyModel(Base):
    """Proxy configuration."""

    __tablename__ = "proxies"

    id: Mapped[GUID] = mapped_column(GUID(), primary_key=True)

    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    proxy_type: Mapped[str] = mapped_column(String(50), nullable=False)

    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    assigned_account_id: Mapped[Optional[GUID]] = mapped_column(
        GUID(), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )

    last_check_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_check_latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    #
    # IMPORTANT:
    # There are *two* foreign-key paths between proxies <-> accounts:
    #   1) AccountModel.proxy_id -> proxies.id (many accounts can use one proxy)
    #   2) ProxyModel.assigned_account_id -> accounts.id ("currently assigned" account)
    #
    # Without explicit `foreign_keys=...`, SQLAlchemy can't determine which FK
    # should be used for the collection relationship and raises
    # AmbiguousForeignKeysError during mapper configuration.
    accounts: Mapped[list["AccountModel"]] = relationship(
        back_populates="proxy",
        foreign_keys="AccountModel.proxy_id",
    )

    assigned_account: Mapped[Optional["AccountModel"]] = relationship(
        "AccountModel",
        foreign_keys=[assigned_account_id],
    )

    __table_args__ = (
        UniqueConstraint("host", "port", name="uq_proxy_address"),
    )


class AccountModel(Base):
    """Telegram worker account."""

    __tablename__ = "accounts"

    id: Mapped[GUID] = mapped_column(GUID(), primary_key=True)

    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)

    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    bio: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_premium: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    session_data: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)

    # How the account was added: "phone", "json_session", "tdata"
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="phone")

    proxy_id: Mapped[Optional[GUID]] = mapped_column(
        GUID(), ForeignKey("proxies.id", ondelete="SET NULL"), nullable=True, unique=True
    )

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="inactive")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    campaign_id: Mapped[Optional[GUID]] = mapped_column(
        GUID(), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True
    )
    group_id: Mapped[Optional[GUID]] = mapped_column(
        GUID(), ForeignKey("account_groups.id", ondelete="SET NULL"), nullable=True
    )

    # Telegram API app credentials
    telegram_app_id: Mapped[Optional[GUID]] = mapped_column(
        GUID(), ForeignKey("telegram_apps.id", ondelete="SET NULL"), nullable=True
    )

    # Schedule fields
    schedule_start_time: Mapped[str] = mapped_column(String(5), nullable=False, default="09:00")
    schedule_end_time: Mapped[str] = mapped_column(String(5), nullable=False, default="21:00")
    schedule_active_days: Mapped[list[int]] = mapped_column(
        MutableList.as_mutable(JSON),
        nullable=False,
        default=lambda: [0, 1, 2, 3, 4, 5, 6],
    )
    schedule_timezone: Mapped[str] = mapped_column(String(50), nullable=False, default="UTC")

    # Limits as JSON dict
    limits: Mapped[dict] = mapped_column(
        MutableDict.as_mutable(JSON),
        nullable=False,
        default=dict,
    )

    # Counters
    hourly_messages_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hourly_responses_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    daily_conversations_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Lifetime totals (used by API/admin)
    total_messages_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_conversations_started: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    last_activity: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_hourly_reset: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_daily_reset: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Per-account randomized reset hour (0-23) to avoid synchronized spikes
    # Each account resets at its own hour instead of all at midnight
    daily_reset_hour: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    proxy: Mapped[Optional[ProxyModel]] = relationship(
        back_populates="accounts",
        foreign_keys=[proxy_id],
    )
    campaign: Mapped[Optional["CampaignModel"]] = relationship(back_populates="accounts")
    group: Mapped[Optional["AccountGroupModel"]] = relationship(
        back_populates="direct_accounts",
        foreign_keys=[group_id],
    )
    telegram_app: Mapped[Optional["TelegramAppModel"]] = relationship(
        back_populates="accounts",
        foreign_keys=[telegram_app_id],
    )
    dialogues: Mapped[list["DialogueModel"]] = relationship(back_populates="account")


class CampaignModel(Base):
    """Outreach campaign."""

    __tablename__ = "campaigns"

    id: Mapped[GUID] = mapped_column(GUID(), primary_key=True)

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    owner_telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")

    # Goal configuration
    goal_target_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    goal_target_action: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    goal_target_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    goal_min_messages_before_goal: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    goal_max_messages_before_goal: Mapped[int] = mapped_column(Integer, nullable=False, default=10)

    # Prompt configuration
    prompt_system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prompt_first_message_template: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prompt_goal_hints: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        nullable=False,
        default=list,
    )
    prompt_forbidden_topics: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        nullable=False,
        default=list,
    )
    prompt_language: Mapped[str] = mapped_column(String(10), nullable=False, default="ru")
    prompt_tone: Mapped[str] = mapped_column(String(50), nullable=False, default="friendly")

    # Stats as JSON dict
    stats: Mapped[dict] = mapped_column(
        MutableDict.as_mutable(JSON),
        nullable=False,
        default=dict,
    )

    # Store account ids as JSON list to keep compatibility with old schema
    account_ids: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        nullable=False,
        default=list,
    )

    # AI settings
    ai_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ai_temperature: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ai_max_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Sending settings (for batch first messages)
    sending_interval_hours: Mapped[float] = mapped_column(Float, nullable=False, default=13.0)
    sending_messages_per_batch: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    sending_delay_min: Mapped[int] = mapped_column(Integer, nullable=False, default=17)
    sending_delay_max: Mapped[int] = mapped_column(Integer, nullable=False, default=23)
    sending_last_batch_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sending_targets_file_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    sending_follow_up_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    accounts: Mapped[list[AccountModel]] = relationship(back_populates="campaign")
    targets: Mapped[list["UserTargetModel"]] = relationship(back_populates="campaign")
    dialogues: Mapped[list["DialogueModel"]] = relationship(back_populates="campaign")


class UserTargetModel(Base):
    """Target user for outreach."""

    __tablename__ = "user_targets"

    id: Mapped[GUID] = mapped_column(GUID(), primary_key=True)

    campaign_id: Mapped[GUID] = mapped_column(
        GUID(), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )

    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    first_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    last_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")

    assigned_account_id: Mapped[Optional[GUID]] = mapped_column(
        GUID(), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )

    dialogue_id: Mapped[Optional[GUID]] = mapped_column(GUID(), nullable=True)

    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    tags: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        nullable=False,
        default=list,
    )

    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    contact_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_contact_attempt: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_contact_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    fail_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    campaign: Mapped[CampaignModel] = relationship(back_populates="targets")
    assigned_account: Mapped[Optional[AccountModel]] = relationship()


class DialogueModel(Base):
    """Conversation between an account and a target."""

    __tablename__ = "dialogues"

    id: Mapped[GUID] = mapped_column(GUID(), primary_key=True)

    account_id: Mapped[GUID] = mapped_column(
        GUID(), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[GUID] = mapped_column(
        GUID(), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )

    target_user_id: Mapped[Optional[GUID]] = mapped_column(
        GUID(), ForeignKey("user_targets.id", ondelete="SET NULL"), nullable=True
    )

    telegram_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    telegram_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="initiated")

    goal_message_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    goal_message_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    next_action_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    last_user_response_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    sentiment_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    interest_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    link_sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Natural-dialogue flags
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    creative_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    fail_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    account: Mapped[AccountModel] = relationship(back_populates="dialogues")
    campaign: Mapped[CampaignModel] = relationship(back_populates="dialogues")
    target_user: Mapped[Optional[UserTargetModel]] = relationship()

    messages: Mapped[list["MessageModel"]] = relationship(
        back_populates="dialogue",
        order_by="MessageModel.timestamp",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # Avoid duplicate dialogues for the same account+telegram user id
        UniqueConstraint("account_id", "telegram_user_id", name="uq_dialogue_account_user"),
    )


class MessageModel(Base):
    """Single message in a dialogue."""

    __tablename__ = "messages"

    id: Mapped[GUID] = mapped_column(GUID(), primary_key=True)

    dialogue_id: Mapped[GUID] = mapped_column(
        GUID(), ForeignKey("dialogues.id", ondelete="CASCADE"), nullable=False
    )

    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    telegram_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    ai_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    is_follow_up: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    dialogue: Mapped[DialogueModel] = relationship(back_populates="messages")


# =============================================================================
# Warmup System Models
# =============================================================================


class AccountGroupModel(Base):
    """Group of accounts for batch operations."""

    __tablename__ = "account_groups"

    id: Mapped[GUID] = mapped_column(GUID(), primary_key=True)

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Default warmup profile for accounts in this group
    default_warmup_profile_id: Mapped[Optional[GUID]] = mapped_column(
        GUID(), ForeignKey("warmup_profiles.id", ondelete="SET NULL"), nullable=True
    )

    # Default proxy group for accounts in this group
    default_proxy_group_id: Mapped[Optional[GUID]] = mapped_column(
        GUID(), ForeignKey("proxy_groups.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    # Direct accounts via group_id FK on accounts table
    direct_accounts: Mapped[list["AccountModel"]] = relationship(
        back_populates="group",
        foreign_keys="AccountModel.group_id",
    )
    # Legacy many-to-many (for warmup system)
    accounts: Mapped[list["AccountGroupMembershipModel"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    default_warmup_profile: Mapped[Optional["WarmupProfileModel"]] = relationship()
    default_proxy_group: Mapped[Optional["ProxyGroupModel"]] = relationship()


class AccountGroupMembershipModel(Base):
    """Many-to-many relationship between accounts and groups."""

    __tablename__ = "account_group_memberships"

    id: Mapped[GUID] = mapped_column(GUID(), primary_key=True)

    account_id: Mapped[GUID] = mapped_column(
        GUID(), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[GUID] = mapped_column(
        GUID(), ForeignKey("account_groups.id", ondelete="CASCADE"), nullable=False
    )

    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    account: Mapped[AccountModel] = relationship()
    group: Mapped[AccountGroupModel] = relationship(back_populates="accounts")

    __table_args__ = (
        UniqueConstraint("account_id", "group_id", name="uq_account_group_membership"),
    )


class ProxyGroupModel(Base):
    """Group of proxies (e.g., by country/region)."""

    __tablename__ = "proxy_groups"

    id: Mapped[GUID] = mapped_column(GUID(), primary_key=True)

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Country/region code (e.g., "DE", "US", "RU")
    country_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    proxies: Mapped[list["ProxyGroupMembershipModel"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class ProxyGroupMembershipModel(Base):
    """Many-to-many relationship between proxies and groups."""

    __tablename__ = "proxy_group_memberships"

    id: Mapped[GUID] = mapped_column(GUID(), primary_key=True)

    proxy_id: Mapped[GUID] = mapped_column(
        GUID(), ForeignKey("proxies.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[GUID] = mapped_column(
        GUID(), ForeignKey("proxy_groups.id", ondelete="CASCADE"), nullable=False
    )

    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    proxy: Mapped[ProxyModel] = relationship()
    group: Mapped[ProxyGroupModel] = relationship(back_populates="proxies")

    __table_args__ = (
        UniqueConstraint("proxy_id", "group_id", name="uq_proxy_group_membership"),
    )


class InterestCategoryModel(Base):
    """Interest category for warmup (e.g., crypto, tech, gaming)."""

    __tablename__ = "interest_categories"

    id: Mapped[GUID] = mapped_column(GUID(), primary_key=True)

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Keywords associated with this interest (for matching)
    keywords: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        nullable=False,
        default=list,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    channels: Mapped[list["WarmupChannelModel"]] = relationship(back_populates="category")
    groups: Mapped[list["WarmupGroupModel"]] = relationship(back_populates="category")


class WarmupChannelModel(Base):
    """Channel for warmup activities (subscribe, view, react)."""

    __tablename__ = "warmup_channels"

    id: Mapped[GUID] = mapped_column(GUID(), primary_key=True)

    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    category_id: Mapped[Optional[GUID]] = mapped_column(
        GUID(), ForeignKey("interest_categories.id", ondelete="SET NULL"), nullable=True
    )

    # Language of the channel (for matching with account persona)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")

    # Channel stats (updated periodically)
    subscriber_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_post_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    category: Mapped[Optional[InterestCategoryModel]] = relationship(back_populates="channels")


class WarmupGroupModel(Base):
    """Telegram group for warmup activities (join, chat, react)."""

    __tablename__ = "warmup_groups"

    id: Mapped[GUID] = mapped_column(GUID(), primary_key=True)

    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    category_id: Mapped[Optional[GUID]] = mapped_column(
        GUID(), ForeignKey("interest_categories.id", ondelete="SET NULL"), nullable=True
    )

    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")

    # Whether accounts can write messages in this group
    can_write: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Member count (updated periodically)
    member_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    category: Mapped[Optional[InterestCategoryModel]] = relationship(back_populates="groups")


class WarmupProfileModel(Base):
    """Warmup profile template with stages and limits."""

    __tablename__ = "warmup_profiles"

    id: Mapped[GUID] = mapped_column(GUID(), primary_key=True)

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Total days for warmup
    total_days: Mapped[int] = mapped_column(Integer, nullable=False, default=21)

    # Stages configuration as JSON
    # Format: [
    #   {"stage": 1, "days": 3, "daily_messages": 0, "join_channels": 5, "join_groups": 0, "reactions_per_day": 10},
    #   {"stage": 2, "days": 4, "daily_messages": 5, "join_channels": 5, "join_groups": 2, "reactions_per_day": 20},
    #   ...
    # ]
    stages: Mapped[list[dict]] = mapped_column(
        MutableList.as_mutable(JSON),
        nullable=False,
        default=list,
    )

    # Activity simulation settings
    min_session_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    max_session_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)

    # Human-like behavior settings
    typing_speed_cpm: Mapped[int] = mapped_column(Integer, nullable=False, default=150)  # chars per minute
    reaction_probability: Mapped[float] = mapped_column(Float, nullable=False, default=0.3)

    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )


class AccountWarmupModel(Base):
    """Warmup progress for an account."""

    __tablename__ = "account_warmups"

    id: Mapped[GUID] = mapped_column(GUID(), primary_key=True)

    account_id: Mapped[GUID] = mapped_column(
        GUID(), ForeignKey("accounts.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    profile_id: Mapped[Optional[GUID]] = mapped_column(
        GUID(), ForeignKey("warmup_profiles.id", ondelete="SET NULL"), nullable=True
    )

    # Current stage (1-5 typically)
    stage: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    # pending, active, paused, completed, failed

    # Timestamps
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    stage_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Progress counters
    channels_joined: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    groups_joined: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reactions_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    messages_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_session_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Daily counters (reset daily)
    daily_reactions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    daily_messages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    daily_joins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_daily_reset: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Per-account randomized reset hour (0-23) to avoid synchronized spikes
    daily_reset_hour: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Dynamic message limit based on warmup stage
    current_daily_message_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Error tracking
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    flood_wait_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    account: Mapped[AccountModel] = relationship()
    profile: Mapped[Optional[WarmupProfileModel]] = relationship()
    subscriptions: Mapped[list["AccountSubscriptionModel"]] = relationship(
        back_populates="warmup", cascade="all, delete-orphan"
    )


class AccountPersonaModel(Base):
    """Account persona for natural behavior simulation."""

    __tablename__ = "account_personas"

    id: Mapped[GUID] = mapped_column(GUID(), primary_key=True)

    account_id: Mapped[GUID] = mapped_column(
        GUID(), ForeignKey("accounts.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    # Interests (list of category IDs or names)
    interests: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        nullable=False,
        default=list,
    )

    # Activity pattern: "early_bird", "night_owl", "office_hours", "random"
    activity_pattern: Mapped[str] = mapped_column(String(50), nullable=False, default="office_hours")

    # Timezone for activity simulation (derived from proxy or set manually)
    timezone: Mapped[str] = mapped_column(String(50), nullable=False, default="UTC")

    # Language preference
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")

    # Behavior parameters
    typing_speed: Mapped[int] = mapped_column(Integer, nullable=False, default=150)  # chars per minute
    reaction_probability: Mapped[float] = mapped_column(Float, nullable=False, default=0.3)
    min_response_delay: Mapped[int] = mapped_column(Integer, nullable=False, default=5)  # seconds
    max_response_delay: Mapped[int] = mapped_column(Integer, nullable=False, default=60)

    # Active hours (JSON: {"start": 9, "end": 23})
    active_hours: Mapped[dict] = mapped_column(
        MutableDict.as_mutable(JSON),
        nullable=False,
        default=lambda: {"start": 9, "end": 22},
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    account: Mapped[AccountModel] = relationship()


class AccountSubscriptionModel(Base):
    """Track account subscriptions to channels/groups."""

    __tablename__ = "account_subscriptions"

    id: Mapped[GUID] = mapped_column(GUID(), primary_key=True)

    warmup_id: Mapped[GUID] = mapped_column(
        GUID(), ForeignKey("account_warmups.id", ondelete="CASCADE"), nullable=False
    )

    # Either channel or group (one of these will be set)
    channel_id: Mapped[Optional[GUID]] = mapped_column(
        GUID(), ForeignKey("warmup_channels.id", ondelete="CASCADE"), nullable=True
    )
    group_id: Mapped[Optional[GUID]] = mapped_column(
        GUID(), ForeignKey("warmup_groups.id", ondelete="CASCADE"), nullable=True
    )

    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    left_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    warmup: Mapped[AccountWarmupModel] = relationship(back_populates="subscriptions")
    channel: Mapped[Optional[WarmupChannelModel]] = relationship()
    group: Mapped[Optional[WarmupGroupModel]] = relationship()

    __table_args__ = (
        UniqueConstraint("warmup_id", "channel_id", name="uq_account_channel_subscription"),
        UniqueConstraint("warmup_id", "group_id", name="uq_account_group_subscription"),
    )


class WarmupActivityLogModel(Base):
    """Log of warmup activities for analytics."""

    __tablename__ = "warmup_activity_logs"

    id: Mapped[GUID] = mapped_column(GUID(), primary_key=True)

    account_id: Mapped[GUID] = mapped_column(
        GUID(), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Activity type: "channel_join", "group_join", "reaction", "message", "scroll", "view"
    activity_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Target (channel/group username or ID)
    target: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Additional details as JSON
    details: Mapped[Optional[dict]] = mapped_column(
        MutableDict.as_mutable(JSON), nullable=True
    )

    # Success/failure
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, index=True
    )

