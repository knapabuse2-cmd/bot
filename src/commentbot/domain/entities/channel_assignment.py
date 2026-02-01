"""Channel assignment entity - maps accounts to channels."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4


class AssignmentStatus(str, Enum):
    """Assignment status."""

    ACTIVE = "active"            # Working
    BLOCKED = "blocked"          # Account blocked in this channel
    SWAPPED = "swapped"          # Swapped to another account
    FAILED = "failed"            # Failed multiple times


@dataclass
class ChannelAssignment:
    """
    Assignment of channel to account.

    Tracks which account works with which channel,
    and handles swapping when needed.

    Attributes:
        id: Unique identifier
        channel_id: Assigned channel
        account_id: Assigned account
        campaign_id: Parent campaign
        status: Current status
        assigned_at: When assigned
        last_activity_at: Last successful activity
        fail_count: Consecutive failures
        swap_count: How many times was swapped
        previous_account_id: Previous account before swap
    """

    id: UUID = field(default_factory=uuid4)
    channel_id: UUID = field(default_factory=uuid4)
    account_id: UUID = field(default_factory=uuid4)
    campaign_id: UUID = field(default_factory=uuid4)
    status: AssignmentStatus = AssignmentStatus.ACTIVE
    assigned_at: datetime = field(default_factory=datetime.utcnow)
    last_activity_at: Optional[datetime] = None
    fail_count: int = 0
    swap_count: int = 0
    previous_account_id: Optional[UUID] = None
    owner_id: int = 0

    # Thresholds
    MAX_FAILS_BEFORE_SWAP = 3

    def is_active(self) -> bool:
        """Check if assignment is active."""
        return self.status == AssignmentStatus.ACTIVE

    def record_success(self) -> None:
        """Record successful activity."""
        self.fail_count = 0
        self.last_activity_at = datetime.utcnow()

    def record_failure(self) -> bool:
        """
        Record failure.

        Returns:
            True if should swap account (too many failures)
        """
        self.fail_count += 1
        return self.fail_count >= self.MAX_FAILS_BEFORE_SWAP

    def needs_swap(self) -> bool:
        """Check if assignment needs account swap."""
        return self.fail_count >= self.MAX_FAILS_BEFORE_SWAP

    def swap_account(self, new_account_id: UUID) -> None:
        """
        Swap to new account.

        Args:
            new_account_id: New account to assign
        """
        self.previous_account_id = self.account_id
        self.account_id = new_account_id
        self.status = AssignmentStatus.ACTIVE
        self.fail_count = 0
        self.swap_count += 1
        self.assigned_at = datetime.utcnow()

    def mark_blocked(self) -> None:
        """Mark assignment as blocked."""
        self.status = AssignmentStatus.BLOCKED

    def mark_failed(self) -> None:
        """Mark assignment as permanently failed."""
        self.status = AssignmentStatus.FAILED
