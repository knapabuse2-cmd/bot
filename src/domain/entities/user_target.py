"""
UserTarget entity representing a target user for outreach.

A UserTarget is a Telegram user who should be contacted
as part of a campaign.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from .base import AggregateRoot


class TargetStatus(str, Enum):
    """Possible states of a target user."""
    
    PENDING = "pending"           # Waiting in queue
    ASSIGNED = "assigned"         # Assigned to an account
    CONTACTED = "contacted"       # First message sent
    IN_PROGRESS = "in_progress"   # Active conversation
    CONVERTED = "converted"       # Goal achieved
    COMPLETED = "completed"       # Dialogue finished
    FAILED = "failed"             # Contact failed
    SKIPPED = "skipped"           # Skipped (e.g., already known)
    BLOCKED = "blocked"           # User blocked us


@dataclass
class UserTarget(AggregateRoot):
    """
    Target user entity for outreach.
    
    Represents a single user to be contacted in a campaign.
    
    Attributes:
        campaign_id: Campaign this target belongs to
        telegram_id: Telegram user ID (if known)
        username: Telegram username (without @)
        phone: Phone number (if known)
        first_name: User's first name (if known)
        last_name: User's last name (if known)
        status: Current target status
        assigned_account_id: Account handling this target
        dialogue_id: Reference to dialogue (if started)
        priority: Queue priority (higher = sooner)
        source: Where this target came from
        tags: Custom tags for filtering
        notes: Admin notes
        contact_attempts: Number of contact attempts
        last_contact_attempt: Last attempt timestamp
        scheduled_contact_at: When to contact this user
    """
    
    campaign_id: UUID = field(default_factory=lambda: UUID(int=0))
    
    # Identification (at least one required)
    telegram_id: Optional[int] = None
    username: Optional[str] = None

    # Backward compatible alias (used by API/UI)
    @property
    def telegram_username(self) -> Optional[str]:
        return self.username

    @telegram_username.setter
    def telegram_username(self, value: Optional[str]) -> None:
        self.username = value
    phone: Optional[str] = None
    
    # Profile info
    first_name: str = ""
    last_name: str = ""
    
    # Status tracking
    status: TargetStatus = TargetStatus.PENDING
    assigned_account_id: Optional[UUID] = None
    dialogue_id: Optional[UUID] = None
    
    # Queue management
    priority: int = 0
    source: str = ""
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    
    # Contact tracking
    contact_attempts: int = 0
    last_contact_attempt: Optional[datetime] = None
    scheduled_contact_at: Optional[datetime] = None

    # Failure tracking (explicit field for analytics and tests)
    fail_reason: Optional[str] = None
    
    def __post_init__(self) -> None:
        """Validate that at least one identifier is provided."""
        if not any([self.telegram_id, self.username, self.phone]):
            raise ValueError("UserTarget requires at least one identifier: telegram_id, username, or phone")
    
    @property
    def display_name(self) -> str:
        """Get displayable name for the target."""
        if self.first_name or self.last_name:
            return f"{self.first_name} {self.last_name}".strip()
        if self.username:
            return f"@{self.username}"
        if self.telegram_id:
            return f"ID:{self.telegram_id}"
        return f"Phone:{self.phone}"
    
    @property
    def identifier(self) -> str:
        """Get primary identifier for Telegram lookup."""
        if self.username:
            return self.username
        if self.telegram_id:
            return str(self.telegram_id)
        if self.phone:
            return self.phone
        raise ValueError("No valid identifier")
    
    def assign_to_account(self, account_id: UUID) -> None:
        """Assign this target to an account."""
        self.assigned_account_id = account_id
        self.status = TargetStatus.ASSIGNED
        self.touch()
    
    def mark_contacted(self, dialogue_id: Optional[UUID] = None) -> None:
        """Mark target as contacted.

        Args:
            dialogue_id: Optional dialogue identifier if a dialogue entity
                has already been created.
        """
        if dialogue_id is not None:
            self.dialogue_id = dialogue_id
        self.status = TargetStatus.CONTACTED
        self.contact_attempts += 1
        self.last_contact_attempt = datetime.utcnow()
        self.touch()
    
    def mark_in_progress(self) -> None:
        """Mark target as having active conversation."""
        self.status = TargetStatus.IN_PROGRESS
        self.touch()
    
    def mark_converted(self) -> None:
        """Mark target as converted (goal achieved)."""
        self.status = TargetStatus.CONVERTED
        self.touch()
    
    def mark_completed(self) -> None:
        """Mark target as completed."""
        self.status = TargetStatus.COMPLETED
        self.touch()
    
    def mark_failed(self, reason: str = "") -> None:
        """Mark target as failed."""
        self.status = TargetStatus.FAILED
        self.fail_reason = reason or None
        if reason:
            self.notes = f"{self.notes}\nFailed: {reason}".strip()
        self.touch()
    
    def mark_blocked(self) -> None:
        """Mark that user blocked us."""
        self.status = TargetStatus.BLOCKED
        self.touch()
    
    def mark_skipped(self, reason: str = "") -> None:
        """Skip this target."""
        self.status = TargetStatus.SKIPPED
        if reason:
            self.notes = f"{self.notes}\nSkipped: {reason}".strip()
        self.touch()
    
    def can_contact(self) -> bool:
        """Check if target can be contacted."""
        return self.status in (TargetStatus.PENDING, TargetStatus.ASSIGNED)
    
    def record_contact_attempt(self) -> None:
        """Record a contact attempt."""
        self.contact_attempts += 1
        self.last_contact_attempt = datetime.utcnow()
        self.touch()
