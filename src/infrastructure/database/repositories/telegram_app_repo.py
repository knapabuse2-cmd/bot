"""
TelegramApp repository implementation.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy import and_, func, select, update

from src.domain.entities import TelegramApp
from src.infrastructure.database.mappers import (
    telegram_app_entity_to_model,
    telegram_app_model_to_entity,
)
from src.infrastructure.database.models import TelegramAppModel, AccountModel

from .base import BaseRepository


class PostgresTelegramAppRepository(BaseRepository[TelegramAppModel, TelegramApp]):
    """PostgreSQL implementation of TelegramAppRepository."""

    model_class = TelegramAppModel

    def _to_entity(self, model: TelegramAppModel) -> TelegramApp:
        return telegram_app_model_to_entity(model)

    def _to_model(self, entity: TelegramApp, model: Optional[TelegramAppModel] = None) -> TelegramAppModel:
        return telegram_app_entity_to_model(entity, model)

    async def get_by_api_id(self, api_id: int) -> Optional[TelegramApp]:
        """Get TelegramApp by API ID."""
        stmt = select(TelegramAppModel).where(TelegramAppModel.api_id == api_id)
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()

        if model is None:
            return None

        return self._to_entity(model)

    async def list_active(self, limit: int = 100) -> list[TelegramApp]:
        """List all active TelegramApps."""
        stmt = (
            select(TelegramAppModel)
            .where(TelegramAppModel.is_active == True)
            .order_by(TelegramAppModel.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        models = result.scalars().all()

        return [self._to_entity(m) for m in models]

    async def list_available(self, limit: int = 100) -> list[TelegramApp]:
        """List TelegramApps that can accept more accounts."""
        stmt = (
            select(TelegramAppModel)
            .where(
                and_(
                    TelegramAppModel.is_active == True,
                    TelegramAppModel.current_account_count < TelegramAppModel.max_accounts,
                )
            )
            .order_by(TelegramAppModel.current_account_count.asc())  # Least loaded first
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        models = result.scalars().all()

        return [self._to_entity(m) for m in models]

    async def get_least_loaded(self) -> Optional[TelegramApp]:
        """Get the TelegramApp with the least accounts that can accept more."""
        stmt = (
            select(TelegramAppModel)
            .where(
                and_(
                    TelegramAppModel.is_active == True,
                    TelegramAppModel.current_account_count < TelegramAppModel.max_accounts,
                )
            )
            .order_by(TelegramAppModel.current_account_count.asc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()

        if model is None:
            return None

        return self._to_entity(model)

    async def increment_account_count(self, app_id: UUID) -> None:
        """Increment account count for a TelegramApp."""
        stmt = (
            update(TelegramAppModel)
            .where(TelegramAppModel.id == app_id)
            .values(current_account_count=TelegramAppModel.current_account_count + 1)
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def decrement_account_count(self, app_id: UUID) -> None:
        """Decrement account count for a TelegramApp."""
        stmt = (
            update(TelegramAppModel)
            .where(
                and_(
                    TelegramAppModel.id == app_id,
                    TelegramAppModel.current_account_count > 0,
                )
            )
            .values(current_account_count=TelegramAppModel.current_account_count - 1)
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def recalculate_account_count(self, app_id: UUID) -> int:
        """Recalculate and update account count from actual accounts."""
        count_stmt = select(func.count(AccountModel.id)).where(
            AccountModel.telegram_app_id == app_id
        )
        result = await self.session.execute(count_stmt)
        actual_count = result.scalar_one()

        update_stmt = (
            update(TelegramAppModel)
            .where(TelegramAppModel.id == app_id)
            .values(current_account_count=actual_count)
        )
        await self.session.execute(update_stmt)
        await self.session.flush()

        return actual_count

    async def recalculate_all_counts(self) -> dict[UUID, int]:
        """Recalculate account counts for all TelegramApps."""
        # Get all apps
        apps_stmt = select(TelegramAppModel)
        result = await self.session.execute(apps_stmt)
        apps = result.scalars().all()

        counts = {}
        for app in apps:
            counts[app.id] = await self.recalculate_account_count(app.id)

        return counts

    async def get_for_account(self, account_id: UUID) -> Optional[TelegramApp]:
        """Get TelegramApp assigned to an account."""
        stmt = (
            select(TelegramAppModel)
            .join(AccountModel, AccountModel.telegram_app_id == TelegramAppModel.id)
            .where(AccountModel.id == account_id)
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()

        if model is None:
            return None

        return self._to_entity(model)

    async def count_total(self) -> int:
        """Get total number of TelegramApps."""
        stmt = select(func.count(TelegramAppModel.id))
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def count_active(self) -> int:
        """Get number of active TelegramApps."""
        stmt = select(func.count(TelegramAppModel.id)).where(
            TelegramAppModel.is_active == True
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def get_total_capacity(self) -> int:
        """Get total account capacity across all active apps."""
        stmt = select(func.sum(TelegramAppModel.max_accounts)).where(
            TelegramAppModel.is_active == True
        )
        result = await self.session.execute(stmt)
        return result.scalar_one() or 0

    async def get_total_used(self) -> int:
        """Get total accounts assigned across all apps."""
        stmt = select(func.sum(TelegramAppModel.current_account_count)).where(
            TelegramAppModel.is_active == True
        )
        result = await self.session.execute(stmt)
        return result.scalar_one() or 0

    async def get_available_capacity(self) -> int:
        """Get remaining account capacity."""
        total = await self.get_total_capacity()
        used = await self.get_total_used()
        return total - used
