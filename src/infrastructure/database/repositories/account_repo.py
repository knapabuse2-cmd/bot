"""
Account repository implementation.

Handles persistence for Telegram accounts with support for
counter management and status tracking.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, func, select, update

from src.application.interfaces.repository import AccountRepository
from src.domain.entities import Account, AccountStatus
from src.infrastructure.database.mappers import (
    account_entity_to_model,
    account_model_to_entity,
)
from src.infrastructure.database.models import AccountModel

from .base import BaseRepository


class PostgresAccountRepository(
    BaseRepository[AccountModel, Account],
    AccountRepository,
):
    """PostgreSQL implementation of AccountRepository."""
    
    model_class = AccountModel
    
    def _to_entity(self, model: AccountModel) -> Account:
        return account_model_to_entity(model)
    
    def _to_model(
        self,
        entity: Account,
        model: Optional[AccountModel] = None,
    ) -> AccountModel:
        return account_entity_to_model(entity, model)
    
    async def get_by_phone(self, phone: str) -> Optional[Account]:
        """Get account by phone number."""
        stmt = select(AccountModel).where(AccountModel.phone == phone)
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        
        if model is None:
            return None
        
        return self._to_entity(model)
    
    async def get_by_telegram_id(self, telegram_id: int) -> Optional[Account]:
        """Get account by Telegram user ID."""
        stmt = select(AccountModel).where(
            AccountModel.telegram_id == telegram_id
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        
        if model is None:
            return None
        
        return self._to_entity(model)
    
    async def list_by_status(
        self,
        status: AccountStatus,
        limit: int = 100,
    ) -> list[Account]:
        """List accounts by status."""
        stmt = (
            select(AccountModel)
            .where(AccountModel.status == status)
            .order_by(AccountModel.created_at.desc())
            .limit(limit)
        )
        
        result = await self.session.execute(stmt)
        models = result.scalars().all()
        
        return [self._to_entity(m) for m in models]
    
    async def list_by_campaign(
        self,
        campaign_id: UUID,
        limit: int = 100,
    ) -> list[Account]:
        """List accounts assigned to a campaign."""
        stmt = (
            select(AccountModel)
            .where(AccountModel.campaign_id == campaign_id)
            .order_by(AccountModel.created_at.desc())
            .limit(limit)
        )
        
        result = await self.session.execute(stmt)
        models = result.scalars().all()
        
        return [self._to_entity(m) for m in models]
    
    async def list_active(self) -> list[Account]:
        """List all active accounts."""
        return await self.list_by_status(AccountStatus.ACTIVE)
    
    async def count_by_status(self, status: AccountStatus) -> int:
        """Count accounts by status."""
        stmt = (
            select(func.count())
            .select_from(AccountModel)
            .where(AccountModel.status == status)
        )
        
        result = await self.session.execute(stmt)
        return result.scalar_one()
    
    async def count_all_by_status(self) -> dict[str, int]:
        """Get count by status for all accounts."""
        stmt = (
            select(
                AccountModel.status,
                func.count().label("count"),
            )
            .group_by(AccountModel.status)
        )
        
        result = await self.session.execute(stmt)
        rows = result.all()
        
        counts = {status.value: 0 for status in AccountStatus}
        for row in rows:
            # row.status is already a string from SQLAlchemy, not an enum
            status_key = row.status if isinstance(row.status, str) else row.status.value
            if status_key in counts:
                counts[status_key] = row.count
        
        return counts
    
    async def reset_hourly_counters(self) -> int:
        """
        Reset hourly message counters for all accounts.

        Returns:
            Number of accounts updated
        """
        from sqlalchemy import or_

        stmt = (
            update(AccountModel)
            .where(
                or_(
                    AccountModel.hourly_messages_count > 0,
                    AccountModel.hourly_responses_count > 0,
                )
            )
            .values(
                hourly_messages_count=0,
                hourly_responses_count=0,
                last_hourly_reset=datetime.utcnow(),
            )
        )

        result = await self.session.execute(stmt)
        return result.rowcount
    
    async def reset_daily_counters(self, current_hour: Optional[int] = None) -> int:
        """
        Reset daily conversation counters for accounts whose reset hour has come.

        Each account has its own randomized daily_reset_hour (0-23) to avoid
        synchronized reset spikes that could be detected by Telegram.

        Args:
            current_hour: Current UTC hour (0-23). If None, uses current time.

        Returns:
            Number of accounts updated
        """
        from sqlalchemy import or_, extract
        from sqlalchemy.sql import func as sql_func

        if current_hour is None:
            current_hour = datetime.utcnow().hour

        # Reset accounts where:
        # 1. Their daily_reset_hour matches current hour
        # 2. They have conversations to reset OR haven't been reset today
        # 3. last_daily_reset was not in the current hour (prevent double reset)
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        stmt = (
            update(AccountModel)
            .where(
                and_(
                    AccountModel.daily_reset_hour == current_hour,
                    or_(
                        AccountModel.daily_conversations_count > 0,
                        AccountModel.last_daily_reset < today_start,
                        AccountModel.last_daily_reset.is_(None),
                    ),
                )
            )
            .values(
                daily_conversations_count=0,
                last_daily_reset=datetime.utcnow(),
            )
        )

        result = await self.session.execute(stmt)
        return result.rowcount

    async def initialize_daily_reset_hours(self) -> int:
        """
        Initialize random daily_reset_hour for accounts that don't have one set.

        Uses account ID hash to generate deterministic but distributed hours.
        Should be called once on startup or migration.

        Returns:
            Number of accounts updated
        """
        # Get accounts with default reset hour (0)
        stmt = select(AccountModel).where(AccountModel.daily_reset_hour == 0)
        result = await self.session.execute(stmt)
        accounts = result.scalars().all()

        import hashlib

        updated = 0
        for account in accounts:
            # Generate deterministic hour based on account ID
            account_hash = hashlib.md5(str(account.id).encode()).hexdigest()
            reset_hour = int(account_hash[:2], 16) % 24  # 0-23
            account.daily_reset_hour = reset_hour
            updated += 1

        return updated
    
    async def increment_message_count(self, account_id: UUID) -> None:
        """Increment hourly message count for an account (cold outreach)."""
        stmt = (
            update(AccountModel)
            .where(AccountModel.id == account_id)
            .values(
                hourly_messages_count=AccountModel.hourly_messages_count + 1,
                total_messages_sent=AccountModel.total_messages_sent + 1,
                last_activity=datetime.utcnow(),
            )
        )

        await self.session.execute(stmt)

    async def increment_response_count(self, account_id: UUID) -> None:
        """Increment hourly response count for an account (responses to incoming)."""
        stmt = (
            update(AccountModel)
            .where(AccountModel.id == account_id)
            .values(
                hourly_responses_count=AccountModel.hourly_responses_count + 1,
                total_messages_sent=AccountModel.total_messages_sent + 1,
                last_activity=datetime.utcnow(),
            )
        )

        await self.session.execute(stmt)
    
    async def increment_conversation_count(self, account_id: UUID) -> None:
        """Increment daily conversation count for an account."""
        stmt = (
            update(AccountModel)
            .where(AccountModel.id == account_id)
            .values(
                daily_conversations_count=AccountModel.daily_conversations_count + 1,
                hourly_messages_count=AccountModel.hourly_messages_count + 1,
                total_conversations_started=AccountModel.total_conversations_started + 1,
                total_messages_sent=AccountModel.total_messages_sent + 1,
                last_activity=datetime.utcnow(),
            )
        )
        
        await self.session.execute(stmt)
    
    async def update_status(
        self,
        account_id: UUID,
        status: AccountStatus,
        error_message: Optional[str] = None,
    ) -> bool:
        """
        Update account status.
        
        Args:
            account_id: Account UUID
            status: New status
            error_message: Optional error message
            
        Returns:
            True if updated
        """
        values = {
            "status": status,
            "updated_at": datetime.utcnow(),
        }
        
        if error_message is not None:
            values["error_message"] = error_message
        elif status == AccountStatus.ACTIVE:
            values["error_message"] = None
        
        stmt = (
            update(AccountModel)
            .where(AccountModel.id == account_id)
            .values(**values)
        )
        
        result = await self.session.execute(stmt)
        return result.rowcount > 0
    
    async def update_telegram_info(
        self,
        account_id: UUID,
        telegram_id: int,
        username: Optional[str],
        first_name: str,
        last_name: str,
    ) -> bool:
        """Update Telegram profile info."""
        stmt = (
            update(AccountModel)
            .where(AccountModel.id == account_id)
            .values(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                updated_at=datetime.utcnow(),
            )
        )
        
        result = await self.session.execute(stmt)
        return result.rowcount > 0
    
    async def assign_to_campaign(
        self,
        account_id: UUID,
        campaign_id: Optional[UUID],
    ) -> bool:
        """Assign account to a campaign (or remove assignment)."""
        stmt = (
            update(AccountModel)
            .where(AccountModel.id == account_id)
            .values(
                campaign_id=campaign_id,
                updated_at=datetime.utcnow(),
            )
        )
        
        result = await self.session.execute(stmt)
        return result.rowcount > 0
    
    async def assign_proxy(
        self,
        account_id: UUID,
        proxy_id: Optional[UUID],
    ) -> bool:
        """Assign proxy to an account (or remove assignment)."""
        stmt = (
            update(AccountModel)
            .where(AccountModel.id == account_id)
            .values(
                proxy_id=proxy_id,
                updated_at=datetime.utcnow(),
            )
        )
        
        result = await self.session.execute(stmt)
        return result.rowcount > 0
