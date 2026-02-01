"""Channel entity for comment bot."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4


class ChannelStatus(str, Enum):
    """Channel status."""

    PENDING = "pending"          # Not yet processed
    ACTIVE = "active"            # Working fine
    NO_ACCESS = "no_access"      # Can't access (private/banned)
    NO_COMMENTS = "no_comments"  # Comments disabled
    ERROR = "error"              # Other error


@dataclass
class Channel:
    """
    Channel to post comments in.

    Attributes:
        id: Unique identifier
        campaign_id: Parent campaign
        link: Channel link (t.me/... or @username)
        username: Parsed username
        telegram_id: Resolved Telegram ID
        title: Channel title
        status: Current status
        error_message: Last error if any
        last_post_id: Last processed post ID
        comments_posted: Total comments posted
        created_at: When added
        last_checked_at: Last status check
        owner_id: Telegram user ID
    """

    id: UUID = field(default_factory=uuid4)
    campaign_id: UUID = field(default_factory=uuid4)
    link: str = ""
    username: Optional[str] = None
    telegram_id: Optional[int] = None
    title: Optional[str] = None
    status: ChannelStatus = ChannelStatus.PENDING
    error_message: Optional[str] = None
    last_post_id: Optional[int] = None
    comments_posted: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_checked_at: Optional[datetime] = None
    owner_id: int = 0

    def is_available(self) -> bool:
        """Check if channel is available for commenting."""
        return self.status == ChannelStatus.ACTIVE

    def mark_active(self, telegram_id: int, title: str) -> None:
        """Mark channel as active after successful check."""
        self.telegram_id = telegram_id
        self.title = title
        self.status = ChannelStatus.ACTIVE
        self.error_message = None
        self.last_checked_at = datetime.utcnow()

    def mark_no_access(self, error: str = "No access") -> None:
        """Mark channel as inaccessible."""
        self.status = ChannelStatus.NO_ACCESS
        self.error_message = error
        self.last_checked_at = datetime.utcnow()

    def mark_no_comments(self) -> None:
        """Mark channel as having comments disabled."""
        self.status = ChannelStatus.NO_COMMENTS
        self.error_message = "Comments disabled"
        self.last_checked_at = datetime.utcnow()

    def mark_error(self, error: str) -> None:
        """Mark channel with error."""
        self.status = ChannelStatus.ERROR
        self.error_message = error
        self.last_checked_at = datetime.utcnow()

    def increment_comments(self) -> None:
        """Increment comment counter."""
        self.comments_posted += 1

    def update_last_post(self, post_id: int) -> None:
        """Update last processed post ID."""
        self.last_post_id = post_id

    @staticmethod
    def parse_link(link: str) -> Optional[str]:
        """Parse channel link to username."""
        link = link.strip()

        # @username
        if link.startswith("@"):
            return link[1:]

        # t.me/username or https://t.me/username
        if "t.me/" in link:
            link = link.replace("https://", "").replace("http://", "")
            parts = link.split("t.me/")
            if len(parts) > 1:
                username = parts[1].split("/")[0].split("?")[0]
                if not username.startswith("+"):  # Not private link
                    return username

        # Plain username
        if link and "/" not in link and not link.startswith("+"):
            return link

        return None
