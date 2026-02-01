"""
Account entity representing a Telegram worker account.

An Account is the core unit of the system - each account can
autonomously interact with target users through Telegram.
"""

from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
from typing import Optional
from uuid import UUID

from .base import AggregateRoot


class AccountStatus(str, Enum):
    """Possible states of an account."""

    INACTIVE = "inactive"       # Not yet configured
    READY = "ready"             # Configured, waiting to start
    ACTIVE = "active"           # Currently running
    PAUSED = "paused"           # Temporarily stopped
    BANNED = "banned"           # Telegram ban detected
    ERROR = "error"             # Error state, needs attention
    COOLDOWN = "cooldown"       # Rate limited, waiting


class AccountSource(str, Enum):
    """How the account was added to the system."""

    PHONE = "phone"             # Authorized via phone number (native session)
    JSON_SESSION = "json_session"  # Imported from JSON + session file
    TDATA = "tdata"             # Imported from Telegram Desktop tdata


@dataclass
class AccountSchedule:
    """
    Defines when an account is allowed to be active.

    Anti-detection: Each account has randomized sleep schedule
    to avoid synchronized activity patterns.

    Attributes:
        start_time: Daily start time (UTC)
        end_time: Daily end time (UTC)
        active_days: Days of week (0=Monday, 6=Sunday)
        timezone: Timezone for schedule interpretation
        sleep_enabled: Whether to enable randomized sleep periods
        sleep_hours: Hours of sleep per day (randomized ±1 hour)
        sleep_start_hour: Base hour when sleep starts (randomized ±2 hours)
    """

    start_time: time = field(default_factory=lambda: time(9, 0))
    end_time: time = field(default_factory=lambda: time(21, 0))
    active_days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])
    timezone: str = "UTC"

    # Sleep schedule for anti-detection
    sleep_enabled: bool = True  # Enable randomized sleep
    sleep_hours: int = 7  # Base sleep duration (will be randomized ±1h)
    sleep_start_hour: int = 23  # Base hour for sleep start (will be randomized ±2h)

    # Per-account randomized offset (set once per account)
    _sleep_offset_hours: float = field(default=0.0, repr=False)
    _initialized: bool = field(default=False, repr=False)

    def _initialize_random_offset(self, account_id: Optional[str] = None) -> None:
        """Initialize random sleep offset based on account_id for consistency."""
        if self._initialized:
            return

        import hashlib
        import random

        if account_id:
            # Deterministic random based on account_id (consistent across restarts)
            seed = int(hashlib.md5(account_id.encode()).hexdigest()[:8], 16)
            rng = random.Random(seed)
        else:
            rng = random.Random()

        # Random offset: -2 to +2 hours for sleep start
        self._sleep_offset_hours = rng.uniform(-2.0, 2.0)
        self._initialized = True

    def get_sleep_window(self, account_id: Optional[str] = None) -> tuple[int, int]:
        """
        Get randomized sleep window for this account.

        Returns:
            Tuple of (sleep_start_hour, sleep_end_hour) in 24h format
        """
        self._initialize_random_offset(account_id)

        import random

        # Add daily variation (±30 minutes)
        daily_variation = random.uniform(-0.5, 0.5)

        # Calculate actual sleep start with offset and variation
        actual_start = self.sleep_start_hour + self._sleep_offset_hours + daily_variation
        actual_start = int(actual_start) % 24

        # Sleep duration with ±1 hour variation
        duration = self.sleep_hours + random.uniform(-1.0, 1.0)
        duration = max(5, min(10, duration))  # Clamp between 5-10 hours

        actual_end = int(actual_start + duration) % 24

        return actual_start, actual_end

    def is_sleeping(self, current_time: datetime, account_id: Optional[str] = None) -> bool:
        """
        Check if account should be sleeping now.

        Args:
            current_time: Current datetime
            account_id: Account ID for consistent randomization

        Returns:
            True if account is in sleep period
        """
        if not self.sleep_enabled:
            return False

        sleep_start, sleep_end = self.get_sleep_window(account_id)
        current_hour = current_time.hour

        # Handle overnight sleep (e.g., 23:00 - 06:00)
        if sleep_start > sleep_end:
            return current_hour >= sleep_start or current_hour < sleep_end
        else:
            return sleep_start <= current_hour < sleep_end

    def is_active_now(self, current_time: datetime, account_id: Optional[str] = None) -> bool:
        """Check if current time falls within active schedule."""
        if current_time.weekday() not in self.active_days:
            return False

        # Check sleep schedule first
        if self.is_sleeping(current_time, account_id):
            return False

        current = current_time.time()
        if self.start_time <= self.end_time:
            return self.start_time <= current <= self.end_time
        # Handle overnight schedules (e.g., 22:00 - 06:00)
        return current >= self.start_time or current <= self.end_time


@dataclass
class AccountLimits:
    """
    Rate limiting configuration for an account.

    Attributes:
        max_new_conversations_per_day: Max new users to contact daily (cold outreach)
        max_messages_per_hour: Max outgoing messages per hour (cold outreach only)
        max_responses_per_hour: Max responses to incoming messages per hour
        min_delay_between_messages: Minimum seconds between messages
        max_delay_between_messages: Maximum seconds between messages
        max_active_dialogues: Max concurrent active dialogues
    """

    max_new_conversations_per_day: int = 20
    max_messages_per_hour: int = 30  # For cold outreach
    max_responses_per_hour: int = 300  # For responding to incoming messages
    min_delay_between_messages: int = 30
    max_delay_between_messages: int = 120
    max_active_dialogues: int = 50
    
    def get_random_delay(self) -> float:
        """Get randomized delay between messages."""
        import random
        return random.uniform(
            self.min_delay_between_messages,
            self.max_delay_between_messages
        )


@dataclass
class Account(AggregateRoot):
    """
    Telegram worker account entity.
    
    Represents a single Telegram account used for outreach.
    Each account has its own session, proxy, and configuration.
    
    Attributes:
        phone: Phone number associated with the account
        session_data: Encrypted Telethon session data
        proxy_id: Reference to assigned proxy
        status: Current account status
        schedule: Activity schedule
        limits: Rate limiting configuration
        campaign_id: Currently assigned campaign (if any)
        telegram_id: Telegram user ID (populated after auth)
        username: Telegram username (if set)
        first_name: Account first name
        last_name: Account last name
        bio: Account bio text
        daily_conversations_count: Counter for daily limit tracking
        hourly_messages_count: Counter for hourly limit tracking
        last_activity: Timestamp of last activity
        error_message: Last error message (if status is ERROR)
    """
    
    phone: str = ""
    session_data: Optional[bytes] = None
    proxy_id: Optional[UUID] = None
    telegram_app_id: Optional[UUID] = None  # Reference to TelegramApp for API credentials

    source: AccountSource = AccountSource.PHONE  # How account was added
    status: AccountStatus = AccountStatus.INACTIVE
    schedule: AccountSchedule = field(default_factory=AccountSchedule)
    limits: AccountLimits = field(default_factory=AccountLimits)
    
    campaign_id: Optional[UUID] = None
    group_id: Optional[UUID] = None  # Account group for batch operations

    # Telegram profile info
    telegram_id: Optional[int] = None
    username: Optional[str] = None
    first_name: str = ""
    last_name: str = ""
    bio: str = ""
    is_premium: bool = False
    
    # Counters (reset daily/hourly)
    daily_conversations_count: int = 0
    hourly_messages_count: int = 0  # Cold outreach messages
    hourly_responses_count: int = 0  # Responses to incoming messages

    # Lifetime totals (never reset)
    total_messages_sent: int = 0
    total_conversations_started: int = 0
    last_daily_reset: datetime = field(default_factory=datetime.utcnow)
    last_hourly_reset: datetime = field(default_factory=datetime.utcnow)
    
    last_activity: Optional[datetime] = None
    error_message: Optional[str] = None
    
    def activate(self) -> None:
        """Set account to active state."""
        if self.status == AccountStatus.BANNED:
            raise ValueError("Cannot activate banned account")
        self.status = AccountStatus.ACTIVE
        self.error_message = None
        self.increment_version()
    
    def pause(self) -> None:
        """Pause the account."""
        self.status = AccountStatus.PAUSED
        self.increment_version()
    
    def set_error(self, message: str) -> None:
        """Set account to error state with message."""
        self.status = AccountStatus.ERROR
        self.error_message = message
        self.increment_version()
    
    def set_banned(self) -> None:
        """Mark account as banned by Telegram."""
        self.status = AccountStatus.BANNED
        self.increment_version()
    
    def can_send_message(self) -> bool:
        """Check if account can send a cold outreach message now."""
        if self.status != AccountStatus.ACTIVE:
            return False
        if self.hourly_messages_count >= self.limits.max_messages_per_hour:
            return False
        return True

    def can_respond_to_message(self) -> bool:
        """Check if account can respond to an incoming message."""
        if self.status != AccountStatus.ACTIVE:
            return False
        if self.hourly_responses_count >= self.limits.max_responses_per_hour:
            return False
        return True

    def can_start_new_conversation(self) -> bool:
        """Check if account can start a new conversation."""
        if not self.can_send_message():
            return False
        if self.daily_conversations_count >= self.limits.max_new_conversations_per_day:
            return False
        return True

    def record_message_sent(self) -> None:
        """Record that a cold outreach message was sent."""
        self.hourly_messages_count += 1
        self.total_messages_sent += 1
        self.last_activity = datetime.utcnow()
        self.touch()

    def record_response_sent(self) -> None:
        """Record that a response to incoming message was sent."""
        self.hourly_responses_count += 1
        self.total_messages_sent += 1
        self.last_activity = datetime.utcnow()
        self.touch()

    def record_new_conversation(self) -> None:
        """Record that a new conversation was started."""
        self.daily_conversations_count += 1
        self.total_conversations_started += 1
        self.record_message_sent()

    def reset_hourly_counter(self) -> None:
        """Reset hourly message counters."""
        self.hourly_messages_count = 0
        self.hourly_responses_count = 0
        self.last_hourly_reset = datetime.utcnow()

    def reset_daily_counter(self) -> None:
        """Reset daily conversation counter."""
        self.daily_conversations_count = 0
        self.last_daily_reset = datetime.utcnow()
    
    def is_configured(self) -> bool:
        """Check if account is fully configured."""
        return bool(self.session_data and self.proxy_id)
