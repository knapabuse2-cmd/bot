"""Campaign entity for comment bot."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4


class CampaignStatus(str, Enum):
    """Campaign status."""

    DRAFT = "draft"              # Being configured
    ACTIVE = "active"            # Running
    PAUSED = "paused"            # Manually paused
    COMPLETED = "completed"      # Finished


@dataclass
class Campaign:
    """
    Comment campaign.

    Contains channels to comment on and settings.

    Attributes:
        id: Unique identifier
        name: Campaign name
        status: Current status
        comment_templates: List of comment templates (randomly picked)
        min_delay: Min delay between comments (seconds)
        max_delay: Max delay between comments (seconds)
        comments_per_post: How many comments per post
        created_at: When campaign was created
        owner_id: Telegram user ID who created this
    """

    id: UUID = field(default_factory=uuid4)
    name: str = ""
    status: CampaignStatus = CampaignStatus.DRAFT
    comment_templates: list[str] = field(default_factory=list)
    initial_message: Optional[str] = None  # Message sent after profile copy
    min_delay: int = 30          # seconds
    max_delay: int = 120         # seconds
    comments_per_post: int = 1
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    owner_id: int = 0

    # Stats
    total_comments: int = 0
    successful_comments: int = 0
    failed_comments: int = 0

    def is_active(self) -> bool:
        """Check if campaign is running."""
        return self.status == CampaignStatus.ACTIVE

    def activate(self) -> None:
        """Start campaign."""
        self.status = CampaignStatus.ACTIVE
        self.updated_at = datetime.utcnow()

    def pause(self) -> None:
        """Pause campaign."""
        self.status = CampaignStatus.PAUSED
        self.updated_at = datetime.utcnow()

    def complete(self) -> None:
        """Mark campaign as completed."""
        self.status = CampaignStatus.COMPLETED
        self.updated_at = datetime.utcnow()

    def add_template(self, template: str) -> None:
        """Add comment template."""
        if template and template not in self.comment_templates:
            self.comment_templates.append(template)

    def get_random_template(self) -> Optional[str]:
        """Get random comment template."""
        import random
        if not self.comment_templates:
            return None
        return random.choice(self.comment_templates)

    def increment_stats(self, success: bool) -> None:
        """Update stats after comment attempt."""
        self.total_comments += 1
        if success:
            self.successful_comments += 1
        else:
            self.failed_comments += 1
