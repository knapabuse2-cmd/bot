"""
ScrapeTask entity for target collection from channels/chats.

Represents a scraping task that collects usernames from
Telegram channels, groups, and their comments.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from .base import AggregateRoot


class ScrapeTaskStatus(str, Enum):
    """Status of a scrape task."""

    PENDING = "pending"         # Waiting to start
    RUNNING = "running"         # Currently scraping
    COMPLETED = "completed"     # Successfully finished
    FAILED = "failed"           # Failed with error
    CANCELLED = "cancelled"     # Cancelled by user


@dataclass
class ScrapeTask(AggregateRoot):
    """
    Scraping task entity.

    Represents a task to collect usernames from Telegram sources.

    Attributes:
        campaign_id: Campaign to add targets to (optional)
        account_id: Account used for scraping
        sources: List of channel/chat links to scrape
        status: Current task status
        total_sources: Number of sources to process
        processed_sources: Number of sources processed
        total_users_found: Total unique users found
        users_added: Users added as targets
        users_skipped: Users skipped (duplicates, bots, etc.)
        error_message: Error message if failed
        started_at: When scraping started
        completed_at: When scraping finished
    """

    # References
    campaign_id: Optional[UUID] = None  # If set, add targets to this campaign
    account_id: UUID = field(default_factory=lambda: UUID(int=0))

    # Task configuration
    sources: list[str] = field(default_factory=list)  # Channel/chat links
    scrape_comments: bool = True  # Scrape comment authors
    scrape_chat: bool = True      # Scrape chat participants
    max_users_per_source: int = 1000  # Limit per source
    skip_bots: bool = True
    skip_no_username: bool = True  # Skip users without username

    # Status tracking
    status: ScrapeTaskStatus = ScrapeTaskStatus.PENDING
    total_sources: int = 0
    processed_sources: int = 0
    current_source: str = ""

    # Results
    total_users_found: int = 0
    users_added: int = 0
    users_skipped: int = 0
    collected_usernames: list[str] = field(default_factory=list)

    # Error tracking
    error_message: str = ""
    failed_sources: list[str] = field(default_factory=list)

    # Timestamps
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        """Initialize totals."""
        if self.sources and self.total_sources == 0:
            self.total_sources = len(self.sources)

    def start(self) -> None:
        """Mark task as started."""
        self.status = ScrapeTaskStatus.RUNNING
        self.started_at = datetime.utcnow()
        self.touch()

    def mark_source_processed(self, source: str, users_found: int) -> None:
        """Mark a source as processed."""
        self.processed_sources += 1
        self.total_users_found += users_found
        self.current_source = ""
        self.touch()

    def mark_source_failed(self, source: str, error: str) -> None:
        """Mark a source as failed."""
        self.failed_sources.append(f"{source}: {error}")
        self.processed_sources += 1
        self.current_source = ""
        self.touch()

    def set_current_source(self, source: str) -> None:
        """Set currently processing source."""
        self.current_source = source
        self.touch()

    def add_usernames(self, usernames: list[str]) -> int:
        """
        Add collected usernames.

        Returns number of new usernames added (deduped).
        """
        existing = set(self.collected_usernames)
        new_usernames = [u for u in usernames if u not in existing]
        self.collected_usernames.extend(new_usernames)
        return len(new_usernames)

    def complete(self, users_added: int, users_skipped: int) -> None:
        """Mark task as completed."""
        self.status = ScrapeTaskStatus.COMPLETED
        self.users_added = users_added
        self.users_skipped = users_skipped
        self.completed_at = datetime.utcnow()
        self.touch()

    def fail(self, error: str) -> None:
        """Mark task as failed."""
        self.status = ScrapeTaskStatus.FAILED
        self.error_message = error
        self.completed_at = datetime.utcnow()
        self.touch()

    def cancel(self) -> None:
        """Cancel the task."""
        self.status = ScrapeTaskStatus.CANCELLED
        self.completed_at = datetime.utcnow()
        self.touch()

    @property
    def progress_percent(self) -> float:
        """Get progress percentage."""
        if self.total_sources == 0:
            return 0.0
        return (self.processed_sources / self.total_sources) * 100

    @property
    def is_running(self) -> bool:
        """Check if task is running."""
        return self.status == ScrapeTaskStatus.RUNNING

    @property
    def is_finished(self) -> bool:
        """Check if task is finished (completed, failed, or cancelled)."""
        return self.status in (
            ScrapeTaskStatus.COMPLETED,
            ScrapeTaskStatus.FAILED,
            ScrapeTaskStatus.CANCELLED,
        )
