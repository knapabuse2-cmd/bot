"""
Domain layer module.

Contains business entities and domain exceptions.
This layer is independent of infrastructure and frameworks.
"""

from .entities import (
    # Base
    Entity,
    AggregateRoot,
    # Account
    Account,
    AccountStatus,
    AccountSchedule,
    AccountLimits,
    # Campaign
    Campaign,
    CampaignStatus,
    CampaignGoal,
    CampaignPrompt,
    CampaignStats,
    # Dialogue
    Dialogue,
    DialogueStatus,
    Message,
    MessageRole,
    # UserTarget
    UserTarget,
    TargetStatus,
    # Proxy
    Proxy,
    ProxyType,
    ProxyStatus,
)

from .exceptions import (
    DomainException,
    # Account
    AccountException,
    AccountNotFoundError,
    AccountAlreadyExistsError,
    AccountBannedError,
    AccountLimitExceededError,
    AccountNotConfiguredError,
    # Campaign
    CampaignException,
    CampaignNotFoundError,
    CampaignInvalidStateError,
    CampaignNotConfiguredError,
    # Dialogue
    DialogueException,
    DialogueNotFoundError,
    DialogueAlreadyExistsError,
    # Proxy
    ProxyException,
    ProxyNotFoundError,
    ProxyNotAvailableError,
    ProxyConnectionError,
    # Target
    TargetException,
    TargetNotFoundError,
    TargetAlreadyContactedError,
    # AI
    AIException,
    AIProviderError,
    AIRateLimitError,
    AIContextTooLongError,
    # Telegram
    TelegramException,
    TelegramAuthError,
    TelegramFloodError,
    TelegramUserNotFoundError,
    TelegramPrivacyError,
)

__all__ = [
    # Entities
    "Entity",
    "AggregateRoot",
    "Account",
    "AccountStatus",
    "AccountSchedule",
    "AccountLimits",
    "Campaign",
    "CampaignStatus",
    "CampaignGoal",
    "CampaignPrompt",
    "CampaignStats",
    "Dialogue",
    "DialogueStatus",
    "Message",
    "MessageRole",
    "UserTarget",
    "TargetStatus",
    "Proxy",
    "ProxyType",
    "ProxyStatus",
    # Exceptions
    "DomainException",
    "AccountException",
    "AccountNotFoundError",
    "AccountAlreadyExistsError",
    "AccountBannedError",
    "AccountLimitExceededError",
    "AccountNotConfiguredError",
    "CampaignException",
    "CampaignNotFoundError",
    "CampaignInvalidStateError",
    "CampaignNotConfiguredError",
    "DialogueException",
    "DialogueNotFoundError",
    "DialogueAlreadyExistsError",
    "ProxyException",
    "ProxyNotFoundError",
    "ProxyNotAvailableError",
    "ProxyConnectionError",
    "TargetException",
    "TargetNotFoundError",
    "TargetAlreadyContactedError",
    "AIException",
    "AIProviderError",
    "AIRateLimitError",
    "AIContextTooLongError",
    "TelegramException",
    "TelegramAuthError",
    "TelegramFloodError",
    "TelegramUserNotFoundError",
    "TelegramPrivacyError",
]
