"""
Campaign entity representing an outreach campaign.

A Campaign defines the goal, messaging strategy, and configuration
for a set of outreach activities across multiple accounts.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from .base import AggregateRoot


class CampaignStatus(str, Enum):
    """Possible states of a campaign."""
    
    DRAFT = "draft"             # Being configured
    READY = "ready"             # Ready to start
    ACTIVE = "active"           # Currently running
    PAUSED = "paused"           # Temporarily stopped
    COMPLETED = "completed"     # Finished successfully
    CANCELLED = "cancelled"     # Manually cancelled


@dataclass
class CampaignGoal:
    """
    Defines the target outcome of a campaign.
    
    Attributes:
        target_message: The message/content to eventually deliver
        target_action: Action we want user to take (e.g., "join_channel")
        target_url: URL to promote (if applicable)
        min_messages_before_goal: Minimum conversation turns before goal
        max_messages_before_goal: Maximum turns before pushing goal
    """
    
    # NOTE:
    # These fields are intentionally Optional to reflect that a campaign
    # may be created/configured progressively.
    target_message: Optional[str] = None
    target_action: Optional[str] = None
    target_url: Optional[str] = None
    min_messages_before_goal: int = 3
    max_messages_before_goal: int = 10

    def is_configured(self) -> bool:
        """Return True when goal configuration is present.

        A campaign goal is considered configured when at least one of the
        goal-driving fields is set (most commonly `target_message`).
        """
        return bool((self.target_message or "").strip())


@dataclass
class CampaignPrompt:
    """
    LLM prompt configuration for the campaign.
    
    Attributes:
        system_prompt: Main system prompt defining AI persona
        first_message_template: Template for initial contact
        goal_transition_hints: Hints for steering toward goal
        forbidden_topics: Topics the AI should avoid
        language: Primary language for responses
        tone: Desired conversation tone
    """
    
    system_prompt: str = ""
    first_message_template: str = ""
    goal_transition_hints: list[str] = field(default_factory=list)
    forbidden_topics: list[str] = field(default_factory=list)
    language: str = "ru"
    tone: str = "friendly"
    
    def build_system_prompt(self, goal: CampaignGoal) -> str:
        """
        Build complete system prompt with goal context.
        
        Args:
            goal: Campaign goal information
            
        Returns:
            Complete system prompt for LLM
        """
        prompt_parts = [self.system_prompt]
        
        if goal.target_message:
            prompt_parts.append(
                f"\n\nЦель разговора: постепенно подвести собеседника к следующей информации: "
                f"{goal.target_message}"
            )
        
        if goal.target_url:
            prompt_parts.append(f"\nЦелевая ссылка для продвижения: {goal.target_url}")
        
        if self.goal_transition_hints:
            hints = "\n".join(f"- {h}" for h in self.goal_transition_hints)
            prompt_parts.append(f"\n\nПодсказки для перехода к цели:\n{hints}")
        
        if self.forbidden_topics:
            forbidden = ", ".join(self.forbidden_topics)
            prompt_parts.append(f"\n\nИзбегай следующих тем: {forbidden}")
        
        prompt_parts.append(f"\n\nТон общения: {self.tone}")
        prompt_parts.append(f"Язык: {self.language}")
        
        return "\n".join(prompt_parts)


@dataclass
class CampaignSendingSettings:
    """
    Settings for first message sending (batch sending).

    Attributes:
        send_interval_hours: Interval between sending batches (in hours)
        messages_per_batch: How many first messages to send per batch
        message_delay_min: Minimum delay between messages in batch (seconds)
        message_delay_max: Maximum delay between messages in batch (seconds)
        last_batch_at: Timestamp of last batch sending
        targets_file_path: Path to original targets file (for cleanup)
        follow_up_enabled: Whether to send follow-up messages (separate from campaign status)
    """

    send_interval_hours: float = 13.0  # Send batch every 13 hours by default
    messages_per_batch: int = 10       # Send 10 first messages per batch
    message_delay_min: int = 17        # Min delay between messages (seconds)
    message_delay_max: int = 23        # Max delay between messages (seconds)
    last_batch_at: Optional[datetime] = None
    targets_file_path: Optional[str] = None  # Path to original targets file
    follow_up_enabled: bool = True  # Whether follow-up messages are enabled

    def can_send_batch(self, current_time: Optional[datetime] = None) -> bool:
        """Check if it's time to send next batch."""
        from datetime import timedelta, timezone

        if current_time is None:
            current_time = datetime.now(timezone.utc)

        if self.last_batch_at is None:
            return True

        # Make sure both datetimes are timezone-aware
        last_batch = self.last_batch_at
        if last_batch.tzinfo is None:
            last_batch = last_batch.replace(tzinfo=timezone.utc)

        next_batch_time = last_batch + timedelta(hours=self.send_interval_hours)
        return current_time >= next_batch_time

    def record_batch_sent(self) -> None:
        """Record that a batch was sent."""
        from datetime import timezone
        self.last_batch_at = datetime.now(timezone.utc)

    def get_random_delay(self) -> float:
        """Get random delay between messages."""
        import random
        return random.uniform(self.message_delay_min, self.message_delay_max)


@dataclass
class CampaignStats:
    """
    Campaign statistics and metrics.

    Attributes:
        total_targets: Total users in campaign
        contacted: Users who received first message
        responded: Users who replied
        goals_reached: Users who received goal message
        completed: Successfully completed dialogues
        failed: Failed dialogues
        total_messages_sent: Total messages sent
        total_tokens_used: Total AI tokens consumed
    """

    total_targets: int = 0
    contacted: int = 0
    responded: int = 0
    goals_reached: int = 0
    completed: int = 0
    failed: int = 0
    total_messages_sent: int = 0
    total_tokens_used: int = 0

    @property
    def messages_sent(self) -> int:
        """Backward compatible alias (used by API/UI)."""
        return self.total_messages_sent

    @property
    def tokens_used(self) -> int:
        """Backward compatible alias (used by API/UI)."""
        return self.total_tokens_used

    @property
    def response_rate(self) -> float:
        """Calculate response rate percentage."""
        if self.contacted == 0:
            return 0.0
        return (self.responded / self.contacted) * 100
    
    @property
    def conversion_rate(self) -> float:
        """Calculate goal conversion rate percentage."""
        if self.contacted == 0:
            return 0.0
        return (self.goals_reached / self.contacted) * 100
    
    @property
    def completion_rate(self) -> float:
        """Calculate completion rate percentage."""
        if self.contacted == 0:
            return 0.0
        return (self.completed / self.contacted) * 100


@dataclass
class Campaign(AggregateRoot):
    """
    Outreach campaign entity.
    
    Defines the overall strategy and tracks progress for a
    coordinated outreach effort across multiple accounts.
    
    Attributes:
        name: Campaign name
        description: Campaign description
        status: Current campaign status
        goal: Campaign goal configuration
        prompt: LLM prompt configuration
        stats: Campaign statistics
        account_ids: Accounts assigned to this campaign
        start_date: Scheduled start date
        end_date: Scheduled end date
        owner_telegram_id: Admin who created the campaign
        ai_model: OpenAI model to use
        ai_temperature: LLM temperature setting
        ai_max_tokens: Max tokens per response
    """
    
    name: str = ""
    description: str = ""
    status: CampaignStatus = CampaignStatus.DRAFT
    
    goal: CampaignGoal = field(default_factory=CampaignGoal)
    prompt: CampaignPrompt = field(default_factory=CampaignPrompt)
    stats: CampaignStats = field(default_factory=CampaignStats)
    sending: CampaignSendingSettings = field(default_factory=CampaignSendingSettings)

    account_ids: list[UUID] = field(default_factory=list)
    
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None

    # Backward compatible aliases (used by API/UI)
    @property
    def started_at(self) -> Optional[datetime]:
        return self.start_date

    @started_at.setter
    def started_at(self, value: Optional[datetime]) -> None:
        self.start_date = value

    @property
    def completed_at(self) -> Optional[datetime]:
        return self.end_date

    @completed_at.setter
    def completed_at(self, value: Optional[datetime]) -> None:
        self.end_date = value
    
    owner_telegram_id: int = 0
    
    # AI settings
    ai_model: str = "gpt-4o-mini"
    ai_temperature: float = 0.7
    ai_max_tokens: int = 500
    
    def activate(self) -> None:
        """Start the campaign."""
        if self.status not in (CampaignStatus.DRAFT, CampaignStatus.READY, CampaignStatus.PAUSED):
            raise ValueError(f"Cannot activate campaign in {self.status} status")
        if not self.prompt.system_prompt:
            raise ValueError("Campaign requires system prompt")
        if not self.account_ids:
            raise ValueError("Campaign requires at least one account")
        
        self.status = CampaignStatus.ACTIVE
        if not self.start_date:
            self.start_date = datetime.utcnow()
        self.increment_version()
    
    def pause(self) -> None:
        """Pause the campaign."""
        if self.status != CampaignStatus.ACTIVE:
            raise ValueError("Can only pause active campaigns")
        self.status = CampaignStatus.PAUSED
        self.increment_version()
    
    def complete(self) -> None:
        """Mark campaign as completed."""
        self.status = CampaignStatus.COMPLETED
        self.end_date = datetime.utcnow()
        self.increment_version()
    
    def cancel(self) -> None:
        """Cancel the campaign."""
        self.status = CampaignStatus.CANCELLED
        self.end_date = datetime.utcnow()
        self.increment_version()
    
    def add_account(self, account_id: UUID) -> None:
        """Add an account to the campaign."""
        if account_id not in self.account_ids:
            self.account_ids.append(account_id)
            self.touch()
    
    def remove_account(self, account_id: UUID) -> None:
        """Remove an account from the campaign."""
        if account_id in self.account_ids:
            self.account_ids.remove(account_id)
            self.touch()
    
    def update_stats(
        self,
        contacted: int = 0,
        responded: int = 0,
        goals_reached: int = 0,
        completed: int = 0,
        failed: int = 0,
        messages_sent: int = 0,
        tokens_used: int = 0,
    ) -> None:
        """Increment campaign statistics."""
        self.stats.contacted += contacted
        self.stats.responded += responded
        self.stats.goals_reached += goals_reached
        self.stats.completed += completed
        self.stats.failed += failed
        self.stats.total_messages_sent += messages_sent
        self.stats.total_tokens_used += tokens_used
        self.touch()
    
    def is_active(self) -> bool:
        """Check if campaign is currently active."""
        return self.status == CampaignStatus.ACTIVE
    
    def get_system_prompt(self) -> str:
        """Get complete system prompt for LLM."""
        return self.prompt.build_system_prompt(self.goal)
