"""
Database infrastructure module.
"""

from .connection import (
    Base,
    AsyncSession,
    get_engine,
    get_session_factory,
    get_session,
    init_database,
    close_database,
)
from .models import (
    AccountModel,
    CampaignModel,
    DialogueModel,
    MessageModel,
    UserTargetModel,
    ProxyModel,
)
from .repositories import (
    PostgresAccountRepository,
    PostgresCampaignRepository,
    PostgresDialogueRepository,
    PostgresUserTargetRepository,
    PostgresProxyRepository,
)

__all__ = [
    # Connection
    "Base",
    "AsyncSession",
    "get_engine",
    "get_session_factory",
    "get_session",
    "init_database",
    "close_database",
    # Models
    "AccountModel",
    "CampaignModel",
    "DialogueModel",
    "MessageModel",
    "UserTargetModel",
    "ProxyModel",
    # Repositories
    "PostgresAccountRepository",
    "PostgresCampaignRepository",
    "PostgresDialogueRepository",
    "PostgresUserTargetRepository",
    "PostgresProxyRepository",
]
