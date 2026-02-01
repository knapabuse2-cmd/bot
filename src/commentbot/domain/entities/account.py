"""Account entity for comment bot."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4


class AccountStatus(str, Enum):
    """Account status."""

    PENDING = "pending"          # Waiting for auth code
    AUTH_CODE = "auth_code"      # Code sent, waiting for input
    AUTH_2FA = "auth_2fa"        # Waiting for 2FA password
    ACTIVE = "active"            # Ready to work
    PAUSED = "paused"            # Manually paused
    BANNED = "banned"            # Account banned
    ERROR = "error"              # Auth or other error


@dataclass
class Account:
    """
    Telegram account for posting comments.

    Attributes:
        id: Unique identifier
        phone: Phone number (for phone auth)
        session_data: Encrypted session string/data
        tdata_path: Path to tdata folder (for tdata auth)
        status: Current account status
        error_message: Last error message if any
        created_at: When account was added
        last_used_at: Last activity time
        comments_today: Comments posted today
        daily_limit: Max comments per day
        owner_id: Telegram user ID who added this account
    """

    id: UUID = field(default_factory=uuid4)
    phone: Optional[str] = None
    session_data: Optional[bytes] = None
    tdata_path: Optional[str] = None
    status: AccountStatus = AccountStatus.PENDING
    error_message: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_used_at: Optional[datetime] = None
    comments_today: int = 0
    daily_limit: int = 50
    owner_id: int = 0

    # Auth flow temp data
    phone_code_hash: Optional[str] = None

    def is_active(self) -> bool:
        """Check if account is ready to work."""
        return self.status == AccountStatus.ACTIVE

    def can_comment(self) -> bool:
        """Check if account can post more comments today."""
        return self.is_active() and self.comments_today < self.daily_limit

    def increment_comments(self) -> None:
        """Increment daily comment counter."""
        self.comments_today += 1
        self.last_used_at = datetime.utcnow()

    def reset_daily_counter(self) -> None:
        """Reset daily comment counter (call at midnight)."""
        self.comments_today = 0

    def mark_active(self, session_data: bytes) -> None:
        """Mark account as active after successful auth."""
        self.session_data = session_data
        self.status = AccountStatus.ACTIVE
        self.error_message = None
        self.phone_code_hash = None

    def mark_error(self, message: str) -> None:
        """Mark account with error."""
        self.status = AccountStatus.ERROR
        self.error_message = message

    def mark_banned(self) -> None:
        """Mark account as banned."""
        self.status = AccountStatus.BANNED
        self.error_message = "Account banned by Telegram"

    def pause(self) -> None:
        """Pause account."""
        self.status = AccountStatus.PAUSED

    def resume(self) -> None:
        """Resume paused account."""
        if self.status == AccountStatus.PAUSED:
            self.status = AccountStatus.ACTIVE
