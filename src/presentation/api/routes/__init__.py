"""
API routes module.
"""

from .accounts import router as accounts_router
from .campaigns import router as campaigns_router
from .proxies import router as proxies_router
from .stats import router as stats_router
from .dialogues import router as dialogues_router
from .premium import router as premium_router

__all__ = [
    "accounts_router",
    "campaigns_router",
    "proxies_router",
    "stats_router",
    "dialogues_router",
    "premium_router",
]
