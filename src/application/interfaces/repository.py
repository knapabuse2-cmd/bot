"""
Abstract repository interfaces.

Defines contracts for data access that the application layer
depends on. Implementations are in the infrastructure layer.
"""

from abc import ABC, abstractmethod
from typing import Generic, Optional, TypeVar
from uuid import UUID

from src.domain.entities import (
    Account,
    AccountStatus,
    Campaign,
    CampaignStatus,
    Dialogue,
    DialogueStatus,
    Message,
    Proxy,
    ProxyStatus,
    TargetStatus,
    UserTarget,
)

T = TypeVar("T")


class Repository(ABC, Generic[T]):
    """
    Base repository interface.
    
    Defines common CRUD operations for all entities.
    """
    
    @abstractmethod
    async def get_by_id(self, entity_id: UUID) -> Optional[T]:
        """Get entity by ID."""
        pass
    
    @abstractmethod
    async def save(self, entity: T) -> T:
        """Save entity (create or update)."""
        pass
    
    @abstractmethod
    async def delete(self, entity_id: UUID) -> bool:
        """Delete entity by ID. Returns True if deleted."""
        pass
    
    @abstractmethod
    async def list_all(self, limit: int = 100, offset: int = 0) -> list[T]:
        """List all entities with pagination."""
        pass


class AccountRepository(Repository[Account]):
    """Repository interface for Account entities."""
    
    @abstractmethod
    async def get_by_phone(self, phone: str) -> Optional[Account]:
        """Get account by phone number."""
        pass
    
    @abstractmethod
    async def get_by_telegram_id(self, telegram_id: int) -> Optional[Account]:
        """Get account by Telegram user ID."""
        pass
    
    @abstractmethod
    async def list_by_status(
        self,
        status: AccountStatus,
        limit: int = 100,
    ) -> list[Account]:
        """List accounts by status."""
        pass
    
    @abstractmethod
    async def list_by_campaign(
        self,
        campaign_id: UUID,
        limit: int = 100,
    ) -> list[Account]:
        """List accounts assigned to a campaign."""
        pass
    
    @abstractmethod
    async def list_active(self) -> list[Account]:
        """List all active accounts."""
        pass
    
    @abstractmethod
    async def count_by_status(self, status: AccountStatus) -> int:
        """Count accounts by status."""
        pass


class CampaignRepository(Repository[Campaign]):
    """Repository interface for Campaign entities."""
    
    @abstractmethod
    async def get_by_name(self, name: str) -> Optional[Campaign]:
        """Get campaign by name."""
        pass
    
    @abstractmethod
    async def list_by_status(
        self,
        status: CampaignStatus,
        limit: int = 100,
    ) -> list[Campaign]:
        """List campaigns by status."""
        pass
    
    @abstractmethod
    async def list_by_owner(
        self,
        owner_telegram_id: int,
        limit: int = 100,
    ) -> list[Campaign]:
        """List campaigns by owner."""
        pass
    
    @abstractmethod
    async def list_active(self) -> list[Campaign]:
        """List all active campaigns."""
        pass
    
    @abstractmethod
    async def update_stats(
        self,
        campaign_id: UUID,
        contacted: int = 0,
        responded: int = 0,
        goals_reached: int = 0,
        completed: int = 0,
        failed: int = 0,
        messages_sent: int = 0,
        tokens_used: int = 0,
    ) -> None:
        """Update campaign statistics."""
        pass


class DialogueRepository(Repository[Dialogue]):
    """Repository interface for Dialogue entities."""
    
    @abstractmethod
    async def get_by_account_and_user(
        self,
        account_id: UUID,
        telegram_user_id: int,
        telegram_username: Optional[str] = None,
    ) -> Optional[Dialogue]:
        """Get dialogue by account and Telegram user."""
        pass
    
    @abstractmethod
    async def list_by_account(
        self,
        account_id: UUID,
        status: Optional[DialogueStatus] = None,
        limit: int = 100,
    ) -> list[Dialogue]:
        """List dialogues for an account."""
        pass
    
    @abstractmethod
    async def list_by_campaign(
        self,
        campaign_id: UUID,
        status: Optional[DialogueStatus] = None,
        limit: int = 100,
    ) -> list[Dialogue]:
        """List dialogues for a campaign."""
        pass
    
    @abstractmethod
    async def list_pending_actions(
        self,
        account_id: Optional[UUID] = None,
        limit: int = 100,
    ) -> list[Dialogue]:
        """List dialogues that need action (next_action_at passed)."""
        pass
    
    @abstractmethod
    async def add_message(
        self,
        dialogue_id: UUID,
        message: Message,
    ) -> Dialogue:
        """Add a message to a dialogue."""
        pass
    
    @abstractmethod
    async def count_active_by_account(self, account_id: UUID) -> int:
        """Count active dialogues for an account."""
        pass


class UserTargetRepository(Repository[UserTarget]):
    """Repository interface for UserTarget entities."""
    
    @abstractmethod
    async def get_by_telegram_id(
        self,
        campaign_id: UUID,
        telegram_id: int,
    ) -> Optional[UserTarget]:
        """Get target by Telegram ID within a campaign."""
        pass
    
    @abstractmethod
    async def get_by_username(
        self,
        campaign_id: UUID,
        username: str,
    ) -> Optional[UserTarget]:
        """Get target by username within a campaign."""
        pass
    
    @abstractmethod
    async def list_by_campaign(
        self,
        campaign_id: UUID,
        status: Optional[TargetStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UserTarget]:
        """List targets for a campaign."""
        pass
    
    @abstractmethod
    async def list_pending(
        self,
        campaign_id: UUID,
        limit: int = 100,
    ) -> list[UserTarget]:
        """List pending targets ready to be assigned."""
        pass
    
    @abstractmethod
    async def list_scheduled(
        self,
        account_id: UUID,
        limit: int = 100,
    ) -> list[UserTarget]:
        """List targets scheduled for an account."""
        pass
    
    @abstractmethod
    async def bulk_create(
        self,
        targets: list[UserTarget],
    ) -> int:
        """Bulk create targets. Returns count created."""
        pass
    
    @abstractmethod
    async def count_by_campaign(
        self,
        campaign_id: UUID,
        status: Optional[TargetStatus] = None,
    ) -> int:
        """Count targets in a campaign."""
        pass


class ProxyRepository(Repository[Proxy]):
    """Repository interface for Proxy entities."""
    
    @abstractmethod
    async def get_by_address(self, host: str, port: int) -> Optional[Proxy]:
        """Get proxy by host and port."""
        pass
    
    @abstractmethod
    async def list_available(self, limit: int = 100) -> list[Proxy]:
        """List available (unassigned) proxies."""
        pass
    
    @abstractmethod
    async def list_by_status(
        self,
        status: ProxyStatus,
        limit: int = 100,
    ) -> list[Proxy]:
        """List proxies by status."""
        pass
    
    @abstractmethod
    async def get_for_account(self, account_id: UUID) -> Optional[Proxy]:
        """Get proxy assigned to an account."""
        pass
    
    @abstractmethod
    async def bulk_create(self, proxies: list[Proxy]) -> int:
        """Bulk create proxies. Returns count created."""
        pass
    
    @abstractmethod
    async def count_available(self) -> int:
        """Count available proxies."""
        pass
