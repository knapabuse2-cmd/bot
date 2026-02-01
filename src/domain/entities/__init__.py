"""
Domain entities module.

Contains all business entities that represent the core
concepts of the outreach system.
"""

from .base import Entity, AggregateRoot
from .account import (
    Account,
    AccountSource,
    AccountStatus,
    AccountSchedule,
    AccountLimits,
)
from .campaign import (
    Campaign,
    CampaignStatus,
    CampaignGoal,
    CampaignPrompt,
    CampaignStats,
    CampaignSendingSettings,
)
from .dialogue import (
    Dialogue,
    DialogueStatus,
    Message,
    MessageRole,
)
from .user_target import (
    UserTarget,
    TargetStatus,
    TargetStatus as UserTargetStatus,  # Alias for backward compatibility
)
from .proxy import (
    Proxy,
    ProxyType,
    ProxyStatus,
)
from .telegram_app import TelegramApp
from .scrape_task import (
    ScrapeTask,
    ScrapeTaskStatus,
)
from .warmup import (
    WarmupStatus,
    ActivityPattern,
    WarmupStage,
    WarmupProfile,
    AccountWarmup,
    AccountPersona,
    InterestCategory,
    WarmupChannel,
    WarmupGroup,
    AccountGroup,
    ProxyGroup,
    WarmupActivityLog,
)

__all__ = [
    # Base
    "Entity",
    "AggregateRoot",
    # Account
    "Account",
    "AccountSource",
    "AccountStatus",
    "AccountSchedule",
    "AccountLimits",
    # Campaign
    "Campaign",
    "CampaignStatus",
    "CampaignGoal",
    "CampaignPrompt",
    "CampaignStats",
    "CampaignSendingSettings",
    # Dialogue
    "Dialogue",
    "DialogueStatus",
    "Message",
    "MessageRole",
    # UserTarget
    "UserTarget",
    "TargetStatus",
    "UserTargetStatus",
    # Proxy
    "Proxy",
    "ProxyType",
    "ProxyStatus",
    # TelegramApp
    "TelegramApp",
    # ScrapeTask
    "ScrapeTask",
    "ScrapeTaskStatus",
    # Warmup
    "WarmupStatus",
    "ActivityPattern",
    "WarmupStage",
    "WarmupProfile",
    "AccountWarmup",
    "AccountPersona",
    "InterestCategory",
    "WarmupChannel",
    "WarmupGroup",
    "AccountGroup",
    "ProxyGroup",
    "WarmupActivityLog",
]
