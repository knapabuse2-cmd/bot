"""
Telegram infrastructure module.

Provides Telegram client with human-like interaction capabilities.
"""

from .client import (
    TelegramWorkerClient,
    create_new_session,
)

__all__ = [
    "TelegramWorkerClient",
    "create_new_session",
]
