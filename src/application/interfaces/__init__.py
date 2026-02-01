"""
Application interfaces module.
"""

from .repository import (
    Repository,
    AccountRepository,
    CampaignRepository,
    DialogueRepository,
    UserTargetRepository,
    ProxyRepository,
)

__all__ = [
    "Repository",
    "AccountRepository",
    "CampaignRepository",
    "DialogueRepository",
    "UserTargetRepository",
    "ProxyRepository",
]
