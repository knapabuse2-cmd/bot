"""
Account service.

Handles business logic for account management operations.
"""

from typing import Optional
from uuid import UUID

import structlog

from src.application.interfaces.repository import AccountRepository, ProxyRepository
from src.domain.entities import Account, AccountSource, AccountStatus, Proxy
from src.domain.exceptions import (
    AccountAlreadyExistsError,
    AccountNotConfiguredError,
    AccountNotFoundError,
    ProxyNotAvailableError,
)

logger = structlog.get_logger(__name__)


class AccountService:
    """
    Service for account management operations.
    
    Handles:
    - Account creation and configuration
    - Proxy assignment
    - Status management
    - Counter resets
    """
    
    def __init__(
        self,
        account_repo: AccountRepository,
        proxy_repo: ProxyRepository,
    ):
        """
        Initialize service.
        
        Args:
            account_repo: Account repository
            proxy_repo: Proxy repository
        """
        self.account_repo = account_repo
        # Backward compatible aliases (used in presentation layer)
        self._account_repo = account_repo

        self.proxy_repo = proxy_repo
        self._proxy_repo = proxy_repo
    
    async def create_account(
        self,
        phone: str,
        session_data: Optional[bytes] = None,
        source: AccountSource = AccountSource.PHONE,
    ) -> Account:
        """
        Create a new account.

        Args:
            phone: Phone number
            session_data: Encrypted session data (optional)
            source: How the account was added (phone, json_session, tdata)

        Returns:
            Created account

        Raises:
            AccountAlreadyExistsError: If phone already registered
        """
        existing = await self.account_repo.get_by_phone(phone)
        if existing:
            raise AccountAlreadyExistsError(phone)

        account = Account(
            phone=phone,
            session_data=session_data,
            source=source,
            status=AccountStatus.INACTIVE if not session_data else AccountStatus.READY,
        )
        
        saved = await self.account_repo.save(account)
        
        logger.info(
            "Account created",
            account_id=str(saved.id),
            phone=phone,
        )
        
        return saved
    
    async def get_account(self, account_id: UUID) -> Account:
        """
        Get account by ID.
        
        Args:
            account_id: Account UUID
            
        Returns:
            Account entity
            
        Raises:
            AccountNotFoundError: If not found
        """
        account = await self.account_repo.get_by_id(account_id)
        if not account:
            raise AccountNotFoundError(str(account_id))
        return account
    
    async def update_session(
        self,
        account_id: UUID,
        session_data: bytes,
        telegram_id: Optional[int] = None,
        username: Optional[str] = None,
        first_name: str = "",
        last_name: str = "",
    ) -> Account:
        """
        Update account session data.
        
        Args:
            account_id: Account UUID
            session_data: Encrypted session data
            telegram_id: Telegram user ID
            username: Telegram username
            first_name: First name
            last_name: Last name
            
        Returns:
            Updated account
        """
        account = await self.get_account(account_id)
        
        account.session_data = session_data
        if telegram_id:
            account.telegram_id = telegram_id
        if username:
            account.username = username
        account.first_name = first_name
        account.last_name = last_name
        
        # Update status to READY if was INACTIVE
        if account.status == AccountStatus.INACTIVE:
            account.status = AccountStatus.READY
        
        saved = await self.account_repo.save(account)
        
        logger.info(
            "Account session updated",
            account_id=str(account_id),
            telegram_id=telegram_id,
        )
        
        return saved
    
    async def assign_proxy(
        self,
        account_id: UUID,
        proxy_id: Optional[UUID] = None,
    ) -> Account:
        """
        Assign a proxy to an account.
        
        If proxy_id is None, assigns an available proxy automatically.
        
        Args:
            account_id: Account UUID
            proxy_id: Specific proxy UUID (optional)
            
        Returns:
            Updated account
            
        Raises:
            ProxyNotAvailableError: If no proxy available
        """
        account = await self.get_account(account_id)
        
        if proxy_id:
            proxy = await self.proxy_repo.get_by_id(proxy_id)
            if not proxy or not proxy.is_available():
                raise ProxyNotAvailableError("Specified proxy not available")
        else:
            # Get first available proxy
            available = await self.proxy_repo.list_available(limit=1)
            if not available:
                raise ProxyNotAvailableError("No proxies available")
            proxy = available[0]
        
        # Release old proxy if switching
        old_proxy_id = account.proxy_id
        if old_proxy_id and old_proxy_id != proxy.id:
            old_proxy = await self.proxy_repo.get_by_id(old_proxy_id)
            if old_proxy:
                old_proxy.assigned_account_id = None
                await self.proxy_repo.save(old_proxy)

        # Update both sides of the relationship to keep them in sync
        account.proxy_id = proxy.id
        proxy.assigned_account_id = account.id

        await self.proxy_repo.save(proxy)
        saved = await self.account_repo.save(account)

        logger.info(
            "Proxy assigned to account",
            account_id=str(account_id),
            proxy_id=str(proxy.id),
        )

        return saved
    
    async def activate_account(self, account_id: UUID) -> Account:
        """
        Activate an account for operation.
        
        Args:
            account_id: Account UUID
            
        Returns:
            Activated account
            
        Raises:
            AccountNotConfiguredError: If not fully configured
        """
        account = await self.get_account(account_id)
        
        if not account.session_data:
            raise AccountNotConfiguredError(str(account_id), "session_data")
        if not account.proxy_id:
            raise AccountNotConfiguredError(str(account_id), "proxy")
        
        account.activate()
        saved = await self.account_repo.save(account)
        
        logger.info(
            "Account activated",
            account_id=str(account_id),
        )
        
        return saved
    
    async def pause_account(self, account_id: UUID) -> Account:
        """Pause an account."""
        account = await self.get_account(account_id)
        account.pause()
        saved = await self.account_repo.save(account)
        
        logger.info("Account paused", account_id=str(account_id))
        return saved
    
    async def set_account_error(
        self,
        account_id: UUID,
        error_message: str,
    ) -> Account:
        """Set account to error state."""
        account = await self.get_account(account_id)
        account.set_error(error_message)
        saved = await self.account_repo.save(account)
        
        logger.warning(
            "Account error",
            account_id=str(account_id),
            error=error_message,
        )
        return saved
    
    async def set_account_banned(self, account_id: UUID) -> Account:
        """Mark account as banned."""
        account = await self.get_account(account_id)
        account.set_banned()
        saved = await self.account_repo.save(account)
        
        logger.error("Account banned", account_id=str(account_id))
        return saved
    
    async def record_message_sent(self, account_id: UUID) -> None:
        """Record that a cold outreach message was sent."""
        account = await self.get_account(account_id)
        account.record_message_sent()
        await self.account_repo.save(account)

    async def record_response_sent(self, account_id: UUID) -> None:
        """Record that a response to incoming message was sent."""
        account = await self.get_account(account_id)
        account.record_response_sent()
        await self.account_repo.save(account)

    async def record_new_conversation(self, account_id: UUID) -> None:
        """Record that a new conversation was started."""
        account = await self.get_account(account_id)
        account.record_new_conversation()
        await self.account_repo.save(account)
    

    async def increment_message_count(self, account_id: UUID) -> None:
        # Backward compatible counter update.
        # If the repo provides atomic increment methods we use them,
        # otherwise we fall back to load+save.
        inc = getattr(self.account_repo, "increment_message_count", None)
        if callable(inc):
            await inc(account_id)
            return
        await self.record_message_sent(account_id)

    async def increment_conversation_count(self, account_id: UUID) -> None:
        inc = getattr(self.account_repo, "increment_conversation_count", None)
        if callable(inc):
            await inc(account_id)
            return
        await self.record_new_conversation(account_id)

    async def list_active_accounts(self) -> list[Account]:
        """List all active accounts."""
        return await self.account_repo.list_active()
    
    async def list_accounts_by_campaign(
        self,
        campaign_id: UUID,
    ) -> list[Account]:
        """List accounts assigned to a campaign."""
        return await self.account_repo.list_by_campaign(campaign_id)
    
    async def get_account_stats(self) -> dict:
        """Get account statistics."""
        active = await self.account_repo.count_by_status(AccountStatus.ACTIVE)
        ready = await self.account_repo.count_by_status(AccountStatus.READY)
        paused = await self.account_repo.count_by_status(AccountStatus.PAUSED)
        error = await self.account_repo.count_by_status(AccountStatus.ERROR)
        banned = await self.account_repo.count_by_status(AccountStatus.BANNED)
        
        return {
            "active": active,
            "ready": ready,
            "paused": paused,
            "error": error,
            "banned": banned,
            "total": active + ready + paused + error + banned,
        }
