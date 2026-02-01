"""
Warmup system repositories.

PostgreSQL implementations for warmup-related entities.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update, delete, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.domain.entities import (
    WarmupProfile,
    AccountWarmup,
    AccountPersona,
    InterestCategory,
    WarmupChannel,
    WarmupGroup,
    AccountGroup,
    ProxyGroup,
    WarmupActivityLog,
    WarmupStatus,
)

from ..models import (
    WarmupProfileModel,
    AccountWarmupModel,
    AccountPersonaModel,
    InterestCategoryModel,
    WarmupChannelModel,
    WarmupGroupModel,
    AccountGroupModel,
    ProxyGroupModel,
    WarmupActivityLogModel,
    AccountGroupMembershipModel,
    ProxyGroupMembershipModel,
    AccountSubscriptionModel,
    AccountModel,
)

from ..mappers import (
    warmup_profile_model_to_entity,
    warmup_profile_entity_to_model,
    account_warmup_model_to_entity,
    account_warmup_entity_to_model,
    account_persona_model_to_entity,
    account_persona_entity_to_model,
    interest_category_model_to_entity,
    interest_category_entity_to_model,
    warmup_channel_model_to_entity,
    warmup_channel_entity_to_model,
    warmup_group_model_to_entity,
    warmup_group_entity_to_model,
    account_group_model_to_entity,
    account_group_entity_to_model,
    proxy_group_model_to_entity,
    proxy_group_entity_to_model,
    warmup_activity_log_model_to_entity,
    warmup_activity_log_entity_to_model,
)


class WarmupProfileRepository:
    """Repository for warmup profiles."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, profile_id: UUID) -> Optional[WarmupProfile]:
        """Get profile by ID."""
        result = await self.session.execute(
            select(WarmupProfileModel).where(WarmupProfileModel.id == profile_id)
        )
        model = result.scalar_one_or_none()
        return warmup_profile_model_to_entity(model) if model else None

    async def get_default(self) -> Optional[WarmupProfile]:
        """Get default warmup profile."""
        result = await self.session.execute(
            select(WarmupProfileModel).where(WarmupProfileModel.is_default == True)
        )
        model = result.scalar_one_or_none()
        return warmup_profile_model_to_entity(model) if model else None

    async def get_all(self) -> list[WarmupProfile]:
        """Get all profiles."""
        result = await self.session.execute(select(WarmupProfileModel))
        models = result.scalars().all()
        return [warmup_profile_model_to_entity(m) for m in models]

    async def save(self, entity: WarmupProfile) -> WarmupProfile:
        """Save profile."""
        model = warmup_profile_entity_to_model(entity)
        merged = await self.session.merge(model)
        await self.session.flush()
        return warmup_profile_model_to_entity(merged)

    async def delete(self, profile_id: UUID) -> bool:
        """Delete profile."""
        result = await self.session.execute(
            delete(WarmupProfileModel).where(WarmupProfileModel.id == profile_id)
        )
        return result.rowcount > 0


class AccountWarmupRepository:
    """Repository for account warmup progress."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, warmup_id: UUID) -> Optional[AccountWarmup]:
        """Get warmup by ID."""
        result = await self.session.execute(
            select(AccountWarmupModel).where(AccountWarmupModel.id == warmup_id)
        )
        model = result.scalar_one_or_none()
        return account_warmup_model_to_entity(model) if model else None

    async def get_by_account_id(self, account_id: UUID) -> Optional[AccountWarmup]:
        """Get warmup by account ID."""
        result = await self.session.execute(
            select(AccountWarmupModel).where(AccountWarmupModel.account_id == account_id)
        )
        model = result.scalar_one_or_none()
        return account_warmup_model_to_entity(model) if model else None

    async def get_active_warmups(self) -> list[AccountWarmup]:
        """Get all active warmups."""
        result = await self.session.execute(
            select(AccountWarmupModel).where(AccountWarmupModel.status == WarmupStatus.ACTIVE.value)
        )
        models = result.scalars().all()
        return [account_warmup_model_to_entity(m) for m in models]

    async def get_warmups_by_status(self, status: WarmupStatus) -> list[AccountWarmup]:
        """Get warmups by status."""
        result = await self.session.execute(
            select(AccountWarmupModel).where(AccountWarmupModel.status == status.value)
        )
        models = result.scalars().all()
        return [account_warmup_model_to_entity(m) for m in models]

    async def save(self, entity: AccountWarmup) -> AccountWarmup:
        """Save warmup."""
        model = account_warmup_entity_to_model(entity)
        merged = await self.session.merge(model)
        await self.session.flush()
        return account_warmup_model_to_entity(merged)

    async def delete(self, warmup_id: UUID) -> bool:
        """Delete warmup."""
        result = await self.session.execute(
            delete(AccountWarmupModel).where(AccountWarmupModel.id == warmup_id)
        )
        return result.rowcount > 0

    async def reset_daily_counters(self, current_hour: Optional[int] = None) -> int:
        """Reset daily counters for active warmups whose reset hour has come.

        Each warmup has a randomized daily_reset_hour (0-23) to avoid all warmups
        resetting at the same time (which could be detected by Telegram).

        Args:
            current_hour: Current UTC hour (0-23). If None, uses current time.

        Returns:
            Number of warmups updated
        """
        from sqlalchemy import and_, or_

        if current_hour is None:
            current_hour = datetime.utcnow().hour

        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        result = await self.session.execute(
            update(AccountWarmupModel)
            .where(
                and_(
                    AccountWarmupModel.status == WarmupStatus.ACTIVE.value,
                    AccountWarmupModel.daily_reset_hour == current_hour,
                    or_(
                        AccountWarmupModel.daily_reactions > 0,
                        AccountWarmupModel.daily_messages > 0,
                        AccountWarmupModel.daily_joins > 0,
                        AccountWarmupModel.last_daily_reset < today_start,
                        AccountWarmupModel.last_daily_reset.is_(None),
                    ),
                )
            )
            .values(
                daily_reactions=0,
                daily_messages=0,
                daily_joins=0,
                last_daily_reset=datetime.utcnow(),
            )
        )
        return result.rowcount

    async def initialize_daily_reset_hours(self) -> int:
        """Initialize random daily_reset_hour for warmups that don't have one set.

        Uses account ID hash to generate deterministic but distributed hours.

        Returns:
            Number of warmups updated
        """
        from sqlalchemy import select

        # Get warmups with default reset hour (0)
        stmt = select(AccountWarmupModel).where(AccountWarmupModel.daily_reset_hour == 0)
        result = await self.session.execute(stmt)
        warmups = result.scalars().all()

        import hashlib

        updated = 0
        for warmup in warmups:
            # Generate deterministic hour based on account ID
            account_hash = hashlib.md5(str(warmup.account_id).encode()).hexdigest()
            reset_hour = int(account_hash[:2], 16) % 24  # 0-23
            warmup.daily_reset_hour = reset_hour
            updated += 1

        return updated

    async def start_warmup_for_accounts(
        self, account_ids: list[UUID], profile_id: Optional[UUID] = None
    ) -> int:
        """Start warmup for multiple accounts at once."""
        count = 0
        for account_id in account_ids:
            # Check if warmup already exists
            existing = await self.get_by_account_id(account_id)
            if existing:
                # Update existing
                existing.status = WarmupStatus.ACTIVE
                existing.started_at = datetime.utcnow()
                existing.stage = 1
                existing.profile_id = profile_id
                await self.save(existing)
            else:
                # Create new
                warmup = AccountWarmup(
                    id=UUID(int=0),  # Will be generated
                    account_id=account_id,
                    profile_id=profile_id,
                    status=WarmupStatus.ACTIVE,
                    stage=1,
                    started_at=datetime.utcnow(),
                    stage_started_at=datetime.utcnow(),
                )
                warmup.id = UUID(bytes=__import__('os').urandom(16))
                await self.save(warmup)
            count += 1
        return count


class AccountPersonaRepository:
    """Repository for account personas."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_account_id(self, account_id: UUID) -> Optional[AccountPersona]:
        """Get persona by account ID."""
        result = await self.session.execute(
            select(AccountPersonaModel).where(AccountPersonaModel.account_id == account_id)
        )
        model = result.scalar_one_or_none()
        return account_persona_model_to_entity(model) if model else None

    async def save(self, entity: AccountPersona) -> AccountPersona:
        """Save persona."""
        model = account_persona_entity_to_model(entity)
        merged = await self.session.merge(model)
        await self.session.flush()
        return account_persona_model_to_entity(merged)

    async def delete(self, account_id: UUID) -> bool:
        """Delete persona by account ID."""
        result = await self.session.execute(
            delete(AccountPersonaModel).where(AccountPersonaModel.account_id == account_id)
        )
        return result.rowcount > 0


class InterestCategoryRepository:
    """Repository for interest categories."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, category_id: UUID) -> Optional[InterestCategory]:
        """Get category by ID."""
        result = await self.session.execute(
            select(InterestCategoryModel).where(InterestCategoryModel.id == category_id)
        )
        model = result.scalar_one_or_none()
        return interest_category_model_to_entity(model) if model else None

    async def get_by_name(self, name: str) -> Optional[InterestCategory]:
        """Get category by name."""
        result = await self.session.execute(
            select(InterestCategoryModel).where(InterestCategoryModel.name == name)
        )
        model = result.scalar_one_or_none()
        return interest_category_model_to_entity(model) if model else None

    async def get_all(self) -> list[InterestCategory]:
        """Get all categories."""
        result = await self.session.execute(select(InterestCategoryModel))
        models = result.scalars().all()
        return [interest_category_model_to_entity(m) for m in models]

    async def save(self, entity: InterestCategory) -> InterestCategory:
        """Save category."""
        model = interest_category_entity_to_model(entity)
        merged = await self.session.merge(model)
        await self.session.flush()
        return interest_category_model_to_entity(merged)

    async def delete(self, category_id: UUID) -> bool:
        """Delete category."""
        result = await self.session.execute(
            delete(InterestCategoryModel).where(InterestCategoryModel.id == category_id)
        )
        return result.rowcount > 0


class WarmupChannelRepository:
    """Repository for warmup channels."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, channel_id: UUID) -> Optional[WarmupChannel]:
        """Get channel by ID."""
        result = await self.session.execute(
            select(WarmupChannelModel).where(WarmupChannelModel.id == channel_id)
        )
        model = result.scalar_one_or_none()
        return warmup_channel_model_to_entity(model) if model else None

    async def get_by_username(self, username: str) -> Optional[WarmupChannel]:
        """Get channel by username."""
        result = await self.session.execute(
            select(WarmupChannelModel).where(WarmupChannelModel.username == username)
        )
        model = result.scalar_one_or_none()
        return warmup_channel_model_to_entity(model) if model else None

    async def get_active(self, limit: int = 100) -> list[WarmupChannel]:
        """Get active channels."""
        result = await self.session.execute(
            select(WarmupChannelModel)
            .where(WarmupChannelModel.is_active == True)
            .limit(limit)
        )
        models = result.scalars().all()
        return [warmup_channel_model_to_entity(m) for m in models]

    async def get_by_category(self, category_id: UUID) -> list[WarmupChannel]:
        """Get channels by category."""
        result = await self.session.execute(
            select(WarmupChannelModel)
            .where(
                and_(
                    WarmupChannelModel.category_id == category_id,
                    WarmupChannelModel.is_active == True,
                )
            )
        )
        models = result.scalars().all()
        return [warmup_channel_model_to_entity(m) for m in models]

    async def get_by_language(self, language: str) -> list[WarmupChannel]:
        """Get channels by language."""
        result = await self.session.execute(
            select(WarmupChannelModel)
            .where(
                and_(
                    WarmupChannelModel.language == language,
                    WarmupChannelModel.is_active == True,
                )
            )
        )
        models = result.scalars().all()
        return [warmup_channel_model_to_entity(m) for m in models]

    async def get_random_for_warmup(
        self, language: str, exclude_ids: list[UUID], limit: int = 5
    ) -> list[WarmupChannel]:
        """Get random channels for warmup, excluding already joined."""
        query = (
            select(WarmupChannelModel)
            .where(
                and_(
                    WarmupChannelModel.is_active == True,
                    WarmupChannelModel.language == language,
                    ~WarmupChannelModel.id.in_(exclude_ids) if exclude_ids else True,
                )
            )
            .order_by(func.random())
            .limit(limit)
        )
        result = await self.session.execute(query)
        models = result.scalars().all()
        return [warmup_channel_model_to_entity(m) for m in models]

    async def save(self, entity: WarmupChannel) -> WarmupChannel:
        """Save channel."""
        model = warmup_channel_entity_to_model(entity)
        merged = await self.session.merge(model)
        await self.session.flush()
        return warmup_channel_model_to_entity(merged)

    async def delete(self, channel_id: UUID) -> bool:
        """Delete channel."""
        result = await self.session.execute(
            delete(WarmupChannelModel).where(WarmupChannelModel.id == channel_id)
        )
        return result.rowcount > 0

    async def count(self) -> int:
        """Count all channels."""
        result = await self.session.execute(
            select(func.count()).select_from(WarmupChannelModel)
        )
        return result.scalar() or 0


class WarmupGroupRepository:
    """Repository for warmup groups."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, group_id: UUID) -> Optional[WarmupGroup]:
        """Get group by ID."""
        result = await self.session.execute(
            select(WarmupGroupModel).where(WarmupGroupModel.id == group_id)
        )
        model = result.scalar_one_or_none()
        return warmup_group_model_to_entity(model) if model else None

    async def get_by_username(self, username: str) -> Optional[WarmupGroup]:
        """Get group by username."""
        result = await self.session.execute(
            select(WarmupGroupModel).where(WarmupGroupModel.username == username)
        )
        model = result.scalar_one_or_none()
        return warmup_group_model_to_entity(model) if model else None

    async def get_active(self, limit: int = 100) -> list[WarmupGroup]:
        """Get active groups."""
        result = await self.session.execute(
            select(WarmupGroupModel)
            .where(WarmupGroupModel.is_active == True)
            .limit(limit)
        )
        models = result.scalars().all()
        return [warmup_group_model_to_entity(m) for m in models]

    async def get_writable(self) -> list[WarmupGroup]:
        """Get groups where accounts can write."""
        result = await self.session.execute(
            select(WarmupGroupModel)
            .where(
                and_(
                    WarmupGroupModel.is_active == True,
                    WarmupGroupModel.can_write == True,
                )
            )
        )
        models = result.scalars().all()
        return [warmup_group_model_to_entity(m) for m in models]

    async def get_random_for_warmup(
        self, language: str, exclude_ids: list[UUID], limit: int = 3
    ) -> list[WarmupGroup]:
        """Get random groups for warmup."""
        query = (
            select(WarmupGroupModel)
            .where(
                and_(
                    WarmupGroupModel.is_active == True,
                    WarmupGroupModel.language == language,
                    ~WarmupGroupModel.id.in_(exclude_ids) if exclude_ids else True,
                )
            )
            .order_by(func.random())
            .limit(limit)
        )
        result = await self.session.execute(query)
        models = result.scalars().all()
        return [warmup_group_model_to_entity(m) for m in models]

    async def save(self, entity: WarmupGroup) -> WarmupGroup:
        """Save group."""
        model = warmup_group_entity_to_model(entity)
        merged = await self.session.merge(model)
        await self.session.flush()
        return warmup_group_model_to_entity(merged)

    async def delete(self, group_id: UUID) -> bool:
        """Delete group."""
        result = await self.session.execute(
            delete(WarmupGroupModel).where(WarmupGroupModel.id == group_id)
        )
        return result.rowcount > 0

    async def count(self) -> int:
        """Count all groups."""
        result = await self.session.execute(
            select(func.count()).select_from(WarmupGroupModel)
        )
        return result.scalar() or 0


class AccountGroupRepository:
    """Repository for account groups."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, group_id: UUID) -> Optional[AccountGroup]:
        """Get group by ID with accounts loaded."""
        from sqlalchemy.orm import selectinload

        result = await self.session.execute(
            select(AccountGroupModel)
            .where(AccountGroupModel.id == group_id)
            .options(selectinload(AccountGroupModel.direct_accounts))
        )
        model = result.scalar_one_or_none()
        return account_group_model_to_entity(model) if model else None

    async def get_by_name(self, name: str) -> Optional[AccountGroup]:
        """Get group by name."""
        from sqlalchemy.orm import selectinload

        result = await self.session.execute(
            select(AccountGroupModel)
            .where(AccountGroupModel.name == name)
            .options(selectinload(AccountGroupModel.direct_accounts))
        )
        model = result.scalar_one_or_none()
        return account_group_model_to_entity(model) if model else None

    async def get_all(self) -> list[AccountGroup]:
        """Get all groups with account counts."""
        from sqlalchemy.orm import selectinload

        result = await self.session.execute(
            select(AccountGroupModel)
            .options(selectinload(AccountGroupModel.direct_accounts))
            .order_by(AccountGroupModel.name)
        )
        models = result.scalars().all()
        return [account_group_model_to_entity(m) for m in models]

    async def save(self, entity: AccountGroup) -> AccountGroup:
        """Save group."""
        from sqlalchemy.orm import selectinload

        model = account_group_entity_to_model(entity)
        merged = await self.session.merge(model)
        await self.session.flush()

        # Reload with relationships to avoid lazy load issues
        result = await self.session.execute(
            select(AccountGroupModel)
            .where(AccountGroupModel.id == merged.id)
            .options(selectinload(AccountGroupModel.direct_accounts))
        )
        reloaded = result.scalar_one()
        return account_group_model_to_entity(reloaded)

    async def delete(self, group_id: UUID) -> bool:
        """Delete group (accounts will have group_id set to NULL)."""
        result = await self.session.execute(
            delete(AccountGroupModel).where(AccountGroupModel.id == group_id)
        )
        return result.rowcount > 0

    async def add_account(self, group_id: UUID, account_id: UUID) -> bool:
        """Add account to group by setting account.group_id."""
        from sqlalchemy import update

        result = await self.session.execute(
            update(AccountModel)
            .where(AccountModel.id == account_id)
            .values(group_id=group_id)
        )
        return result.rowcount > 0

    async def remove_account(self, group_id: UUID, account_id: UUID) -> bool:
        """Remove account from group by clearing account.group_id."""
        from sqlalchemy import update

        result = await self.session.execute(
            update(AccountModel)
            .where(
                and_(
                    AccountModel.id == account_id,
                    AccountModel.group_id == group_id,
                )
            )
            .values(group_id=None)
        )
        return result.rowcount > 0

    async def get_account_ids(self, group_id: UUID) -> list[UUID]:
        """Get all account IDs in a group."""
        result = await self.session.execute(
            select(AccountModel.id).where(AccountModel.group_id == group_id)
        )
        return list(result.scalars().all())

    async def get_accounts_without_group(self) -> list[tuple[UUID, str, Optional[str]]]:
        """Get accounts not assigned to any group.

        Returns list of (id, phone, username) tuples.
        """
        result = await self.session.execute(
            select(AccountModel.id, AccountModel.phone, AccountModel.username)
            .where(AccountModel.group_id.is_(None))
            .order_by(AccountModel.phone)
        )
        return list(result.all())

    async def add_accounts_batch(self, group_id: UUID, account_ids: list[UUID]) -> int:
        """Add multiple accounts to group."""
        count = 0
        for account_id in account_ids:
            if await self.add_account(group_id, account_id):
                count += 1
        return count


class ProxyGroupRepository:
    """Repository for proxy groups."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, group_id: UUID) -> Optional[ProxyGroup]:
        """Get group by ID."""
        result = await self.session.execute(
            select(ProxyGroupModel).where(ProxyGroupModel.id == group_id)
        )
        model = result.scalar_one_or_none()
        return proxy_group_model_to_entity(model) if model else None

    async def get_by_name(self, name: str) -> Optional[ProxyGroup]:
        """Get group by name."""
        result = await self.session.execute(
            select(ProxyGroupModel).where(ProxyGroupModel.name == name)
        )
        model = result.scalar_one_or_none()
        return proxy_group_model_to_entity(model) if model else None

    async def get_by_country(self, country_code: str) -> list[ProxyGroup]:
        """Get groups by country code."""
        result = await self.session.execute(
            select(ProxyGroupModel).where(ProxyGroupModel.country_code == country_code)
        )
        models = result.scalars().all()
        return [proxy_group_model_to_entity(m) for m in models]

    async def get_all(self) -> list[ProxyGroup]:
        """Get all groups."""
        result = await self.session.execute(select(ProxyGroupModel))
        models = result.scalars().all()
        return [proxy_group_model_to_entity(m) for m in models]

    async def save(self, entity: ProxyGroup) -> ProxyGroup:
        """Save group."""
        model = proxy_group_entity_to_model(entity)
        merged = await self.session.merge(model)
        await self.session.flush()
        return proxy_group_model_to_entity(merged)

    async def delete(self, group_id: UUID) -> bool:
        """Delete group."""
        result = await self.session.execute(
            delete(ProxyGroupModel).where(ProxyGroupModel.id == group_id)
        )
        return result.rowcount > 0

    async def add_proxy(self, group_id: UUID, proxy_id: UUID) -> bool:
        """Add proxy to group."""
        membership = ProxyGroupMembershipModel(
            id=UUID(bytes=__import__('os').urandom(16)),
            proxy_id=proxy_id,
            group_id=group_id,
        )
        self.session.add(membership)
        try:
            await self.session.flush()
            return True
        except Exception:
            return False

    async def remove_proxy(self, group_id: UUID, proxy_id: UUID) -> bool:
        """Remove proxy from group."""
        result = await self.session.execute(
            delete(ProxyGroupMembershipModel).where(
                and_(
                    ProxyGroupMembershipModel.group_id == group_id,
                    ProxyGroupMembershipModel.proxy_id == proxy_id,
                )
            )
        )
        return result.rowcount > 0

    async def get_proxy_ids(self, group_id: UUID) -> list[UUID]:
        """Get all proxy IDs in a group."""
        result = await self.session.execute(
            select(ProxyGroupMembershipModel.proxy_id).where(
                ProxyGroupMembershipModel.group_id == group_id
            )
        )
        return list(result.scalars().all())

    async def get_available_proxies_in_group(self, group_id: UUID, limit: int = 100) -> list:
        """
        Get available (not assigned to any account) proxies in a group.

        Returns list of Proxy entities that are in the group and not assigned to any account.
        """
        from src.infrastructure.database.models import ProxyModel, AccountModel
        from src.infrastructure.database.mappers import proxy_model_to_entity
        from src.domain.entities import ProxyStatus

        # Subquery to get proxy IDs already assigned to accounts
        assigned_subq = (
            select(AccountModel.proxy_id)
            .where(AccountModel.proxy_id.isnot(None))
            .scalar_subquery()
        )

        # Get proxy IDs in this group
        proxy_ids_in_group = (
            select(ProxyGroupMembershipModel.proxy_id)
            .where(ProxyGroupMembershipModel.group_id == group_id)
            .scalar_subquery()
        )

        stmt = (
            select(ProxyModel)
            .where(
                and_(
                    ProxyModel.id.in_(proxy_ids_in_group),
                    ProxyModel.status.in_([
                        ProxyStatus.ACTIVE.value,
                        ProxyStatus.SLOW.value,
                        ProxyStatus.UNKNOWN.value,
                    ]),
                    ProxyModel.id.notin_(assigned_subq),
                )
            )
            .order_by(ProxyModel.last_check_latency_ms.asc().nullsfirst())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        models = result.scalars().all()

        return [proxy_model_to_entity(m) for m in models]

    async def count_proxies_in_group(self, group_id: UUID) -> int:
        """Count total proxies in a group."""
        result = await self.session.execute(
            select(func.count(ProxyGroupMembershipModel.id)).where(
                ProxyGroupMembershipModel.group_id == group_id
            )
        )
        return result.scalar_one()

    async def count_available_proxies_in_group(self, group_id: UUID) -> int:
        """Count available (not assigned) proxies in a group."""
        from src.infrastructure.database.models import ProxyModel, AccountModel
        from src.domain.entities import ProxyStatus

        # Subquery to get proxy IDs already assigned to accounts
        assigned_subq = (
            select(AccountModel.proxy_id)
            .where(AccountModel.proxy_id.isnot(None))
            .scalar_subquery()
        )

        # Get proxy IDs in this group
        proxy_ids_in_group = (
            select(ProxyGroupMembershipModel.proxy_id)
            .where(ProxyGroupMembershipModel.group_id == group_id)
            .scalar_subquery()
        )

        stmt = select(func.count(ProxyModel.id)).where(
            and_(
                ProxyModel.id.in_(proxy_ids_in_group),
                ProxyModel.status.in_([
                    ProxyStatus.ACTIVE.value,
                    ProxyStatus.SLOW.value,
                    ProxyStatus.UNKNOWN.value,
                ]),
                ProxyModel.id.notin_(assigned_subq),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def get_proxies_in_group(self, group_id: UUID, limit: int = 100) -> list:
        """Get all proxies in a group (both assigned and available)."""
        from src.infrastructure.database.models import ProxyModel
        from src.infrastructure.database.mappers import proxy_model_to_entity

        proxy_ids_in_group = (
            select(ProxyGroupMembershipModel.proxy_id)
            .where(ProxyGroupMembershipModel.group_id == group_id)
            .scalar_subquery()
        )

        stmt = (
            select(ProxyModel)
            .where(ProxyModel.id.in_(proxy_ids_in_group))
            .order_by(ProxyModel.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        models = result.scalars().all()

        return [proxy_model_to_entity(m) for m in models]

    async def bulk_add_proxies(self, group_id: UUID, proxy_ids: list[UUID]) -> int:
        """Add multiple proxies to a group."""
        import os
        count = 0
        for proxy_id in proxy_ids:
            membership = ProxyGroupMembershipModel(
                id=UUID(bytes=os.urandom(16)),
                proxy_id=proxy_id,
                group_id=group_id,
            )
            self.session.add(membership)
            try:
                await self.session.flush()
                count += 1
            except Exception:
                await self.session.rollback()
        return count


class WarmupActivityLogRepository:
    """Repository for warmup activity logs."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def log_activity(
        self,
        account_id: UUID,
        activity_type: str,
        target: Optional[str] = None,
        details: Optional[dict] = None,
        success: bool = True,
        error: Optional[str] = None,
    ) -> WarmupActivityLog:
        """Log a warmup activity."""
        log = WarmupActivityLog(
            id=UUID(bytes=__import__('os').urandom(16)),
            account_id=account_id,
            activity_type=activity_type,
            target=target,
            details=details,
            success=success,
            error=error,
            created_at=datetime.utcnow(),
        )
        model = warmup_activity_log_entity_to_model(log)
        self.session.add(model)
        await self.session.flush()
        return log

    async def get_by_account(
        self, account_id: UUID, limit: int = 100
    ) -> list[WarmupActivityLog]:
        """Get activity logs for an account."""
        result = await self.session.execute(
            select(WarmupActivityLogModel)
            .where(WarmupActivityLogModel.account_id == account_id)
            .order_by(WarmupActivityLogModel.created_at.desc())
            .limit(limit)
        )
        models = result.scalars().all()
        return [warmup_activity_log_model_to_entity(m) for m in models]

    async def get_recent(
        self, hours: int = 24, limit: int = 1000
    ) -> list[WarmupActivityLog]:
        """Get recent activity logs."""
        cutoff = datetime.utcnow() - __import__('datetime').timedelta(hours=hours)
        result = await self.session.execute(
            select(WarmupActivityLogModel)
            .where(WarmupActivityLogModel.created_at >= cutoff)
            .order_by(WarmupActivityLogModel.created_at.desc())
            .limit(limit)
        )
        models = result.scalars().all()
        return [warmup_activity_log_model_to_entity(m) for m in models]

    async def count_by_type(
        self, account_id: UUID, activity_type: str, since: datetime
    ) -> int:
        """Count activities of a specific type since a timestamp."""
        result = await self.session.execute(
            select(func.count())
            .select_from(WarmupActivityLogModel)
            .where(
                and_(
                    WarmupActivityLogModel.account_id == account_id,
                    WarmupActivityLogModel.activity_type == activity_type,
                    WarmupActivityLogModel.created_at >= since,
                    WarmupActivityLogModel.success == True,
                )
            )
        )
        return result.scalar() or 0
