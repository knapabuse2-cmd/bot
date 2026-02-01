"""
Application services.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .account_auth import (
    AccountAuthService,
    AuthSession,
    AuthState,
    get_auth_service,
)
from .dialogue_processor import (
    DialogueProcessor,
    DialogueAction,
    ParsedResponse,
    ResponseParser,
    MessageBatcher,
    TypingSimulator,
)

# NOTE:
# Some services depend on optional/heavier infrastructure (e.g. AI providers).
# To keep imports lightweight (and avoid accidental import-time side effects),
# we expose core service classes via lazy module attribute loading.

__all__ = [
    # Auth
    "AccountAuthService",
    "AuthSession",
    "AuthState",
    "get_auth_service",
    # Dialogue
    "DialogueProcessor",
    "DialogueAction",
    "ParsedResponse",
    "ResponseParser",
    "MessageBatcher",
    "TypingSimulator",

    # Core services (lazy)
    "AccountService",
    "CampaignService",
    "DialogueService",
    "ScraperService",
    "ParallelScraperService",
    "create_targets_from_usernames",
]


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "AccountService": (".account_service", "AccountService"),
    "CampaignService": (".campaign_service", "CampaignService"),
    "DialogueService": (".dialogue_service", "DialogueService"),
    "ScraperService": (".scraper_service", "ScraperService"),
    "ParallelScraperService": (".scraper_service", "ParallelScraperService"),
    "create_targets_from_usernames": (".scraper_service", "create_targets_from_usernames"),
}


def __getattr__(name: str) -> Any:  # pragma: no cover
    """Lazy-load selected service classes on demand.

    This allows modules to do:
        from src.application.services import AccountService

    without forcing import of all services (some of which may pull in
    optional dependencies) at package import time.
    """

    if name in _LAZY_EXPORTS:
        module_path, attr = _LAZY_EXPORTS[name]
        module = import_module(module_path, __name__)
        value = getattr(module, attr)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
