"""
Infrastructure layer module.
"""

from .database import (
    Base,
    get_session,
    init_database,
    close_database,
    PostgresAccountRepository,
    PostgresCampaignRepository,
    PostgresDialogueRepository,
    PostgresUserTargetRepository,
    PostgresProxyRepository,
)
from .ai import (
    OpenAIProvider,
    AIResponse,
    get_ai_provider,
    close_ai_provider,
)
from .telegram import (
    TelegramWorkerClient,
    create_new_session,
)

__all__ = [
    # Database
    "Base",
    "get_session",
    "init_database",
    "close_database",
    "PostgresAccountRepository",
    "PostgresCampaignRepository",
    "PostgresDialogueRepository",
    "PostgresUserTargetRepository",
    "PostgresProxyRepository",
    # AI
    "OpenAIProvider",
    "AIResponse",
    "get_ai_provider",
    "close_ai_provider",
    # Telegram
    "TelegramWorkerClient",
    "create_new_session",
]
