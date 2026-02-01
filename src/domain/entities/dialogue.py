"""
Dialogue entity representing a conversation between an account and target user.

A Dialogue tracks the full conversation history, state, and progress
toward the campaign goal.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from .base import AggregateRoot


class DialogueStatus(str, Enum):
    """Possible states of a dialogue."""
    
    PENDING = "pending"             # Scheduled but not started
    INITIATED = "initiated"         # First message sent, waiting response
    ACTIVE = "active"               # Ongoing conversation
    GOAL_REACHED = "goal_reached"   # Target message delivered
    COMPLETED = "completed"         # Successfully finished
    FAILED = "failed"               # User blocked/ignored/negative response
    PAUSED = "paused"               # Temporarily paused
    EXPIRED = "expired"             # Timed out waiting for response


class MessageRole(str, Enum):
    """Who sent the message."""
    
    ACCOUNT = "account"   # Our worker account
    USER = "user"         # Target user


@dataclass
class Message:
    """
    A single message in a dialogue.
    
    Attributes:
        id: Unique message identifier
        role: Who sent the message
        content: Message text content
        timestamp: When the message was sent
        telegram_message_id: Original Telegram message ID
        ai_generated: Whether this was AI-generated
        tokens_used: Tokens consumed for AI generation (if applicable)
        is_follow_up: Whether this is a follow-up message
    """
    
    id: UUID
    role: MessageRole
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    telegram_message_id: Optional[int] = None
    ai_generated: bool = False
    tokens_used: int = 0
    is_follow_up: bool = False
    
    def to_llm_format(self) -> dict:
        """Convert to OpenAI message format."""
        role = "assistant" if self.role == MessageRole.ACCOUNT else "user"
        return {"role": role, "content": self.content}


@dataclass
class Dialogue(AggregateRoot):
    """
    Conversation entity between worker account and target user.
    
    Tracks the full history and state of interaction with a single user.
    
    Attributes:
        account_id: Worker account handling this dialogue
        campaign_id: Campaign this dialogue belongs to
        target_user_id: Reference to target user entity
        telegram_user_id: Telegram ID of the target user
        telegram_username: Username of target user (if known)
        status: Current dialogue status
        messages: List of all messages in conversation
        goal_message_sent: Whether the goal message was delivered
        goal_message_sent_at: When the goal was reached
        next_action_at: When to take next action (send message/follow up)
        retry_count: Number of retry attempts
        max_retries: Maximum retries before marking failed
        last_user_response_at: Last time user responded
        sentiment_score: Estimated user sentiment (-1 to 1)
        notes: Admin notes about this dialogue
    """
    
    account_id: UUID = field(default_factory=lambda: UUID(int=0))
    campaign_id: UUID = field(default_factory=lambda: UUID(int=0))
    target_user_id: UUID = field(default_factory=lambda: UUID(int=0))
    
    telegram_user_id: int = 0
    telegram_username: Optional[str] = None
    
    status: DialogueStatus = DialogueStatus.PENDING
    messages: list[Message] = field(default_factory=list)
    
    # Goal tracking
    goal_message_sent: bool = False
    goal_message_sent_at: Optional[datetime] = None
    
    # Scheduling
    next_action_at: Optional[datetime] = None
    
    # Retry logic
    retry_count: int = 0
    max_retries: int = 3
    
    # Analytics
    last_user_response_at: Optional[datetime] = None
    sentiment_score: Optional[float] = None
    interest_score: int = 0  # Accumulated interest from user messages
    link_sent_count: int = 0  # How many times we sent the link
    
    notes: str = ""
    fail_reason: Optional[str] = None
    needs_review: bool = False
    creative_sent: bool = False

    # Backward compatible aliases (used by API/UI)
    @property
    def target_id(self) -> UUID:
        return self.target_user_id

    @target_id.setter
    def target_id(self, value: UUID) -> None:
        self.target_user_id = value

    @property
    def target_telegram_id(self) -> int:
        return self.telegram_user_id

    @target_telegram_id.setter
    def target_telegram_id(self, value: int) -> None:
        self.telegram_user_id = int(value or 0)

    @property
    def target_username(self) -> Optional[str]:
        return self.telegram_username

    @target_username.setter
    def target_username(self, value: Optional[str]) -> None:
        self.telegram_username = value

    @property
    def goal_reached(self) -> bool:
        return bool(self.goal_message_sent)

    @goal_reached.setter
    def goal_reached(self, value: bool) -> None:
        self.goal_message_sent = bool(value)

    @property
    def goal_reached_at(self) -> Optional[datetime]:
        return self.goal_message_sent_at

    @goal_reached_at.setter
    def goal_reached_at(self, value: Optional[datetime]) -> None:
        self.goal_message_sent_at = value

    @property
    def messages_count(self) -> int:
        return len(self.messages)

    @property
    def last_message_at(self) -> Optional[datetime]:
        if not self.messages:
            return None
        return max(m.timestamp for m in self.messages)

    
    def add_message(
        self,
        message_id: UUID,
        role: MessageRole,
        content: str,
        telegram_message_id: Optional[int] = None,
        ai_generated: bool = False,
        tokens_used: int = 0,
        is_follow_up: bool = False,
    ) -> Message:
        """
        Add a message to the dialogue.
        
        Args:
            message_id: Unique ID for the message
            role: Who sent it (account or user)
            content: Message text
            telegram_message_id: Original Telegram message ID
            ai_generated: Whether AI generated this
            tokens_used: Tokens consumed for generation
            is_follow_up: Whether this is a follow-up message
            
        Returns:
            The created Message object
        """
        message = Message(
            id=message_id,
            role=role,
            content=content,
            telegram_message_id=telegram_message_id,
            ai_generated=ai_generated,
            tokens_used=tokens_used,
            is_follow_up=is_follow_up,
        )
        self.messages.append(message)
        
        if role == MessageRole.USER:
            self.last_user_response_at = message.timestamp
            if self.status == DialogueStatus.INITIATED:
                self.status = DialogueStatus.ACTIVE
        
        self.touch()
        return message
    
    def get_conversation_history(self, max_messages: int = 20) -> list[dict]:
        """
        Get conversation history in OpenAI format.
        
        Args:
            max_messages: Maximum number of recent messages to include
            
        Returns:
            List of messages in OpenAI chat format
        """
        recent = self.messages[-max_messages:] if len(self.messages) > max_messages else self.messages
        return [msg.to_llm_format() for msg in recent]
    
    def mark_initiated(self) -> None:
        """Mark dialogue as initiated (first message sent)."""
        self.status = DialogueStatus.INITIATED
        self.increment_version()
    
    def mark_goal_reached(self) -> None:
        """Mark that the campaign goal was achieved."""
        self.goal_message_sent = True
        self.goal_message_sent_at = datetime.utcnow()
        self.status = DialogueStatus.GOAL_REACHED
        self.increment_version()
    
    def mark_completed(self) -> None:
        """Mark dialogue as successfully completed."""
        self.status = DialogueStatus.COMPLETED
        self.increment_version()
    
    def mark_failed(self, reason: str = "") -> None:
        """Mark dialogue as failed."""
        self.status = DialogueStatus.FAILED
        if reason:
            self.fail_reason = reason
            self.notes = f"{self.notes}\nFailed: {reason}".strip()
        self.increment_version()
    
    def mark_expired(self) -> None:
        """Mark dialogue as expired (no response timeout)."""
        self.status = DialogueStatus.EXPIRED
        self.increment_version()
    
    def should_retry(self) -> bool:
        """Check if dialogue should retry contact."""
        return (
            self.status in (DialogueStatus.INITIATED, DialogueStatus.ACTIVE)
            and self.retry_count < self.max_retries
        )
    
    def increment_retry(self) -> None:
        """Increment retry counter."""
        self.retry_count += 1
        self.touch()
    
    def get_message_count(self) -> int:
        """Get total message count."""
        return len(self.messages)
    
    def get_user_message_count(self) -> int:
        """Get count of messages from user."""
        return sum(1 for m in self.messages if m.role == MessageRole.USER)
    
    def get_last_message(self) -> Optional[Message]:
        """Get the most recent message."""
        return self.messages[-1] if self.messages else None
    
    def get_last_user_message(self) -> Optional[Message]:
        """Get the most recent message from user."""
        for msg in reversed(self.messages):
            if msg.role == MessageRole.USER:
                return msg
        return None
    
    def is_waiting_for_user(self) -> bool:
        """Check if we're waiting for user response."""
        last = self.get_last_message()
        return last is not None and last.role == MessageRole.ACCOUNT
    
    def get_follow_up_count(self) -> int:
        """Get count of follow-up messages sent."""
        return sum(1 for m in self.messages if m.is_follow_up)
    
    def get_tokens_used(self) -> int:
        """Get total tokens used in dialogue."""
        return sum(m.tokens_used for m in self.messages)
