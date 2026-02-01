"""Repositories for comment bot."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.commentbot.domain.entities import (
    Account,
    AccountStatus,
    CommentTask,
    TaskStatus,
    Campaign,
    CampaignStatus,
    Channel,
    ChannelStatus,
    ChannelAssignment,
    AssignmentStatus,
)
from src.commentbot.infrastructure.database.models import (
    AccountModel,
    CommentTaskModel,
    CampaignModel,
    ChannelModel,
    ChannelAssignmentModel,
)


class AccountRepository:
    """Repository for account operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, account: Account) -> Account:
        """Save or update account."""
        model = await self.session.get(AccountModel, account.id)

        if model is None:
            model = AccountModel(
                id=account.id,
                phone=account.phone,
                session_data=account.session_data,
                tdata_path=account.tdata_path,
                status=account.status,
                error_message=account.error_message,
                created_at=account.created_at,
                last_used_at=account.last_used_at,
                comments_today=account.comments_today,
                daily_limit=account.daily_limit,
                owner_id=account.owner_id,
                phone_code_hash=account.phone_code_hash,
            )
            self.session.add(model)
        else:
            model.phone = account.phone
            model.session_data = account.session_data
            model.tdata_path = account.tdata_path
            model.status = account.status
            model.error_message = account.error_message
            model.last_used_at = account.last_used_at
            model.comments_today = account.comments_today
            model.daily_limit = account.daily_limit
            model.phone_code_hash = account.phone_code_hash

        await self.session.flush()
        return account

    async def get_by_id(self, account_id: UUID) -> Optional[Account]:
        """Get account by ID."""
        model = await self.session.get(AccountModel, account_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def get_by_phone(self, phone: str) -> Optional[Account]:
        """Get account by phone number."""
        stmt = select(AccountModel).where(AccountModel.phone == phone)
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_entity(model)

    async def list_by_owner(self, owner_id: int) -> list[Account]:
        """List all accounts for an owner."""
        stmt = (
            select(AccountModel)
            .where(AccountModel.owner_id == owner_id)
            .order_by(AccountModel.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars()]

    async def list_active(self, owner_id: int) -> list[Account]:
        """List active accounts for an owner."""
        stmt = (
            select(AccountModel)
            .where(
                AccountModel.owner_id == owner_id,
                AccountModel.status == AccountStatus.ACTIVE,
            )
            .order_by(AccountModel.last_used_at.desc().nullsfirst())
        )
        result = await self.session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars()]

    async def list_available_for_work(self, owner_id: int) -> list[Account]:
        """List accounts that can work (active and under daily limit)."""
        stmt = (
            select(AccountModel)
            .where(
                AccountModel.owner_id == owner_id,
                AccountModel.status == AccountStatus.ACTIVE,
                AccountModel.comments_today < AccountModel.daily_limit,
            )
            .order_by(AccountModel.comments_today.asc())  # Least used first
        )
        result = await self.session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars()]

    async def delete(self, account_id: UUID) -> bool:
        """Delete account."""
        model = await self.session.get(AccountModel, account_id)
        if model is None:
            return False
        await self.session.delete(model)
        return True

    async def reset_daily_counters(self) -> int:
        """Reset daily comment counters for all accounts."""
        stmt = (
            update(AccountModel)
            .where(AccountModel.comments_today > 0)
            .values(comments_today=0)
        )
        result = await self.session.execute(stmt)
        return result.rowcount

    def _to_entity(self, model: AccountModel) -> Account:
        """Convert model to entity."""
        return Account(
            id=model.id,
            phone=model.phone,
            session_data=model.session_data,
            tdata_path=model.tdata_path,
            status=model.status,
            error_message=model.error_message,
            created_at=model.created_at,
            last_used_at=model.last_used_at,
            comments_today=model.comments_today,
            daily_limit=model.daily_limit,
            owner_id=model.owner_id,
            phone_code_hash=model.phone_code_hash,
        )


class CampaignRepository:
    """Repository for campaign operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, campaign: Campaign) -> Campaign:
        """Save or update campaign."""
        model = await self.session.get(CampaignModel, campaign.id)

        if model is None:
            model = CampaignModel(
                id=campaign.id,
                name=campaign.name,
                status=campaign.status,
                comment_templates=campaign.comment_templates,
                initial_message=campaign.initial_message,
                min_delay=campaign.min_delay,
                max_delay=campaign.max_delay,
                comments_per_post=campaign.comments_per_post,
                created_at=campaign.created_at,
                updated_at=campaign.updated_at,
                owner_id=campaign.owner_id,
                total_comments=campaign.total_comments,
                successful_comments=campaign.successful_comments,
                failed_comments=campaign.failed_comments,
            )
            self.session.add(model)
        else:
            model.name = campaign.name
            model.status = campaign.status
            model.comment_templates = campaign.comment_templates
            model.initial_message = campaign.initial_message
            model.min_delay = campaign.min_delay
            model.max_delay = campaign.max_delay
            model.comments_per_post = campaign.comments_per_post
            model.updated_at = campaign.updated_at
            model.total_comments = campaign.total_comments
            model.successful_comments = campaign.successful_comments
            model.failed_comments = campaign.failed_comments

        await self.session.flush()
        return campaign

    async def get_by_id(self, campaign_id: UUID) -> Optional[Campaign]:
        """Get campaign by ID."""
        model = await self.session.get(CampaignModel, campaign_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def list_by_owner(self, owner_id: int) -> list[Campaign]:
        """List all campaigns for an owner."""
        stmt = (
            select(CampaignModel)
            .where(CampaignModel.owner_id == owner_id)
            .order_by(CampaignModel.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars()]

    async def list_active(self, owner_id: int) -> list[Campaign]:
        """List active campaigns for an owner."""
        stmt = (
            select(CampaignModel)
            .where(
                CampaignModel.owner_id == owner_id,
                CampaignModel.status == CampaignStatus.ACTIVE,
            )
        )
        result = await self.session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars()]

    async def delete(self, campaign_id: UUID) -> bool:
        """Delete campaign (cascades to channels and assignments)."""
        model = await self.session.get(CampaignModel, campaign_id)
        if model is None:
            return False
        await self.session.delete(model)
        return True

    def _to_entity(self, model: CampaignModel) -> Campaign:
        """Convert model to entity."""
        return Campaign(
            id=model.id,
            name=model.name,
            status=model.status,
            comment_templates=model.comment_templates or [],
            initial_message=model.initial_message,
            min_delay=model.min_delay,
            max_delay=model.max_delay,
            comments_per_post=model.comments_per_post,
            created_at=model.created_at,
            updated_at=model.updated_at,
            owner_id=model.owner_id,
            total_comments=model.total_comments,
            successful_comments=model.successful_comments,
            failed_comments=model.failed_comments,
        )


class ChannelRepository:
    """Repository for channel operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, channel: Channel) -> Channel:
        """Save or update channel."""
        model = await self.session.get(ChannelModel, channel.id)

        if model is None:
            model = ChannelModel(
                id=channel.id,
                campaign_id=channel.campaign_id,
                link=channel.link,
                username=channel.username,
                telegram_id=channel.telegram_id,
                title=channel.title,
                status=channel.status,
                error_message=channel.error_message,
                last_post_id=channel.last_post_id,
                comments_posted=channel.comments_posted,
                created_at=channel.created_at,
                last_checked_at=channel.last_checked_at,
                owner_id=channel.owner_id,
            )
            self.session.add(model)
        else:
            model.link = channel.link
            model.username = channel.username
            model.telegram_id = channel.telegram_id
            model.title = channel.title
            model.status = channel.status
            model.error_message = channel.error_message
            model.last_post_id = channel.last_post_id
            model.comments_posted = channel.comments_posted
            model.last_checked_at = channel.last_checked_at

        await self.session.flush()
        return channel

    async def get_by_id(self, channel_id: UUID) -> Optional[Channel]:
        """Get channel by ID."""
        model = await self.session.get(ChannelModel, channel_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def list_by_campaign(self, campaign_id: UUID) -> list[Channel]:
        """List all channels in a campaign."""
        stmt = (
            select(ChannelModel)
            .where(ChannelModel.campaign_id == campaign_id)
            .order_by(ChannelModel.created_at)
        )
        result = await self.session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars()]

    async def list_active_by_campaign(self, campaign_id: UUID) -> list[Channel]:
        """List active channels in a campaign."""
        stmt = (
            select(ChannelModel)
            .where(
                ChannelModel.campaign_id == campaign_id,
                ChannelModel.status == ChannelStatus.ACTIVE,
            )
        )
        result = await self.session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars()]

    async def list_unassigned(self, campaign_id: UUID) -> list[Channel]:
        """List channels without assignment in a campaign."""
        stmt = (
            select(ChannelModel)
            .outerjoin(ChannelAssignmentModel)
            .where(
                ChannelModel.campaign_id == campaign_id,
                ChannelModel.status == ChannelStatus.ACTIVE,
                ChannelAssignmentModel.id.is_(None),
            )
        )
        result = await self.session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars()]

    async def delete(self, channel_id: UUID) -> bool:
        """Delete channel."""
        model = await self.session.get(ChannelModel, channel_id)
        if model is None:
            return False
        await self.session.delete(model)
        return True

    def _to_entity(self, model: ChannelModel) -> Channel:
        """Convert model to entity."""
        return Channel(
            id=model.id,
            campaign_id=model.campaign_id,
            link=model.link,
            username=model.username,
            telegram_id=model.telegram_id,
            title=model.title,
            status=model.status,
            error_message=model.error_message,
            last_post_id=model.last_post_id,
            comments_posted=model.comments_posted,
            created_at=model.created_at,
            last_checked_at=model.last_checked_at,
            owner_id=model.owner_id,
        )


class ChannelAssignmentRepository:
    """Repository for channel assignment operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, assignment: ChannelAssignment) -> ChannelAssignment:
        """Save or update assignment."""
        model = await self.session.get(ChannelAssignmentModel, assignment.id)

        if model is None:
            model = ChannelAssignmentModel(
                id=assignment.id,
                channel_id=assignment.channel_id,
                account_id=assignment.account_id,
                campaign_id=assignment.campaign_id,
                status=assignment.status,
                assigned_at=assignment.assigned_at,
                last_activity_at=assignment.last_activity_at,
                fail_count=assignment.fail_count,
                swap_count=assignment.swap_count,
                previous_account_id=assignment.previous_account_id,
                owner_id=assignment.owner_id,
            )
            self.session.add(model)
        else:
            model.account_id = assignment.account_id
            model.status = assignment.status
            model.assigned_at = assignment.assigned_at
            model.last_activity_at = assignment.last_activity_at
            model.fail_count = assignment.fail_count
            model.swap_count = assignment.swap_count
            model.previous_account_id = assignment.previous_account_id

        await self.session.flush()
        return assignment

    async def get_by_id(self, assignment_id: UUID) -> Optional[ChannelAssignment]:
        """Get assignment by ID."""
        model = await self.session.get(ChannelAssignmentModel, assignment_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def get_by_channel(self, channel_id: UUID) -> Optional[ChannelAssignment]:
        """Get assignment for a channel."""
        stmt = select(ChannelAssignmentModel).where(
            ChannelAssignmentModel.channel_id == channel_id
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_entity(model)

    async def list_by_account(self, account_id: UUID) -> list[ChannelAssignment]:
        """List all assignments for an account."""
        stmt = (
            select(ChannelAssignmentModel)
            .where(
                ChannelAssignmentModel.account_id == account_id,
                ChannelAssignmentModel.status == AssignmentStatus.ACTIVE,
            )
        )
        result = await self.session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars()]

    async def list_by_campaign(self, campaign_id: UUID) -> list[ChannelAssignment]:
        """List all assignments in a campaign."""
        stmt = (
            select(ChannelAssignmentModel)
            .where(ChannelAssignmentModel.campaign_id == campaign_id)
        )
        result = await self.session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars()]

    async def list_needing_swap(self, campaign_id: UUID) -> list[ChannelAssignment]:
        """List assignments that need account swap."""
        stmt = (
            select(ChannelAssignmentModel)
            .where(
                ChannelAssignmentModel.campaign_id == campaign_id,
                or_(
                    ChannelAssignmentModel.status == AssignmentStatus.BLOCKED,
                    ChannelAssignmentModel.fail_count >= 3,
                ),
            )
        )
        result = await self.session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars()]

    async def count_by_account(self, account_id: UUID) -> int:
        """Count active assignments for an account."""
        stmt = (
            select(ChannelAssignmentModel)
            .where(
                ChannelAssignmentModel.account_id == account_id,
                ChannelAssignmentModel.status == AssignmentStatus.ACTIVE,
            )
        )
        result = await self.session.execute(stmt)
        return len(result.scalars().all())

    async def delete(self, assignment_id: UUID) -> bool:
        """Delete assignment."""
        model = await self.session.get(ChannelAssignmentModel, assignment_id)
        if model is None:
            return False
        await self.session.delete(model)
        return True

    def _to_entity(self, model: ChannelAssignmentModel) -> ChannelAssignment:
        """Convert model to entity."""
        return ChannelAssignment(
            id=model.id,
            channel_id=model.channel_id,
            account_id=model.account_id,
            campaign_id=model.campaign_id,
            status=model.status,
            assigned_at=model.assigned_at,
            last_activity_at=model.last_activity_at,
            fail_count=model.fail_count,
            swap_count=model.swap_count,
            previous_account_id=model.previous_account_id,
            owner_id=model.owner_id,
        )


class CommentTaskRepository:
    """Repository for comment task operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, task: CommentTask) -> CommentTask:
        """Save or update task."""
        model = await self.session.get(CommentTaskModel, task.id)

        if model is None:
            model = CommentTaskModel(
                id=task.id,
                account_id=task.account_id,
                channel_link=task.channel_link,
                post_link=task.post_link,
                comment_text=task.comment_text,
                status=task.status,
                error_message=task.error_message,
                created_at=task.created_at,
                executed_at=task.executed_at,
                owner_id=task.owner_id,
            )
            self.session.add(model)
        else:
            model.account_id = task.account_id
            model.channel_link = task.channel_link
            model.post_link = task.post_link
            model.comment_text = task.comment_text
            model.status = task.status
            model.error_message = task.error_message
            model.executed_at = task.executed_at

        await self.session.flush()
        return task

    async def get_by_id(self, task_id: UUID) -> Optional[CommentTask]:
        """Get task by ID."""
        model = await self.session.get(CommentTaskModel, task_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def list_pending(self, owner_id: int, limit: int = 100) -> list[CommentTask]:
        """List pending tasks for an owner."""
        stmt = (
            select(CommentTaskModel)
            .where(
                CommentTaskModel.owner_id == owner_id,
                CommentTaskModel.status == TaskStatus.PENDING,
            )
            .order_by(CommentTaskModel.created_at)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars()]

    async def list_by_owner(
        self,
        owner_id: int,
        status: Optional[TaskStatus] = None,
        limit: int = 100,
    ) -> list[CommentTask]:
        """List tasks for an owner."""
        stmt = select(CommentTaskModel).where(CommentTaskModel.owner_id == owner_id)

        if status:
            stmt = stmt.where(CommentTaskModel.status == status)

        stmt = stmt.order_by(CommentTaskModel.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars()]

    def _to_entity(self, model: CommentTaskModel) -> CommentTask:
        """Convert model to entity."""
        return CommentTask(
            id=model.id,
            account_id=model.account_id,
            channel_link=model.channel_link,
            post_link=model.post_link,
            comment_text=model.comment_text,
            status=model.status,
            error_message=model.error_message,
            created_at=model.created_at,
            executed_at=model.executed_at,
            owner_id=model.owner_id,
        )
