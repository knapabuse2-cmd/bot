"""
TelegramApp entity representing API credentials configuration.

Each Telegram app (api_id/api_hash pair) should be used by a limited
number of accounts to avoid detection and rate limiting.
Recommendation: ~20-30 accounts per API ID.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import UUID

from .base import AggregateRoot


@dataclass
class TelegramApp(AggregateRoot):
    """
    Telegram API application credentials.

    Created at https://my.telegram.org/apps

    Attributes:
        api_id: Telegram API ID
        api_hash: Telegram API Hash
        name: Friendly name for the app
        description: Optional description
        max_accounts: Maximum accounts that can use this app
        current_account_count: Current number of accounts using this app
        is_active: Whether new accounts can be assigned to this app
        notes: Admin notes
    """

    api_id: int = 0
    api_hash: str = ""

    name: str = ""
    description: str = ""

    # Limits
    max_accounts: int = 25  # Default limit: 25 accounts per app
    current_account_count: int = 0

    # Status
    is_active: bool = True

    # Metadata
    notes: str = ""

    @property
    def is_available(self) -> bool:
        """Check if this app can accept more accounts."""
        return self.is_active and self.current_account_count < self.max_accounts

    @property
    def available_slots(self) -> int:
        """Get number of available account slots."""
        return max(0, self.max_accounts - self.current_account_count)

    @property
    def usage_percent(self) -> float:
        """Get usage percentage."""
        if self.max_accounts == 0:
            return 100.0
        return (self.current_account_count / self.max_accounts) * 100

    def increment_account_count(self) -> None:
        """Increment account count when account is assigned."""
        self.current_account_count += 1
        self.touch()

    def decrement_account_count(self) -> None:
        """Decrement account count when account is unassigned."""
        if self.current_account_count > 0:
            self.current_account_count -= 1
        self.touch()

    def activate(self) -> None:
        """Activate the app for new account assignments."""
        self.is_active = True
        self.touch()

    def deactivate(self) -> None:
        """Deactivate the app (no new assignments)."""
        self.is_active = False
        self.touch()
