"""
Proxy repository implementation.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy import and_, func, select

from src.application.interfaces.repository import ProxyRepository
from src.domain.entities import Proxy, ProxyStatus
from src.infrastructure.database.mappers import (
    proxy_entity_to_model,
    proxy_model_to_entity,
)
from src.infrastructure.database.models import ProxyModel

from .base import BaseRepository


class PostgresProxyRepository(BaseRepository[ProxyModel, Proxy], ProxyRepository):
    """PostgreSQL implementation of ProxyRepository."""
    
    model_class = ProxyModel
    
    def _to_entity(self, model: ProxyModel) -> Proxy:
        return proxy_model_to_entity(model)
    
    def _to_model(self, entity: Proxy, model: Optional[ProxyModel] = None) -> ProxyModel:
        return proxy_entity_to_model(entity, model)
    
    async def get_by_address(self, host: str, port: int) -> Optional[Proxy]:
        stmt = select(ProxyModel).where(
            and_(
                ProxyModel.host == host,
                ProxyModel.port == port,
            )
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        
        if model is None:
            return None
        
        return self._to_entity(model)
    
    async def list_available(self, limit: int = 100) -> list[Proxy]:
        """List proxies that are available for assignment."""
        from src.infrastructure.database.models import AccountModel
        
        # Subquery to get proxy IDs already assigned to accounts
        assigned_subq = (
            select(AccountModel.proxy_id)
            .where(AccountModel.proxy_id.isnot(None))
            .scalar_subquery()
        )
        
        stmt = (
            select(ProxyModel)
            .where(
                and_(
                    ProxyModel.status.in_([
                        ProxyStatus.ACTIVE,
                        ProxyStatus.SLOW,
                        ProxyStatus.UNKNOWN,
                    ]),
                    ProxyModel.id.notin_(assigned_subq),
                )
            )
            .order_by(ProxyModel.last_check_latency_ms.asc().nullsfirst())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        models = result.scalars().all()
        
        return [self._to_entity(m) for m in models]
    
    async def list_by_status(
        self,
        status: ProxyStatus,
        limit: int = 100,
    ) -> list[Proxy]:
        stmt = (
            select(ProxyModel)
            .where(ProxyModel.status == status)
            .order_by(ProxyModel.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        models = result.scalars().all()
        
        return [self._to_entity(m) for m in models]
    
    async def get_for_account(self, account_id: UUID) -> Optional[Proxy]:
        from src.infrastructure.database.models import AccountModel
        
        stmt = (
            select(ProxyModel)
            .join(AccountModel, AccountModel.proxy_id == ProxyModel.id)
            .where(AccountModel.id == account_id)
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        
        if model is None:
            return None
        
        return self._to_entity(model)
    
    async def bulk_create(self, proxies: list[Proxy]) -> int:
        models = [self._to_model(p) for p in proxies]
        self.session.add_all(models)
        await self.session.flush()
        return len(models)
    
    async def count_available(self) -> int:
        from src.infrastructure.database.models import AccountModel

        assigned_subq = (
            select(AccountModel.proxy_id)
            .where(AccountModel.proxy_id.isnot(None))
            .scalar_subquery()
        )

        stmt = select(func.count(ProxyModel.id)).where(
            and_(
                ProxyModel.status.in_([
                    ProxyStatus.ACTIVE,
                    ProxyStatus.SLOW,
                    ProxyStatus.UNKNOWN,
                ]),
                ProxyModel.id.notin_(assigned_subq),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def is_assigned(self, proxy_id: UUID) -> bool:
        """Check if proxy is already assigned to an account."""
        from src.infrastructure.database.models import AccountModel

        stmt = select(func.count(AccountModel.id)).where(
            AccountModel.proxy_id == proxy_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one() > 0

    async def get_assigned_account_id(self, proxy_id: UUID) -> Optional[UUID]:
        """Get the account ID that this proxy is assigned to."""
        from src.infrastructure.database.models import AccountModel

        stmt = select(AccountModel.id).where(
            AccountModel.proxy_id == proxy_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all_with_assignment(self, limit: int = 500) -> list[tuple[Proxy, Optional[UUID]]]:
        """List all proxies with their assigned account ID (if any)."""
        from src.infrastructure.database.models import AccountModel
        from sqlalchemy.orm import aliased

        stmt = (
            select(ProxyModel, AccountModel.id.label("account_id"))
            .outerjoin(AccountModel, AccountModel.proxy_id == ProxyModel.id)
            .order_by(ProxyModel.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        rows = result.all()

        return [(self._to_entity(row.ProxyModel), row.account_id) for row in rows]
