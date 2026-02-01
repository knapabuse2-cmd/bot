"""
UserTarget repository implementation.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, func, select

from src.application.interfaces.repository import UserTargetRepository
from src.domain.entities import TargetStatus, UserTarget
from src.infrastructure.database.mappers import (
    user_target_entity_to_model,
    user_target_model_to_entity,
)
from src.infrastructure.database.models import UserTargetModel

from .base import BaseRepository


class PostgresUserTargetRepository(BaseRepository[UserTargetModel, UserTarget], UserTargetRepository):
    """PostgreSQL implementation of UserTargetRepository."""
    
    model_class = UserTargetModel
    
    def _to_entity(self, model: UserTargetModel) -> UserTarget:
        return user_target_model_to_entity(model)
    
    def _to_model(self, entity: UserTarget, model: Optional[UserTargetModel] = None) -> UserTargetModel:
        return user_target_entity_to_model(entity, model)
    
    async def get_by_telegram_id(
        self,
        campaign_id: UUID,
        telegram_id: int,
    ) -> Optional[UserTarget]:
        stmt = select(UserTargetModel).where(
            and_(
                UserTargetModel.campaign_id == campaign_id,
                UserTargetModel.telegram_id == telegram_id,
            )
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        
        if model is None:
            return None
        
        return self._to_entity(model)
    
    async def get_by_username(
        self,
        campaign_id: UUID,
        username: str,
    ) -> Optional[UserTarget]:
        stmt = select(UserTargetModel).where(
            and_(
                UserTargetModel.campaign_id == campaign_id,
                UserTargetModel.username == username,
            )
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        
        if model is None:
            return None
        
        return self._to_entity(model)
    
    async def list_by_campaign(
        self,
        campaign_id: UUID,
        status: Optional[TargetStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UserTarget]:
        stmt = select(UserTargetModel).where(
            UserTargetModel.campaign_id == campaign_id
        )
        
        if status:
            stmt = stmt.where(UserTargetModel.status == status)
        
        stmt = (
            stmt
            .order_by(UserTargetModel.priority.desc(), UserTargetModel.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        
        result = await self.session.execute(stmt)
        models = result.scalars().all()
        
        return [self._to_entity(m) for m in models]
    
    async def list_pending(
        self,
        campaign_id: UUID,
        limit: int = 100,
    ) -> list[UserTarget]:
        """List pending targets ready to be assigned."""
        stmt = (
            select(UserTargetModel)
            .where(
                and_(
                    UserTargetModel.campaign_id == campaign_id,
                    UserTargetModel.status == TargetStatus.PENDING,
                )
            )
            .order_by(
                UserTargetModel.priority.desc(),
                UserTargetModel.created_at.asc(),
            )
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        models = result.scalars().all()
        
        return [self._to_entity(m) for m in models]
    

    async def list_pending_for_update(
        self,
        campaign_id: UUID,
        limit: int = 100,
    ) -> list[UserTarget]:
        # Pending targets that are not yet assigned.
        stmt = (
            select(UserTargetModel)
            .where(
                and_(
                    UserTargetModel.campaign_id == campaign_id,
                    UserTargetModel.status == TargetStatus.PENDING,
                    UserTargetModel.assigned_account_id.is_(None),
                )
            )
            .order_by(UserTargetModel.priority.desc(), UserTargetModel.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def list_scheduled(
        self,
        account_id: UUID,
        limit: int = 100,
    ) -> list[UserTarget]:
        """List targets scheduled for contact by an account."""
        now = datetime.utcnow()
        
        stmt = (
            select(UserTargetModel)
            .where(
                and_(
                    UserTargetModel.assigned_account_id == account_id,
                    UserTargetModel.status == TargetStatus.ASSIGNED,
                    UserTargetModel.scheduled_contact_at <= now,
                )
            )
            .order_by(UserTargetModel.scheduled_contact_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        models = result.scalars().all()
        
        return [self._to_entity(m) for m in models]
    
    async def bulk_create(self, targets: list[UserTarget]) -> int:
        """Bulk create targets."""
        models = [self._to_model(t) for t in targets]
        self.session.add_all(models)
        await self.session.flush()
        return len(models)
    
    async def count_by_campaign(
        self,
        campaign_id: UUID,
        status: Optional[TargetStatus] = None,
    ) -> int:
        stmt = select(func.count(UserTargetModel.id)).where(
            UserTargetModel.campaign_id == campaign_id
        )

        if status:
            stmt = stmt.where(UserTargetModel.status == status)

        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def get_existing_usernames(
        self,
        usernames: list[str],
        campaign_id: Optional[UUID] = None,
    ) -> set[str]:
        """
        Check which usernames already exist in database.

        Args:
            usernames: List of usernames to check
            campaign_id: If provided, only check within this campaign.
                        If None, check across all campaigns.

        Returns:
            Set of usernames that already exist
        """
        if not usernames:
            return set()

        stmt = select(UserTargetModel.username).where(
            UserTargetModel.username.in_(usernames)
        )

        if campaign_id:
            stmt = stmt.where(UserTargetModel.campaign_id == campaign_id)

        result = await self.session.execute(stmt)
        return {row[0] for row in result.all() if row[0]}

    async def get_all_existing_usernames(self) -> set[str]:
        """
        Get all usernames that exist in database.

        Useful for filtering during scraping to avoid duplicates.

        Returns:
            Set of all existing usernames
        """
        stmt = select(UserTargetModel.username).where(
            UserTargetModel.username.isnot(None)
        )
        result = await self.session.execute(stmt)
        return {row[0] for row in result.all() if row[0]}
