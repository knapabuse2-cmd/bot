"""Comment task entity."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4


class TaskStatus(str, Enum):
    """Task status."""

    PENDING = "pending"          # Waiting to be executed
    IN_PROGRESS = "in_progress"  # Currently being executed
    COMPLETED = "completed"      # Successfully completed
    FAILED = "failed"            # Failed to complete


@dataclass
class CommentTask:
    """
    Task to post a comment.

    Attributes:
        id: Unique identifier
        account_id: Account to use for posting
        channel_link: Channel/chat link to comment in
        post_link: Specific post link (optional)
        comment_text: Text to post
        status: Current task status
        error_message: Error if failed
        created_at: When task was created
        executed_at: When task was executed
        owner_id: Telegram user ID who created this task
    """

    id: UUID = field(default_factory=uuid4)
    account_id: Optional[UUID] = None
    channel_link: str = ""
    post_link: Optional[str] = None
    comment_text: str = ""
    status: TaskStatus = TaskStatus.PENDING
    error_message: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    executed_at: Optional[datetime] = None
    owner_id: int = 0

    def mark_in_progress(self) -> None:
        """Mark task as in progress."""
        self.status = TaskStatus.IN_PROGRESS

    def mark_completed(self) -> None:
        """Mark task as completed."""
        self.status = TaskStatus.COMPLETED
        self.executed_at = datetime.utcnow()

    def mark_failed(self, error: str) -> None:
        """Mark task as failed."""
        self.status = TaskStatus.FAILED
        self.error_message = error
        self.executed_at = datetime.utcnow()
