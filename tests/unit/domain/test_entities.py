"""
Unit tests for domain entities.
"""

from datetime import datetime, time, timedelta
from uuid import uuid4

import pytest

from src.domain.entities import (
    Account,
    AccountLimits,
    AccountSchedule,
    AccountStatus,
    Campaign,
    CampaignGoal,
    CampaignPrompt,
    CampaignStats,
    CampaignStatus,
    Dialogue,
    DialogueStatus,
    Message,
    MessageRole,
    UserTarget,
    TargetStatus,
)


class TestAccountSchedule:
    """Tests for AccountSchedule value object."""
    
    def test_default_schedule(self):
        """Test default schedule values."""
        schedule = AccountSchedule()
        
        assert schedule.start_time == time(9, 0)
        assert schedule.end_time == time(21, 0)
        assert schedule.active_days == [0, 1, 2, 3, 4, 5, 6]
        assert schedule.timezone == "UTC"
    
    def test_is_active_now_within_hours(self):
        """Test is_active_now when current time is within schedule."""
        schedule = AccountSchedule(
            start_time=time(0, 0),
            end_time=time(23, 59),
        )
        
        # Any time should be active
        now = datetime(2024, 1, 15, 12, 0)  # Monday noon
        assert schedule.is_active_now(now) is True
    
    def test_is_active_now_outside_hours(self):
        """Test is_active_now when current time is outside schedule."""
        schedule = AccountSchedule(
            start_time=time(9, 0),
            end_time=time(17, 0),
        )
        
        # 8 AM should be inactive
        early = datetime(2024, 1, 15, 8, 0)  # Monday 8 AM
        assert schedule.is_active_now(early) is False
        
        # 6 PM should be inactive
        late = datetime(2024, 1, 15, 18, 0)  # Monday 6 PM
        assert schedule.is_active_now(late) is False
    
    def test_is_active_now_inactive_day(self):
        """Test is_active_now on inactive day."""
        schedule = AccountSchedule(
            active_days=[0, 1, 2, 3, 4],  # Mon-Fri only
        )
        
        # Saturday at noon should be inactive
        saturday = datetime(2024, 1, 13, 12, 0)  # Saturday
        assert schedule.is_active_now(saturday) is False


class TestAccountLimits:
    """Tests for AccountLimits value object."""
    
    def test_default_limits(self):
        """Test default limit values."""
        limits = AccountLimits()
        
        assert limits.max_new_conversations_per_day == 20
        assert limits.max_messages_per_hour == 30
        assert limits.min_delay_between_messages == 30
        assert limits.max_delay_between_messages == 120
        assert limits.max_active_dialogues == 50
    
    def test_custom_limits(self):
        """Test custom limit values."""
        limits = AccountLimits(
            max_new_conversations_per_day=10,
            max_messages_per_hour=15,
        )
        
        assert limits.max_new_conversations_per_day == 10
        assert limits.max_messages_per_hour == 15


class TestAccount:
    """Tests for Account entity."""
    
    def test_create_account(self, account_factory):
        """Test account creation."""
        account = account_factory(phone="+79001234567")
        
        assert account.phone == "+79001234567"
        assert account.status == AccountStatus.ACTIVE
        assert account.id is not None
    
    def test_can_start_new_conversation_within_limit(self, account_factory):
        """Test can_start_new_conversation when under limit."""
        account = account_factory(
            daily_conversations_count=5,
        )
        account.limits.max_new_conversations_per_day = 20
        
        assert account.can_start_new_conversation() is True
    
    def test_can_start_new_conversation_at_limit(self, account_factory):
        """Test can_start_new_conversation when at limit."""
        account = account_factory(
            daily_conversations_count=20,
        )
        account.limits.max_new_conversations_per_day = 20
        
        assert account.can_start_new_conversation() is False
    
    def test_can_send_message_within_limit(self, account_factory):
        """Test can_send_message when under limit."""
        account = account_factory(
            hourly_messages_count=10,
        )
        account.limits.max_messages_per_hour = 30
        
        assert account.can_send_message() is True
    
    def test_can_send_message_at_limit(self, account_factory):
        """Test can_send_message when at limit."""
        account = account_factory(
            hourly_messages_count=30,
        )
        account.limits.max_messages_per_hour = 30
        
        assert account.can_send_message() is False
    
    def test_inactive_account_cannot_start_conversation(self, account_factory):
        """Test inactive account cannot start conversations."""
        account = account_factory(status=AccountStatus.INACTIVE)
        
        assert account.can_start_new_conversation() is False
    
    def test_banned_account_cannot_send_message(self, account_factory):
        """Test banned account cannot send messages."""
        account = account_factory(status=AccountStatus.BANNED)
        
        assert account.can_send_message() is False


class TestCampaignGoal:
    """Tests for CampaignGoal value object."""
    
    def test_default_goal(self):
        """Test default goal values."""
        goal = CampaignGoal()
        
        assert goal.target_message is None
        assert goal.target_url is None
        assert goal.min_messages_before_goal == 3
        assert goal.max_messages_before_goal == 10
    
    def test_is_configured_without_message(self):
        """Test is_configured without target message."""
        goal = CampaignGoal()
        
        assert goal.is_configured() is False
    
    def test_is_configured_with_message(self):
        """Test is_configured with target message."""
        goal = CampaignGoal(target_message="Check out our channel!")
        
        assert goal.is_configured() is True


class TestCampaignStats:
    """Tests for CampaignStats value object."""
    
    def test_response_rate_calculation(self):
        """Test response rate calculation."""
        stats = CampaignStats(
            contacted=100,
            responded=25,
        )
        
        assert stats.response_rate == 25.0
    
    def test_response_rate_no_contacts(self):
        """Test response rate with no contacts."""
        stats = CampaignStats(contacted=0)
        
        assert stats.response_rate == 0.0
    
    def test_conversion_rate_calculation(self):
        """Test conversion rate calculation."""
        stats = CampaignStats(
            contacted=100,
            goals_reached=10,
        )
        
        assert stats.conversion_rate == 10.0


class TestDialogue:
    """Tests for Dialogue entity."""
    
    def test_create_dialogue(self, dialogue_factory):
        """Test dialogue creation."""
        dialogue = dialogue_factory(telegram_user_id=12345)
        
        assert dialogue.telegram_user_id == 12345
        assert dialogue.status == DialogueStatus.ACTIVE
        assert len(dialogue.messages) == 0
    
    def test_add_message(self, dialogue_factory):
        """Test adding message to dialogue."""
        dialogue = dialogue_factory()
        
        msg = dialogue.add_message(
            message_id=uuid4(),
            role=MessageRole.ACCOUNT,
            content="Hello!",
        )
        
        assert len(dialogue.messages) == 1
        assert msg.role == MessageRole.ACCOUNT
        assert msg.content == "Hello!"
    
    def test_get_conversation_history(self, dialogue_factory):
        """Test getting conversation history in LLM format."""
        dialogue = dialogue_factory()
        
        dialogue.add_message(
            message_id=uuid4(),
            role=MessageRole.ACCOUNT,
            content="Hello!",
        )
        dialogue.add_message(
            message_id=uuid4(),
            role=MessageRole.USER,
            content="Hi there!",
        )
        
        history = dialogue.get_conversation_history()
        
        assert len(history) == 2
        assert history[0]["role"] == "assistant"
        assert history[0]["content"] == "Hello!"
        assert history[1]["role"] == "user"
        assert history[1]["content"] == "Hi there!"


class TestUserTarget:
    """Tests for UserTarget entity."""
    
    def test_create_target(self, target_factory):
        """Test target creation."""
        target = target_factory(telegram_id=12345)
        
        assert target.telegram_id == 12345
        assert target.status == TargetStatus.PENDING
    
    def test_assign_to_account(self, target_factory):
        """Test assigning target to account."""
        target = target_factory()
        account_id = uuid4()
        
        target.assign_to_account(account_id)
        
        assert target.assigned_account_id == account_id
        assert target.status == TargetStatus.ASSIGNED
    
    def test_mark_contacted(self, target_factory):
        """Test marking target as contacted."""
        target = target_factory()
        
        target.mark_contacted()
        
        assert target.status == TargetStatus.CONTACTED
        assert target.contact_attempts == 1
    
    def test_mark_failed(self, target_factory):
        """Test marking target as failed."""
        target = target_factory()
        
        target.mark_failed("privacy_settings")
        
        assert target.status == TargetStatus.FAILED
        assert target.fail_reason == "privacy_settings"
