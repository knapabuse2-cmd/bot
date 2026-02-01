"""
Warmup Worker.

Executes warmup activities for accounts:
- Joining channels and groups
- Sending reactions
- Viewing messages
- Simulating natural behavior
- Scrolling feeds
- Reading message history
"""

import asyncio
import random
import logging
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from telethon import TelegramClient
from telethon.tl.functions.channels import JoinChannelRequest, GetFullChannelRequest
from telethon.tl.functions.messages import (
    GetHistoryRequest,
    SendReactionRequest,
    ReadHistoryRequest,
    GetDialogsRequest,
    SetTypingRequest,
)
from telethon.tl.types import (
    ReactionEmoji,
    InputPeerChannel,
    Channel,
    InputPeerEmpty,
    SendMessageTypingAction,
    SendMessageCancelAction,
)
from telethon.errors import (
    FloodWaitError,
    ChannelPrivateError,
    UserAlreadyParticipantError,
    ChatWriteForbiddenError,
    PeerFloodError,
    ChannelsTooMuchError,
    InviteHashExpiredError,
    UserBannedInChannelError,
)

from src.domain.entities import WarmupStatus, AccountWarmup, WarmupChannel, WarmupGroup
from src.services.warmup_service import WarmupService
from src.infrastructure.database.connection import get_session
from src.infrastructure.database.repositories import (
    AccountWarmupRepository,
    WarmupChannelRepository,
    WarmupGroupRepository,
)


logger = logging.getLogger(__name__)

# Common reaction emojis weighted by usage frequency
REACTION_EMOJIS = ["👍", "❤️", "🔥", "👏", "🎉", "😂", "🤔", "👀", "💯", "🙏"]

# Minimum interval between warmup cycles (seconds)
MIN_WARMUP_INTERVAL = 300  # 5 minutes
MAX_WARMUP_INTERVAL = 900  # 15 minutes


class WarmupWorker:
    """
    Worker that executes warmup activities for an account.

    Should be run as part of the main account worker loop.
    """

    def __init__(
        self,
        account_id: UUID,
        client: TelegramClient,
    ):
        self.account_id = account_id
        self.client = client
        self.warmup: Optional[AccountWarmup] = None
        self._running = False
        self._last_warmup_time: Optional[datetime] = None
        self._cycle_count = 0

    async def initialize(self) -> bool:
        """Initialize warmup worker. Returns True if account is in warmup."""
        async with get_session() as session:
            repo = AccountWarmupRepository(session)
            self.warmup = await repo.get_by_account_id(self.account_id)

        if not self.warmup or self.warmup.status != WarmupStatus.ACTIVE:
            return False

        logger.info(
            f"Warmup initialized for account {self.account_id}, "
            f"stage={self.warmup.stage}, status={self.warmup.status.value}"
        )
        return True

    async def refresh_warmup_state(self) -> bool:
        """Refresh warmup state from database."""
        async with get_session() as session:
            repo = AccountWarmupRepository(session)
            self.warmup = await repo.get_by_account_id(self.account_id)
        return self.warmup is not None and self.warmup.status == WarmupStatus.ACTIVE

    async def should_run_warmup(self) -> bool:
        """Check if warmup should run now."""
        if not self.warmup:
            return False

        if self.warmup.status != WarmupStatus.ACTIVE:
            return False

        # Check flood wait
        if self.warmup.flood_wait_until:
            if self.warmup.flood_wait_until > datetime.utcnow():
                wait_remaining = (self.warmup.flood_wait_until - datetime.utcnow()).seconds
                logger.debug(f"Account {self.account_id} in flood wait, {wait_remaining}s remaining")
                return False

        # Check minimum interval between warmup cycles
        if self._last_warmup_time:
            elapsed = (datetime.utcnow() - self._last_warmup_time).total_seconds()
            min_interval = random.uniform(MIN_WARMUP_INTERVAL, MAX_WARMUP_INTERVAL)
            if elapsed < min_interval:
                return False

        return True

    def get_next_warmup_delay(self) -> float:
        """Get delay before next warmup cycle."""
        return random.uniform(MIN_WARMUP_INTERVAL, MAX_WARMUP_INTERVAL)

    async def run_warmup_cycle(self) -> None:
        """Run a single warmup cycle."""
        if not await self.should_run_warmup():
            return

        self._cycle_count += 1
        self._last_warmup_time = datetime.utcnow()

        async with get_session() as session:
            service = WarmupService(session)

            # Refresh warmup state from DB
            await self.refresh_warmup_state()
            if not self.warmup:
                return

            # Check if should do activity based on persona active hours
            if not await service.should_do_activity(self.warmup):
                logger.debug(f"Account {self.account_id} not in active hours, skipping warmup")
                return

            # Check and update stage if needed
            self.warmup = await service.check_stage_progress(self.warmup)
            if self.warmup.status != WarmupStatus.ACTIVE:
                logger.info(f"Account {self.account_id} warmup status changed to {self.warmup.status.value}")
                return

            # Get current stage config
            stage_config = await service.get_current_stage_config(self.warmup)
            if not stage_config:
                logger.warning(f"No stage config for account {self.account_id}")
                return

            logger.info(
                f"Account {self.account_id} starting warmup cycle #{self._cycle_count}, "
                f"stage={self.warmup.stage}, daily_joins={self.warmup.daily_joins}, "
                f"daily_reactions={self.warmup.daily_reactions}"
            )

            # Try to do activities based on stage limits
            activities_done = 0

            # Randomize activity order for more natural behavior
            activities = ["join_channel", "join_group", "react", "scroll", "view_profile"]
            random.shuffle(activities)

            for activity in activities:
                try:
                    if activity == "join_channel":
                        # 1. Join channels
                        if await service.can_join_channel(self.warmup):
                            channels = await service.get_channels_to_join(self.warmup, limit=1)
                            for channel in channels:
                                success = await self._join_channel(channel.username)
                                await service.record_channel_join(
                                    self.warmup, channel.username, success=success
                                )
                                if success:
                                    activities_done += 1
                                    await self._random_delay(30, 120)

                    elif activity == "join_group":
                        # 2. Join groups
                        stage_config = await service.get_current_stage_config(self.warmup)
                        if stage_config and self.warmup.daily_joins < (stage_config.join_channels + stage_config.join_groups):
                            groups = await service.get_groups_to_join(self.warmup, limit=1)
                            for group in groups:
                                success = await self._join_group(group.username)
                                await service.record_group_join(
                                    self.warmup, group.username, success=success
                                )
                                if success:
                                    activities_done += 1
                                    await self._random_delay(30, 120)

                    elif activity == "react":
                        # 3. Send reactions (potentially multiple)
                        if await service.can_send_reaction(self.warmup):
                            # Send 1-3 reactions per cycle
                            reactions_to_send = random.randint(1, 3)
                            for _ in range(reactions_to_send):
                                if not await service.can_send_reaction(self.warmup):
                                    break
                                reacted = await self._react_to_random_post()
                                if reacted:
                                    await service.record_reaction(self.warmup, "random_post")
                                    activities_done += 1
                                    await self._random_delay(5, 30)

                    elif activity == "scroll":
                        # 4. Read messages and scroll dialogs (passive activity)
                        await self._scroll_dialogs()
                        await self._random_delay(2, 10)

                    elif activity == "view_profile":
                        # 5. View random profile (natural behavior)
                        await self._view_random_profile()
                        await self._random_delay(3, 15)

                except FloodWaitError as e:
                    await self._handle_flood_wait(e.seconds)
                    break
                except Exception as e:
                    logger.error(f"Error in warmup activity {activity}: {e}")
                    continue

            await session.commit()
            logger.info(
                f"Account {self.account_id} completed warmup cycle #{self._cycle_count}, "
                f"activities_done={activities_done}"
            )

    async def _join_channel(self, username: str) -> bool:
        """Join a channel."""
        try:
            # Add @ if missing
            if not username.startswith("@"):
                username = f"@{username}"

            entity = await self.client.get_entity(username)
            await self.client(JoinChannelRequest(entity))
            logger.info(f"Account {self.account_id} joined channel {username}")
            return True
        except UserAlreadyParticipantError:
            logger.debug(f"Account {self.account_id} already in {username}")
            return True
        except FloodWaitError as e:
            await self._handle_flood_wait(e.seconds)
            return False
        except ChannelPrivateError:
            logger.warning(f"Channel {username} is private")
            return False
        except PeerFloodError:
            logger.warning(f"Account {self.account_id} got peer flood")
            await self._handle_flood_wait(300)
            return False
        except ChannelsTooMuchError:
            logger.warning(f"Account {self.account_id} joined too many channels")
            return False
        except InviteHashExpiredError:
            logger.warning(f"Invite link for {username} expired")
            return False
        except UserBannedInChannelError:
            logger.warning(f"Account {self.account_id} is banned in {username}")
            return False
        except Exception as e:
            logger.error(f"Error joining {username}: {e}")
            return False

    async def _join_group(self, username: str) -> bool:
        """Join a group."""
        # Same as channel join
        return await self._join_channel(username)

    async def _view_random_profile(self) -> bool:
        """View a random user profile from dialogs (natural behavior)."""
        try:
            dialogs = await self.client.get_dialogs(limit=30)

            # Filter to users (not channels/groups)
            users = [d for d in dialogs if d.is_user and not d.entity.bot]
            if not users:
                return False

            # Pick random user
            dialog = random.choice(users)

            # Get full user info (simulates viewing profile)
            try:
                await self.client.get_entity(dialog.entity.id)
                logger.debug(f"Account {self.account_id} viewed profile of user {dialog.entity.id}")
                return True
            except Exception:
                return False

        except Exception as e:
            logger.debug(f"Error viewing profile: {e}")
            return False

    async def _read_channel_history(self) -> bool:
        """Read message history in a random joined channel."""
        try:
            dialogs = await self.client.get_dialogs(limit=50)

            # Filter channels
            channels = [d for d in dialogs if d.is_channel and not d.is_group]
            if not channels:
                return False

            # Pick random channel
            channel = random.choice(channels)

            # Get message history (simulates scrolling through channel)
            messages = await self.client.get_messages(channel.entity, limit=random.randint(10, 30))

            # Simulate reading time
            if messages:
                read_time = random.uniform(2, 8)
                await asyncio.sleep(read_time)

                # Mark as read
                try:
                    await self.client(
                        ReadHistoryRequest(
                            peer=channel.input_entity,
                            max_id=messages[0].id if messages else 0,
                        )
                    )
                except Exception:
                    pass

            logger.debug(f"Account {self.account_id} read history in {channel.name}")
            return True

        except Exception as e:
            logger.debug(f"Error reading channel history: {e}")
            return False

    async def _react_to_random_post(self) -> bool:
        """React to a random post in joined channels."""
        try:
            # Get dialogs
            dialogs = await self.client.get_dialogs(limit=30)

            # Filter channels
            channels = [d for d in dialogs if d.is_channel and not d.is_group]
            if not channels:
                return False

            # Pick random channel
            channel = random.choice(channels)

            # Get recent messages
            messages = await self.client.get_messages(channel.entity, limit=10)
            if not messages:
                return False

            # Pick random message
            message = random.choice(messages)
            if not message or not message.id:
                return False

            # Send reaction
            emoji = random.choice(REACTION_EMOJIS)
            await self.client(
                SendReactionRequest(
                    peer=channel.input_entity,
                    msg_id=message.id,
                    reaction=[ReactionEmoji(emoticon=emoji)],
                )
            )
            logger.debug(f"Account {self.account_id} reacted {emoji} to message in {channel.name}")
            return True

        except FloodWaitError as e:
            await self._handle_flood_wait(e.seconds)
            return False
        except Exception as e:
            logger.debug(f"Error sending reaction: {e}")
            return False

    async def _scroll_dialogs(self) -> None:
        """Simulate scrolling through dialogs (passive activity)."""
        try:
            dialogs = await self.client.get_dialogs(limit=20)

            # Mark some as read
            for dialog in dialogs[:5]:
                try:
                    await self.client(
                        ReadHistoryRequest(
                            peer=dialog.input_entity,
                            max_id=dialog.message.id if dialog.message else 0,
                        )
                    )
                    await asyncio.sleep(random.uniform(0.5, 2))
                except Exception:
                    pass

        except Exception as e:
            logger.debug(f"Error scrolling dialogs: {e}")

    async def _handle_flood_wait(self, seconds: int) -> None:
        """Handle flood wait by updating warmup record."""
        async with get_session() as session:
            service = WarmupService(session)
            if self.warmup:
                await service.record_flood_wait(self.warmup, seconds)
                await session.commit()

    async def _random_delay(self, min_sec: int, max_sec: int) -> None:
        """Wait for a random delay."""
        delay = random.uniform(min_sec, max_sec)
        await asyncio.sleep(delay)


class WarmupScheduler:
    """
    Scheduler that runs warmup cycles periodically.

    Manages warmup execution across all active accounts.
    """

    def __init__(self):
        self._running = False
        self._workers: dict[UUID, WarmupWorker] = {}

    async def start(self) -> None:
        """Start the warmup scheduler."""
        self._running = True
        logger.info("Warmup scheduler started")

        while self._running:
            try:
                await self._run_daily_reset()
                await asyncio.sleep(random.uniform(55, 75))  # Check ~every minute with jitter
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in warmup scheduler: {e}")
                await asyncio.sleep(random.uniform(55, 75))

    async def stop(self) -> None:
        """Stop the warmup scheduler."""
        self._running = False
        logger.info("Warmup scheduler stopped")

    async def _run_daily_reset(self) -> None:
        """Reset daily counters at midnight."""
        now = datetime.utcnow()
        if now.hour == 0 and now.minute < 2:
            async with get_session() as session:
                service = WarmupService(session)
                count = await service.reset_daily_counters()
                await session.commit()
                if count > 0:
                    logger.info(f"Reset daily counters for {count} warmups")


class AccountWarmupManager:
    """
    Manages warmup for a single account within the account worker.

    This class is designed to be embedded in AccountWorker/AccountWorkerV2
    and handles warmup lifecycle without creating new workers.
    """

    def __init__(self, account_id: UUID, client: TelegramClient):
        self.account_id = account_id
        self.client = client
        self._worker: Optional[WarmupWorker] = None
        self._is_warmup_account = False
        self._initialized = False
        self._warmup_task: Optional[asyncio.Task] = None

    async def initialize(self) -> bool:
        """
        Initialize warmup manager.

        Returns True if account is in warmup mode.
        """
        if self._initialized:
            return self._is_warmup_account

        self._worker = WarmupWorker(self.account_id, self.client)
        self._is_warmup_account = await self._worker.initialize()
        self._initialized = True

        if self._is_warmup_account:
            logger.info(f"Account {self.account_id} is in warmup mode")

        return self._is_warmup_account

    @property
    def is_warmup_active(self) -> bool:
        """Check if warmup is active for this account."""
        return self._is_warmup_account and self._worker is not None

    @property
    def warmup_status(self) -> Optional[WarmupStatus]:
        """Get current warmup status."""
        if self._worker and self._worker.warmup:
            return self._worker.warmup.status
        return None

    @property
    def warmup_stage(self) -> Optional[int]:
        """Get current warmup stage."""
        if self._worker and self._worker.warmup:
            return self._worker.warmup.stage
        return None

    def can_do_outreach(self) -> bool:
        """Check if account can do cold outreach (only after warmup completed)."""
        if not self._is_warmup_account:
            return True  # Not in warmup, can do outreach

        if self._worker and self._worker.warmup:
            # Only completed warmup can do outreach
            if self._worker.warmup.status == WarmupStatus.COMPLETED:
                return True

        # Account is in warmup - NO messaging allowed
        return False

    def can_respond_to_messages(self) -> bool:
        """Check if account can respond to incoming messages."""
        # Same logic - warmup accounts should not respond at all
        return self.can_do_outreach()

    async def run_warmup_cycle(self) -> bool:
        """
        Run a warmup cycle if applicable.

        Returns True if warmup cycle was executed.
        """
        if not self._is_warmup_account or not self._worker:
            return False

        if not await self._worker.should_run_warmup():
            return False

        try:
            await self._worker.run_warmup_cycle()
            return True
        except Exception as e:
            logger.error(f"Error in warmup cycle for {self.account_id}: {e}")
            return False

    async def refresh_warmup_state(self) -> bool:
        """
        Refresh warmup state from database.

        Returns True if still in warmup mode.
        """
        if not self._worker:
            return False

        self._is_warmup_account = await self._worker.refresh_warmup_state()
        return self._is_warmup_account

    def get_next_warmup_delay(self) -> float:
        """Get delay until next warmup cycle."""
        if self._worker:
            return self._worker.get_next_warmup_delay()
        return random.uniform(MIN_WARMUP_INTERVAL, MAX_WARMUP_INTERVAL)

    def get_warmup_info(self) -> dict:
        """Get warmup information for logging/stats."""
        if not self._worker or not self._worker.warmup:
            return {"is_warmup": False}

        warmup = self._worker.warmup
        return {
            "is_warmup": True,
            "status": warmup.status.value,
            "stage": warmup.stage,
            "channels_joined": warmup.channels_joined,
            "groups_joined": warmup.groups_joined,
            "reactions_sent": warmup.reactions_sent,
            "daily_joins": warmup.daily_joins,
            "daily_reactions": warmup.daily_reactions,
            "cycle_count": self._worker._cycle_count,
        }


# Helper function for integration with account worker
async def run_warmup_for_account(
    account_id: UUID,
    client: TelegramClient,
) -> bool:
    """
    Run warmup cycle for an account.

    Should be called from the main account worker loop.
    Returns True if warmup was executed, False if not in warmup mode.
    """
    worker = WarmupWorker(account_id, client)

    if not await worker.initialize():
        return False

    await worker.run_warmup_cycle()
    return True


async def check_warmup_status(account_id: UUID) -> Optional[AccountWarmup]:
    """
    Check warmup status for an account.

    Returns AccountWarmup if exists, None otherwise.
    """
    async with get_session() as session:
        repo = AccountWarmupRepository(session)
        return await repo.get_by_account_id(account_id)


async def is_account_in_warmup(account_id: UUID) -> bool:
    """Check if account is currently in active warmup."""
    warmup = await check_warmup_status(account_id)
    return warmup is not None and warmup.status == WarmupStatus.ACTIVE
