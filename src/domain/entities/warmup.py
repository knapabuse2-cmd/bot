"""
Warmup system entities.

Entities for account warmup, including:
- WarmupProfile: Templates for warmup stages
- AccountWarmup: Progress tracking for an account
- AccountPersona: Simulated personality for natural behavior
- WarmupChannel/WarmupGroup: Targets for warmup activities
- AccountGroup/ProxyGroup: Grouping for batch operations
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from .base import Entity, AggregateRoot


class WarmupStatus(str, Enum):
    """Warmup process status."""

    PENDING = "pending"       # Not started yet
    ACTIVE = "active"         # Currently warming up
    PAUSED = "paused"         # Temporarily paused
    COMPLETED = "completed"   # Warmup finished
    FAILED = "failed"         # Error occurred


class ActivityPattern(str, Enum):
    """Activity patterns for persona."""

    EARLY_BIRD = "early_bird"     # Active 6-14
    OFFICE_HOURS = "office_hours"  # Active 9-18
    NIGHT_OWL = "night_owl"       # Active 18-02
    RANDOM = "random"             # Random times


@dataclass
class WarmupStage:
    """Single stage configuration in a warmup profile."""

    stage: int
    days: int
    daily_messages: int = 0
    join_channels: int = 0
    join_groups: int = 0
    reactions_per_day: int = 0
    can_outreach: bool = False  # Whether can do cold outreach


@dataclass
class WarmupProfile(Entity):
    """
    Warmup profile template.

    Defines stages and limits for account warmup process.
    """

    name: str = ""
    description: Optional[str] = None

    total_days: int = 21
    stages: list[WarmupStage] = field(default_factory=list)

    # Activity simulation settings
    min_session_duration_minutes: int = 10
    max_session_duration_minutes: int = 60

    # Human-like behavior
    typing_speed_cpm: int = 150  # characters per minute
    reaction_probability: float = 0.3

    is_default: bool = False

    def get_stage_config(self, stage_num: int) -> Optional[WarmupStage]:
        """Get configuration for a specific stage."""
        for stage in self.stages:
            if stage.stage == stage_num:
                return stage
        return None

    def get_stage_for_day(self, day: int) -> Optional[WarmupStage]:
        """Get stage configuration for a specific day of warmup."""
        days_passed = 0
        for stage in sorted(self.stages, key=lambda s: s.stage):
            days_passed += stage.days
            if day <= days_passed:
                return stage
        return self.stages[-1] if self.stages else None


@dataclass
class AccountWarmup(AggregateRoot):
    """
    Warmup progress for an account.

    Tracks the current stage, counters, and status of the warmup process.
    """

    account_id: UUID = field(default_factory=lambda: UUID(int=0))
    profile_id: Optional[UUID] = None

    stage: int = 1
    status: WarmupStatus = WarmupStatus.PENDING

    # Timestamps
    started_at: Optional[datetime] = None
    stage_started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    last_activity_at: Optional[datetime] = None

    # Total counters
    channels_joined: int = 0
    groups_joined: int = 0
    reactions_sent: int = 0
    messages_sent: int = 0
    total_session_minutes: int = 0

    # Daily counters (reset daily)
    daily_reactions: int = 0
    daily_messages: int = 0
    daily_joins: int = 0
    last_daily_reset: Optional[datetime] = None

    # Current limits
    current_daily_message_limit: int = 0

    # Error tracking
    error_message: Optional[str] = None
    flood_wait_until: Optional[datetime] = None

    def start(self) -> None:
        """Start warmup process."""
        self.status = WarmupStatus.ACTIVE
        self.started_at = datetime.utcnow()
        self.stage_started_at = datetime.utcnow()
        self.increment_version()

    def pause(self) -> None:
        """Pause warmup process."""
        self.status = WarmupStatus.PAUSED
        self.increment_version()

    def resume(self) -> None:
        """Resume warmup process."""
        self.status = WarmupStatus.ACTIVE
        self.increment_version()

    def advance_stage(self, new_stage: int) -> None:
        """Move to next stage."""
        self.stage = new_stage
        self.stage_started_at = datetime.utcnow()
        self.increment_version()

    def complete(self) -> None:
        """Mark warmup as completed."""
        self.status = WarmupStatus.COMPLETED
        self.completed_at = datetime.utcnow()
        self.increment_version()

    def set_error(self, message: str) -> None:
        """Set error status."""
        self.status = WarmupStatus.FAILED
        self.error_message = message
        self.increment_version()

    def reset_daily_counters(self) -> None:
        """Reset daily counters."""
        self.daily_reactions = 0
        self.daily_messages = 0
        self.daily_joins = 0
        self.last_daily_reset = datetime.utcnow()

    def record_activity(self) -> None:
        """Record that activity happened."""
        self.last_activity_at = datetime.utcnow()
        self.touch()

    def can_do_activity(self) -> bool:
        """Check if warmup can perform activities now."""
        if self.status != WarmupStatus.ACTIVE:
            return False
        if self.flood_wait_until and self.flood_wait_until > datetime.utcnow():
            return False
        return True


@dataclass
class AccountPersona(Entity):
    """
    Account persona for natural behavior simulation.

    Defines personality traits that affect how the account behaves.
    """

    account_id: UUID = field(default_factory=lambda: UUID(int=0))

    interests: list[str] = field(default_factory=list)
    activity_pattern: ActivityPattern = ActivityPattern.OFFICE_HOURS
    timezone: str = "UTC"
    language: str = "en"

    # Behavior parameters
    typing_speed: int = 150  # chars per minute
    reaction_probability: float = 0.3
    min_response_delay: int = 5  # seconds
    max_response_delay: int = 60

    # Active hours
    active_hours_start: int = 9
    active_hours_end: int = 22

    def is_active_time(self, hour: int) -> bool:
        """Check if given hour is within active hours."""
        if self.active_hours_start <= self.active_hours_end:
            return self.active_hours_start <= hour < self.active_hours_end
        # Handle overnight (e.g., 22-06)
        return hour >= self.active_hours_start or hour < self.active_hours_end

    def get_response_delay(self) -> float:
        """Get randomized response delay."""
        import random
        return random.uniform(self.min_response_delay, self.max_response_delay)


@dataclass
class InterestCategory(Entity):
    """Category of interests for warmup channels."""

    name: str = ""
    description: Optional[str] = None
    keywords: list[str] = field(default_factory=list)


@dataclass
class WarmupChannel(Entity):
    """Channel for warmup activities."""

    username: str = ""
    title: Optional[str] = None
    category_id: Optional[UUID] = None
    language: str = "en"

    subscriber_count: Optional[int] = None
    last_post_at: Optional[datetime] = None

    is_active: bool = True


@dataclass
class WarmupGroup(Entity):
    """Telegram group for warmup activities."""

    username: str = ""
    title: Optional[str] = None
    category_id: Optional[UUID] = None
    language: str = "en"

    can_write: bool = False
    member_count: Optional[int] = None

    is_active: bool = True


@dataclass
class AccountGroup(AggregateRoot):
    """Group of accounts for batch operations."""

    name: str = ""
    description: Optional[str] = None
    account_ids: list[UUID] = field(default_factory=list)

    default_warmup_profile_id: Optional[UUID] = None
    default_proxy_group_id: Optional[UUID] = None

    def add_account(self, account_id: UUID) -> None:
        """Add account to group."""
        if account_id not in self.account_ids:
            self.account_ids.append(account_id)
            self.increment_version()

    def remove_account(self, account_id: UUID) -> None:
        """Remove account from group."""
        if account_id in self.account_ids:
            self.account_ids.remove(account_id)
            self.increment_version()

    @property
    def account_count(self) -> int:
        """Number of accounts in group."""
        return len(self.account_ids)


@dataclass
class ProxyGroup(Entity):
    """Group of proxies by country/region."""

    name: str = ""
    description: Optional[str] = None
    country_code: Optional[str] = None  # "DE", "US", "RU"


@dataclass
class WarmupActivityLog:
    """Single warmup activity log entry."""

    id: UUID = field(default_factory=lambda: UUID(int=0))
    account_id: UUID = field(default_factory=lambda: UUID(int=0))

    activity_type: str = ""  # "channel_join", "reaction", "message", etc.
    target: Optional[str] = None
    details: Optional[dict] = None

    success: bool = True
    error: Optional[str] = None

    created_at: datetime = field(default_factory=datetime.utcnow)
