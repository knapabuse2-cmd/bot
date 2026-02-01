"""
Warmup Service.

Handles account warmup logic including:
- Joining channels and groups
- Sending reactions
- Simulating natural behavior
- Managing warmup stages
"""

import asyncio
import random
import logging
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities import (
    WarmupProfile,
    AccountWarmup,
    AccountPersona,
    WarmupChannel,
    WarmupGroup,
    WarmupStatus,
    WarmupStage,
    ActivityPattern,
)
from src.infrastructure.database.repositories import (
    WarmupProfileRepository,
    AccountWarmupRepository,
    AccountPersonaRepository,
    WarmupChannelRepository,
    WarmupGroupRepository,
    WarmupActivityLogRepository,
    AccountGroupRepository,
)
from src.infrastructure.database.connection import get_session


logger = logging.getLogger(__name__)


# Default warmup profile stages (total 7 days)
DEFAULT_WARMUP_STAGES = [
    WarmupStage(stage=1, days=2, daily_messages=0, join_channels=3, join_groups=0, reactions_per_day=10, can_outreach=False),
    WarmupStage(stage=2, days=2, daily_messages=0, join_channels=3, join_groups=1, reactions_per_day=15, can_outreach=False),
    WarmupStage(stage=3, days=3, daily_messages=0, join_channels=2, join_groups=1, reactions_per_day=20, can_outreach=False),
]


class WarmupService:
    """Service for managing account warmup."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.profile_repo = WarmupProfileRepository(session)
        self.warmup_repo = AccountWarmupRepository(session)
        self.persona_repo = AccountPersonaRepository(session)
        self.channel_repo = WarmupChannelRepository(session)
        self.group_repo = WarmupGroupRepository(session)
        self.log_repo = WarmupActivityLogRepository(session)
        self.account_group_repo = AccountGroupRepository(session)

    # =========================================================================
    # Profile Management
    # =========================================================================

    async def create_default_profile(self) -> WarmupProfile:
        """Create default warmup profile if not exists."""
        existing = await self.profile_repo.get_default()
        if existing:
            return existing

        profile = WarmupProfile(
            id=UUID(bytes=__import__('os').urandom(16)),
            name="Standard",
            description="Standard 7-day warmup profile",
            total_days=7,
            stages=DEFAULT_WARMUP_STAGES,
            min_session_duration_minutes=10,
            max_session_duration_minutes=60,
            typing_speed_cpm=150,
            reaction_probability=0.3,
            is_default=True,
        )
        return await self.profile_repo.save(profile)

    async def get_profile(self, profile_id: UUID) -> Optional[WarmupProfile]:
        """Get warmup profile by ID."""
        return await self.profile_repo.get_by_id(profile_id)

    async def get_default_profile(self) -> Optional[WarmupProfile]:
        """Get default warmup profile."""
        profile = await self.profile_repo.get_default()
        if not profile:
            profile = await self.create_default_profile()
        return profile

    async def list_profiles(self) -> list[WarmupProfile]:
        """List all warmup profiles."""
        return await self.profile_repo.get_all()

    # =========================================================================
    # Warmup Management
    # =========================================================================

    async def start_warmup(
        self,
        account_id: UUID,
        profile_id: Optional[UUID] = None,
    ) -> AccountWarmup:
        """Start warmup for an account."""
        # Get or create default profile
        if not profile_id:
            profile = await self.get_default_profile()
            profile_id = profile.id if profile else None

        # Check if warmup already exists
        existing = await self.warmup_repo.get_by_account_id(account_id)
        if existing:
            if existing.status == WarmupStatus.COMPLETED:
                # Reset completed warmup
                existing.stage = 1
                existing.status = WarmupStatus.ACTIVE
                existing.started_at = datetime.utcnow()
                existing.stage_started_at = datetime.utcnow()
                existing.completed_at = None
                existing.profile_id = profile_id
                existing.channels_joined = 0
                existing.groups_joined = 0
                existing.reactions_sent = 0
                existing.messages_sent = 0
                await self.warmup_repo.save(existing)
                logger.info(f"Reset warmup for account {account_id}")
                return existing
            elif existing.status in (WarmupStatus.PENDING, WarmupStatus.PAUSED):
                existing.status = WarmupStatus.ACTIVE
                existing.started_at = existing.started_at or datetime.utcnow()
                existing.stage_started_at = existing.stage_started_at or datetime.utcnow()
                await self.warmup_repo.save(existing)
                return existing
            else:
                # Already active
                return existing

        # Create new warmup
        warmup = AccountWarmup(
            id=UUID(bytes=__import__('os').urandom(16)),
            account_id=account_id,
            profile_id=profile_id,
            stage=1,
            status=WarmupStatus.ACTIVE,
            started_at=datetime.utcnow(),
            stage_started_at=datetime.utcnow(),
        )
        warmup = await self.warmup_repo.save(warmup)
        logger.info(f"Started warmup for account {account_id}")
        return warmup

    async def start_warmup_for_group(
        self,
        group_id: UUID,
        profile_id: Optional[UUID] = None,
    ) -> int:
        """Start warmup for all accounts in a group."""
        account_ids = await self.account_group_repo.get_account_ids(group_id)
        count = 0
        for account_id in account_ids:
            await self.start_warmup(account_id, profile_id)
            count += 1
        logger.info(f"Started warmup for {count} accounts in group {group_id}")
        return count

    async def pause_warmup(self, account_id: UUID) -> Optional[AccountWarmup]:
        """Pause warmup for an account."""
        warmup = await self.warmup_repo.get_by_account_id(account_id)
        if warmup and warmup.status == WarmupStatus.ACTIVE:
            warmup.pause()
            await self.warmup_repo.save(warmup)
            logger.info(f"Paused warmup for account {account_id}")
        return warmup

    async def resume_warmup(self, account_id: UUID) -> Optional[AccountWarmup]:
        """Resume warmup for an account."""
        warmup = await self.warmup_repo.get_by_account_id(account_id)
        if warmup and warmup.status == WarmupStatus.PAUSED:
            warmup.resume()
            await self.warmup_repo.save(warmup)
            logger.info(f"Resumed warmup for account {account_id}")
        return warmup

    async def complete_warmup(self, account_id: UUID) -> Optional[AccountWarmup]:
        """Mark warmup as completed."""
        warmup = await self.warmup_repo.get_by_account_id(account_id)
        if warmup:
            warmup.complete()
            await self.warmup_repo.save(warmup)
            logger.info(f"Completed warmup for account {account_id}")
        return warmup

    async def get_warmup_status(self, account_id: UUID) -> Optional[AccountWarmup]:
        """Get warmup status for an account."""
        return await self.warmup_repo.get_by_account_id(account_id)

    async def get_active_warmups(self) -> list[AccountWarmup]:
        """Get all active warmups."""
        return await self.warmup_repo.get_active_warmups()

    # =========================================================================
    # Stage Management
    # =========================================================================

    async def check_stage_progress(self, warmup: AccountWarmup) -> AccountWarmup:
        """Check if account should advance to next stage."""
        if warmup.status != WarmupStatus.ACTIVE:
            return warmup

        profile = await self.profile_repo.get_by_id(warmup.profile_id) if warmup.profile_id else None
        if not profile:
            profile = await self.get_default_profile()

        current_stage = profile.get_stage_config(warmup.stage)
        if not current_stage:
            return warmup

        # Check if enough days have passed for current stage
        if warmup.stage_started_at:
            days_in_stage = (datetime.utcnow() - warmup.stage_started_at).days
            if days_in_stage >= current_stage.days and current_stage.days > 0:
                # Advance to next stage
                next_stage_num = warmup.stage + 1
                next_stage = profile.get_stage_config(next_stage_num)
                if next_stage:
                    warmup.advance_stage(next_stage_num)
                    warmup.current_daily_message_limit = next_stage.daily_messages
                    await self.warmup_repo.save(warmup)
                    logger.info(f"Account {warmup.account_id} advanced to stage {next_stage_num}")
                else:
                    # No more stages, complete warmup
                    warmup.complete()
                    await self.warmup_repo.save(warmup)
                    logger.info(f"Account {warmup.account_id} completed warmup")

        return warmup

    async def get_current_stage_config(self, warmup: AccountWarmup) -> Optional[WarmupStage]:
        """Get current stage configuration for a warmup."""
        profile = await self.profile_repo.get_by_id(warmup.profile_id) if warmup.profile_id else None
        if not profile:
            profile = await self.get_default_profile()
        return profile.get_stage_config(warmup.stage) if profile else None

    # =========================================================================
    # Activity Checking
    # =========================================================================

    async def should_do_activity(self, warmup: AccountWarmup) -> bool:
        """Check if warmup should perform activity now."""
        if not warmup.can_do_activity():
            return False

        # Check persona active hours
        persona = await self.persona_repo.get_by_account_id(warmup.account_id)
        if persona:
            now = datetime.utcnow()
            # Simple check - in production would convert to persona timezone
            current_hour = now.hour
            if not persona.is_active_time(current_hour):
                return False

        return True

    async def can_join_channel(self, warmup: AccountWarmup) -> bool:
        """Check if account can join more channels today."""
        stage = await self.get_current_stage_config(warmup)
        if not stage:
            return False
        return warmup.daily_joins < stage.join_channels

    async def can_send_reaction(self, warmup: AccountWarmup) -> bool:
        """Check if account can send more reactions today."""
        stage = await self.get_current_stage_config(warmup)
        if not stage:
            return False
        return warmup.daily_reactions < stage.reactions_per_day

    async def can_send_message(self, warmup: AccountWarmup) -> bool:
        """Check if account can send more messages today."""
        stage = await self.get_current_stage_config(warmup)
        if not stage:
            return False
        return warmup.daily_messages < stage.daily_messages

    async def can_do_outreach(self, warmup: AccountWarmup) -> bool:
        """Check if account can do cold outreach."""
        stage = await self.get_current_stage_config(warmup)
        if not stage:
            return False
        return stage.can_outreach and warmup.status == WarmupStatus.COMPLETED or (
            warmup.status == WarmupStatus.ACTIVE and stage.can_outreach
        )

    # =========================================================================
    # Channel/Group Selection
    # =========================================================================

    async def get_channels_to_join(
        self,
        warmup: AccountWarmup,
        limit: int = 5,
    ) -> list[WarmupChannel]:
        """Get channels for account to join."""
        persona = await self.persona_repo.get_by_account_id(warmup.account_id)
        language = persona.language if persona else "en"

        # Get already joined channel IDs
        # In full implementation, would query account_subscriptions
        exclude_ids: list[UUID] = []

        return await self.channel_repo.get_random_for_warmup(
            language=language,
            exclude_ids=exclude_ids,
            limit=limit,
        )

    async def get_groups_to_join(
        self,
        warmup: AccountWarmup,
        limit: int = 3,
    ) -> list[WarmupGroup]:
        """Get groups for account to join."""
        persona = await self.persona_repo.get_by_account_id(warmup.account_id)
        language = persona.language if persona else "en"

        exclude_ids: list[UUID] = []

        return await self.group_repo.get_random_for_warmup(
            language=language,
            exclude_ids=exclude_ids,
            limit=limit,
        )

    # =========================================================================
    # Activity Recording
    # =========================================================================

    async def record_channel_join(
        self,
        warmup: AccountWarmup,
        channel_username: str,
        success: bool = True,
        error: Optional[str] = None,
    ) -> None:
        """Record that account joined a channel."""
        await self.log_repo.log_activity(
            account_id=warmup.account_id,
            activity_type="channel_join",
            target=channel_username,
            success=success,
            error=error,
        )

        if success:
            warmup.channels_joined += 1
            warmup.daily_joins += 1
            warmup.record_activity()
            await self.warmup_repo.save(warmup)

    async def record_group_join(
        self,
        warmup: AccountWarmup,
        group_username: str,
        success: bool = True,
        error: Optional[str] = None,
    ) -> None:
        """Record that account joined a group."""
        await self.log_repo.log_activity(
            account_id=warmup.account_id,
            activity_type="group_join",
            target=group_username,
            success=success,
            error=error,
        )

        if success:
            warmup.groups_joined += 1
            warmup.daily_joins += 1
            warmup.record_activity()
            await self.warmup_repo.save(warmup)

    async def record_reaction(
        self,
        warmup: AccountWarmup,
        target: str,
        success: bool = True,
        error: Optional[str] = None,
    ) -> None:
        """Record that account sent a reaction."""
        await self.log_repo.log_activity(
            account_id=warmup.account_id,
            activity_type="reaction",
            target=target,
            success=success,
            error=error,
        )

        if success:
            warmup.reactions_sent += 1
            warmup.daily_reactions += 1
            warmup.record_activity()
            await self.warmup_repo.save(warmup)

    async def record_message(
        self,
        warmup: AccountWarmup,
        target: str,
        success: bool = True,
        error: Optional[str] = None,
    ) -> None:
        """Record that account sent a message."""
        await self.log_repo.log_activity(
            account_id=warmup.account_id,
            activity_type="message",
            target=target,
            success=success,
            error=error,
        )

        if success:
            warmup.messages_sent += 1
            warmup.daily_messages += 1
            warmup.record_activity()
            await self.warmup_repo.save(warmup)

    async def record_flood_wait(
        self,
        warmup: AccountWarmup,
        seconds: int,
    ) -> None:
        """Record that account got flood wait."""
        warmup.flood_wait_until = datetime.utcnow() + timedelta(seconds=seconds)
        await self.warmup_repo.save(warmup)
        logger.warning(f"Account {warmup.account_id} got flood wait for {seconds}s")

    # =========================================================================
    # Persona Management
    # =========================================================================

    async def create_persona(
        self,
        account_id: UUID,
        interests: Optional[list[str]] = None,
        language: str = "en",
        timezone: str = "UTC",
        activity_pattern: ActivityPattern = ActivityPattern.OFFICE_HOURS,
    ) -> AccountPersona:
        """Create persona for account."""
        persona = AccountPersona(
            id=UUID(bytes=__import__('os').urandom(16)),
            account_id=account_id,
            interests=interests or ["general"],
            activity_pattern=activity_pattern,
            timezone=timezone,
            language=language,
            typing_speed=random.randint(100, 200),
            reaction_probability=random.uniform(0.2, 0.4),
            min_response_delay=random.randint(3, 10),
            max_response_delay=random.randint(30, 90),
            active_hours_start=9 if activity_pattern == ActivityPattern.OFFICE_HOURS else 18,
            active_hours_end=22 if activity_pattern == ActivityPattern.OFFICE_HOURS else 2,
        )
        return await self.persona_repo.save(persona)

    async def get_or_create_persona(self, account_id: UUID) -> AccountPersona:
        """Get or create persona for account."""
        persona = await self.persona_repo.get_by_account_id(account_id)
        if not persona:
            persona = await self.create_persona(account_id)
        return persona

    # =========================================================================
    # Daily Reset
    # =========================================================================

    async def reset_daily_counters(self, current_hour: Optional[int] = None) -> int:
        """Reset daily counters for warmups whose reset hour has come.

        Each warmup has a randomized daily_reset_hour (0-23) to avoid all warmups
        resetting at the same time.

        Args:
            current_hour: Current UTC hour (0-23). If None, uses current time.

        Returns:
            Number of warmups reset
        """
        return await self.warmup_repo.reset_daily_counters(current_hour)

    async def initialize_daily_reset_hours(self) -> int:
        """Initialize random reset hours for warmups that don't have one.

        Returns:
            Number of warmups initialized
        """
        return await self.warmup_repo.initialize_daily_reset_hours()

    # =========================================================================
    # Statistics
    # =========================================================================

    async def get_warmup_stats(self) -> dict:
        """Get warmup statistics."""
        all_warmups = await self.warmup_repo.get_warmups_by_status(WarmupStatus.ACTIVE)
        pending = await self.warmup_repo.get_warmups_by_status(WarmupStatus.PENDING)
        completed = await self.warmup_repo.get_warmups_by_status(WarmupStatus.COMPLETED)
        paused = await self.warmup_repo.get_warmups_by_status(WarmupStatus.PAUSED)

        channels_count = await self.channel_repo.count()
        groups_count = await self.group_repo.count()

        return {
            "active_warmups": len(all_warmups),
            "pending_warmups": len(pending),
            "completed_warmups": len(completed),
            "paused_warmups": len(paused),
            "total_channels": channels_count,
            "total_groups": groups_count,
        }


# =========================================================================
# Helper function to get service with session
# =========================================================================

async def get_warmup_service() -> WarmupService:
    """Get warmup service with a new session."""
    async with get_session() as session:
        return WarmupService(session)
