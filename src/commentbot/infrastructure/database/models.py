"""SQLAlchemy models for comment bot."""

from datetime import datetime
from typing import Optional
from uuid import uuid4

from uuid import UUID as PyUUID

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    JSON,
    TypeDecorator,
    CHAR,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class UUID(TypeDecorator):
    """Platform-independent UUID type. Uses CHAR(36) for SQLite."""
    impl = CHAR
    cache_ok = True

    def __init__(self):
        super().__init__(36)

    def process_bind_param(self, value, dialect):
        if value is not None:
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return PyUUID(value)
        return value

from src.commentbot.domain.entities import (
    AccountStatus,
    TaskStatus,
    CampaignStatus,
    ChannelStatus,
    AssignmentStatus,
)


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class AccountModel(Base):
    """Account database model."""

    __tablename__ = "commentbot_accounts"

    id: Mapped[PyUUID] = mapped_column(
        UUID(),
        primary_key=True,
        default=uuid4,
    )
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    session_data: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    tdata_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[AccountStatus] = mapped_column(
        Enum(AccountStatus),
        default=AccountStatus.PENDING,
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    comments_today: Mapped[int] = mapped_column(Integer, default=0)
    daily_limit: Mapped[int] = mapped_column(Integer, default=50)
    owner_id: Mapped[int] = mapped_column(Integer, default=0, index=True)
    phone_code_hash: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)


class CampaignModel(Base):
    """Campaign database model."""

    __tablename__ = "commentbot_campaigns"

    id: Mapped[PyUUID] = mapped_column(
        UUID(),
        primary_key=True,
        default=uuid4,
    )
    name: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[CampaignStatus] = mapped_column(
        Enum(CampaignStatus),
        default=CampaignStatus.DRAFT,
    )
    comment_templates: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    initial_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    min_delay: Mapped[int] = mapped_column(Integer, default=30)
    max_delay: Mapped[int] = mapped_column(Integer, default=120)
    comments_per_post: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    owner_id: Mapped[int] = mapped_column(Integer, default=0, index=True)

    # Stats
    total_comments: Mapped[int] = mapped_column(Integer, default=0)
    successful_comments: Mapped[int] = mapped_column(Integer, default=0)
    failed_comments: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    channels: Mapped[list["ChannelModel"]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
    )


class ChannelModel(Base):
    """Channel database model."""

    __tablename__ = "commentbot_channels"

    id: Mapped[PyUUID] = mapped_column(
        UUID(),
        primary_key=True,
        default=uuid4,
    )
    campaign_id: Mapped[PyUUID] = mapped_column(
        UUID(),
        ForeignKey("commentbot_campaigns.id", ondelete="CASCADE"),
        index=True,
    )
    link: Mapped[str] = mapped_column(String(500), default="")
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    status: Mapped[ChannelStatus] = mapped_column(
        Enum(ChannelStatus),
        default=ChannelStatus.PENDING,
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_post_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    comments_posted: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    owner_id: Mapped[int] = mapped_column(Integer, default=0, index=True)

    # Relationships
    campaign: Mapped["CampaignModel"] = relationship(back_populates="channels")
    assignment: Mapped[Optional["ChannelAssignmentModel"]] = relationship(
        back_populates="channel",
        uselist=False,
    )


class ChannelAssignmentModel(Base):
    """Channel assignment database model."""

    __tablename__ = "commentbot_assignments"

    id: Mapped[PyUUID] = mapped_column(
        UUID(),
        primary_key=True,
        default=uuid4,
    )
    channel_id: Mapped[PyUUID] = mapped_column(
        UUID(),
        ForeignKey("commentbot_channels.id", ondelete="CASCADE"),
        unique=True,  # One assignment per channel
        index=True,
    )
    account_id: Mapped[PyUUID] = mapped_column(
        UUID(),
        ForeignKey("commentbot_accounts.id", ondelete="CASCADE"),
        index=True,
    )
    campaign_id: Mapped[PyUUID] = mapped_column(
        UUID(),
        ForeignKey("commentbot_campaigns.id", ondelete="CASCADE"),
        index=True,
    )
    status: Mapped[AssignmentStatus] = mapped_column(
        Enum(AssignmentStatus),
        default=AssignmentStatus.ACTIVE,
    )
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    swap_count: Mapped[int] = mapped_column(Integer, default=0)
    previous_account_id: Mapped[Optional[PyUUID]] = mapped_column(
        UUID(),
        nullable=True,
    )
    owner_id: Mapped[int] = mapped_column(Integer, default=0, index=True)

    # Relationships
    channel: Mapped["ChannelModel"] = relationship(back_populates="assignment")


class CommentTaskModel(Base):
    """Comment task database model."""

    __tablename__ = "commentbot_tasks"

    id: Mapped[PyUUID] = mapped_column(
        UUID(),
        primary_key=True,
        default=uuid4,
    )
    account_id: Mapped[Optional[PyUUID]] = mapped_column(
        UUID(),
        nullable=True,
    )
    channel_link: Mapped[str] = mapped_column(String(500), default="")
    post_link: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    comment_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus),
        default=TaskStatus.PENDING,
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    owner_id: Mapped[int] = mapped_column(Integer, default=0, index=True)
