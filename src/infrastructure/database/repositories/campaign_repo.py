"""
Campaign repository implementation.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from src.application.interfaces.repository import CampaignRepository
from src.domain.entities import Campaign, CampaignStatus
from src.infrastructure.database.mappers import (
    campaign_entity_to_model,
    campaign_model_to_entity,
)
from src.infrastructure.database.models import CampaignModel

from .base import BaseRepository


class PostgresCampaignRepository(BaseRepository[CampaignModel, Campaign], CampaignRepository):
    """PostgreSQL implementation of CampaignRepository."""
    
    model_class = CampaignModel
    
    def _to_entity(self, model: CampaignModel) -> Campaign:
        return campaign_model_to_entity(model)
    
    def _to_model(self, entity: Campaign, model: Optional[CampaignModel] = None) -> CampaignModel:
        return campaign_entity_to_model(entity, model)
    
    async def get_by_id(self, entity_id: UUID) -> Optional[Campaign]:
        """Get campaign with accounts loaded."""
        stmt = (
            select(CampaignModel)
            .options(selectinload(CampaignModel.accounts))
            .where(CampaignModel.id == entity_id)
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        
        if model is None:
            return None
        
        return self._to_entity(model)
    
    async def get_by_name(self, name: str) -> Optional[Campaign]:
        stmt = (
            select(CampaignModel)
            .options(selectinload(CampaignModel.accounts))
            .where(CampaignModel.name == name)
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        
        if model is None:
            return None
        
        return self._to_entity(model)
    
    async def list_by_status(
        self,
        status: CampaignStatus,
        limit: int = 100,
    ) -> list[Campaign]:
        stmt = (
            select(CampaignModel)
            .options(selectinload(CampaignModel.accounts))
            .where(CampaignModel.status == status)
            .order_by(CampaignModel.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        models = result.scalars().all()
        
        return [self._to_entity(m) for m in models]
    
    async def list_by_owner(
        self,
        owner_telegram_id: int,
        limit: int = 100,
    ) -> list[Campaign]:
        stmt = (
            select(CampaignModel)
            .options(selectinload(CampaignModel.accounts))
            .where(CampaignModel.owner_telegram_id == owner_telegram_id)
            .order_by(CampaignModel.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        models = result.scalars().all()
        
        return [self._to_entity(m) for m in models]
    
    async def list_active(self) -> list[Campaign]:
        return await self.list_by_status(CampaignStatus.ACTIVE)
    
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
        """Update campaign statistics atomically."""
        model = await self.session.get(CampaignModel, campaign_id)
        if model is None:
            return
        
        stats = model.stats or {}
        stats["contacted"] = stats.get("contacted", 0) + contacted
        stats["responded"] = stats.get("responded", 0) + responded
        stats["goals_reached"] = stats.get("goals_reached", 0) + goals_reached
        stats["completed"] = stats.get("completed", 0) + completed
        stats["failed"] = stats.get("failed", 0) + failed
        stats["total_messages_sent"] = stats.get("total_messages_sent", 0) + messages_sent
        stats["total_tokens_used"] = stats.get("total_tokens_used", 0) + tokens_used
        
        model.stats = stats
        await self.session.flush()
