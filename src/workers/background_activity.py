"""
Background Activity Worker.

Simulates human-like behavior for accounts between outreach tasks:
- Random online status (go online/offline)
- Read channels and mark as read
- Send reactions to posts
- View profiles
- Scroll through dialogs
- Random typing simulation

This runs in parallel with main task processing to make accounts
look more natural and avoid detection.
"""

import asyncio
import random
import logging
from datetime import datetime, timedelta
from typing import Optional, List
from uuid import UUID
from enum import Enum

from telethon import TelegramClient
from telethon.tl.functions.messages import (
    ReadHistoryRequest,
    SendReactionRequest,
    GetDialogsRequest,
    SetTypingRequest,
)
from telethon.tl.functions.account import (
    UpdateStatusRequest,
)
from telethon.tl.types import (
    ReactionEmoji,
    SendMessageTypingAction,
    SendMessageCancelAction,
)
from telethon.errors import (
    FloodWaitError,
    PeerFloodError,
)

logger = logging.getLogger(__name__)


class ActivityType(str, Enum):
    """Types of background activities."""
    GO_ONLINE = "go_online"
    GO_OFFLINE = "go_offline"
    READ_CHANNEL = "read_channel"
    READ_DIALOG = "read_dialog"
    SEND_REACTION = "send_reaction"
    VIEW_PROFILE = "view_profile"
    SCROLL_DIALOGS = "scroll_dialogs"
    TYPING_SIMULATION = "typing_simulation"


# Reaction emojis weighted by natural usage
REACTION_EMOJIS = [
    "👍", "👍", "👍",  # Most common (3x weight)
    "❤️", "❤️",        # Common (2x weight)
    "🔥", "🔥",        # Common
    "😂",              # Normal weight
    "👏",
    "🎉",
    "🤔",
    "👀",
    "💯",
    "🙏",
    "😍",
    "🤣",
    "👌",
]


class BackgroundActivityManager:
    """
    Manages background human-like activities for a single account.

    Runs independently from the main task processing loop,
    simulating natural user behavior.
    """

    def __init__(
        self,
        account_id: UUID,
        client: TelegramClient,
        # Timing configuration (in seconds)
        min_activity_interval: float = 120.0,   # Min 2 minutes between activities
        max_activity_interval: float = 600.0,   # Max 10 minutes between activities
        min_online_duration: float = 60.0,      # Min time to stay online
        max_online_duration: float = 300.0,     # Max time to stay online
        min_offline_duration: float = 300.0,    # Min time to stay offline
        max_offline_duration: float = 1800.0,   # Max time to stay offline (30 min)
        # Probability weights for activities
        activity_weights: Optional[dict] = None,
        # Account-specific random offset for desynchronization
        timing_offset_seed: Optional[int] = None,
    ):
        self.account_id = account_id
        self.client = client

        # Timing config
        self._min_activity_interval = min_activity_interval
        self._max_activity_interval = max_activity_interval
        self._min_online_duration = min_online_duration
        self._max_online_duration = max_online_duration
        self._min_offline_duration = min_offline_duration
        self._max_offline_duration = max_offline_duration

        # Activity weights (probability of each activity type)
        self._activity_weights = activity_weights or {
            ActivityType.READ_CHANNEL: 25,
            ActivityType.READ_DIALOG: 20,
            ActivityType.SCROLL_DIALOGS: 20,
            ActivityType.SEND_REACTION: 15,
            ActivityType.VIEW_PROFILE: 10,
            ActivityType.TYPING_SIMULATION: 10,
        }

        # State
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._is_online = False
        self._last_activity_time: Optional[datetime] = None
        self._last_online_change: Optional[datetime] = None
        self._activities_done = 0
        self._flood_wait_until: Optional[datetime] = None

        # Random seed for consistent but unique timing per account
        if timing_offset_seed is None:
            # Use account_id bytes to create a seed
            timing_offset_seed = int(str(account_id).replace("-", "")[:8], 16)
        self._rng = random.Random(timing_offset_seed)

        # Initial random offset so accounts don't all start at same time
        self._initial_offset = self._rng.uniform(0, 120)  # 0-2 min random offset

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def stats(self) -> dict:
        return {
            "account_id": str(self.account_id),
            "running": self._running,
            "is_online": self._is_online,
            "activities_done": self._activities_done,
            "last_activity": self._last_activity_time.isoformat() if self._last_activity_time else None,
            "flood_wait_until": self._flood_wait_until.isoformat() if self._flood_wait_until else None,
        }

    async def start(self) -> None:
        """Start background activity loop."""
        if self._running:
            return

        self._running = True

        # Apply initial offset so accounts don't start activities simultaneously
        await asyncio.sleep(self._initial_offset)

        self._task = asyncio.create_task(self._activity_loop())
        logger.info(f"Background activity started for account {self.account_id}")

    async def stop(self) -> None:
        """Stop background activity loop."""
        if not self._running:
            return

        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # Go offline when stopping
        await self._go_offline()

        logger.info(f"Background activity stopped for account {self.account_id}")

    async def _activity_loop(self) -> None:
        """Main activity loop."""
        while self._running:
            try:
                # Check flood wait
                if self._flood_wait_until and datetime.utcnow() < self._flood_wait_until:
                    wait_time = (self._flood_wait_until - datetime.utcnow()).total_seconds()
                    logger.debug(f"Account {self.account_id} in flood wait, sleeping {wait_time:.0f}s")
                    await asyncio.sleep(min(wait_time, 60))
                    continue

                # Manage online/offline status
                await self._manage_online_status()

                # Only do activities while "online"
                if self._is_online:
                    # Pick and execute random activity
                    await self._do_random_activity()

                # Wait before next activity cycle
                interval = self._rng.uniform(
                    self._min_activity_interval,
                    self._max_activity_interval
                )
                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except FloodWaitError as e:
                self._flood_wait_until = datetime.utcnow() + timedelta(seconds=e.seconds)
                logger.warning(f"Account {self.account_id} got flood wait: {e.seconds}s")
            except Exception as e:
                logger.error(f"Error in background activity for {self.account_id}: {e}")
                await asyncio.sleep(self._rng.uniform(25, 45))  # Random error delay

    async def _manage_online_status(self) -> None:
        """Manage online/offline cycling."""
        now = datetime.utcnow()

        if not self._last_online_change:
            # First run - go online
            await self._go_online()
            return

        elapsed = (now - self._last_online_change).total_seconds()

        if self._is_online:
            # Check if should go offline
            online_duration = self._rng.uniform(
                self._min_online_duration,
                self._max_online_duration
            )
            if elapsed > online_duration:
                await self._go_offline()
        else:
            # Check if should go online
            offline_duration = self._rng.uniform(
                self._min_offline_duration,
                self._max_offline_duration
            )
            if elapsed > offline_duration:
                await self._go_online()

    async def _go_online(self) -> None:
        """Set account status to online."""
        try:
            await self.client(UpdateStatusRequest(offline=False))
            self._is_online = True
            self._last_online_change = datetime.utcnow()
            logger.debug(f"Account {self.account_id} went online")
        except Exception as e:
            logger.debug(f"Error going online: {e}")

    async def _go_offline(self) -> None:
        """Set account status to offline."""
        try:
            await self.client(UpdateStatusRequest(offline=True))
            self._is_online = False
            self._last_online_change = datetime.utcnow()
            logger.debug(f"Account {self.account_id} went offline")
        except Exception as e:
            logger.debug(f"Error going offline: {e}")

    async def _do_random_activity(self) -> None:
        """Execute a random activity based on weights."""
        # Build weighted list
        activities = []
        weights = []
        for activity, weight in self._activity_weights.items():
            activities.append(activity)
            weights.append(weight)

        # Choose activity
        activity = self._rng.choices(activities, weights=weights, k=1)[0]

        try:
            if activity == ActivityType.READ_CHANNEL:
                await self._read_random_channel()
            elif activity == ActivityType.READ_DIALOG:
                await self._read_random_dialog()
            elif activity == ActivityType.SCROLL_DIALOGS:
                await self._scroll_dialogs()
            elif activity == ActivityType.SEND_REACTION:
                await self._send_random_reaction()
            elif activity == ActivityType.VIEW_PROFILE:
                await self._view_random_profile()
            elif activity == ActivityType.TYPING_SIMULATION:
                await self._simulate_typing()

            self._activities_done += 1
            self._last_activity_time = datetime.utcnow()

        except FloodWaitError:
            raise  # Re-raise to be handled by main loop
        except Exception as e:
            logger.debug(f"Activity {activity.value} failed: {e}")

    async def _read_random_channel(self) -> None:
        """Read messages in a random channel."""
        try:
            dialogs = await self.client.get_dialogs(limit=50)

            # Filter to channels only
            channels = [d for d in dialogs if d.is_channel and not d.is_group]
            if not channels:
                return

            channel = self._rng.choice(channels)

            # Get recent messages
            messages = await self.client.get_messages(
                channel.entity,
                limit=self._rng.randint(5, 20)
            )

            if messages:
                # Simulate reading time
                read_time = self._rng.uniform(2, 10)
                await asyncio.sleep(read_time)

                # Mark as read
                try:
                    await self.client(
                        ReadHistoryRequest(
                            peer=channel.input_entity,
                            max_id=messages[0].id,
                        )
                    )
                except Exception:
                    pass

            logger.debug(f"Account {self.account_id} read channel {getattr(channel.entity, 'title', 'unknown')}")

        except Exception as e:
            logger.debug(f"Error reading channel: {e}")

    async def _read_random_dialog(self) -> None:
        """Read messages in a random dialog (DM or group)."""
        try:
            dialogs = await self.client.get_dialogs(limit=30)

            # Filter to users and groups
            chats = [d for d in dialogs if d.is_user or d.is_group]
            if not chats:
                return

            dialog = self._rng.choice(chats)

            # Get recent messages
            messages = await self.client.get_messages(
                dialog.entity,
                limit=self._rng.randint(3, 10)
            )

            if messages:
                # Simulate reading
                read_time = self._rng.uniform(1, 5)
                await asyncio.sleep(read_time)

                # Mark as read
                try:
                    await self.client(
                        ReadHistoryRequest(
                            peer=dialog.input_entity,
                            max_id=messages[0].id if messages else 0,
                        )
                    )
                except Exception:
                    pass

            logger.debug(f"Account {self.account_id} read dialog")

        except Exception as e:
            logger.debug(f"Error reading dialog: {e}")

    async def _scroll_dialogs(self) -> None:
        """Simulate scrolling through dialog list."""
        try:
            # Just fetch dialogs - this simulates opening the app
            dialogs = await self.client.get_dialogs(limit=self._rng.randint(10, 30))

            # Simulate scrolling time
            scroll_time = self._rng.uniform(1, 4)
            await asyncio.sleep(scroll_time)

            # Maybe mark a few as read
            for dialog in dialogs[:self._rng.randint(1, 3)]:
                try:
                    if dialog.message:
                        await self.client(
                            ReadHistoryRequest(
                                peer=dialog.input_entity,
                                max_id=dialog.message.id,
                            )
                        )
                        await asyncio.sleep(self._rng.uniform(0.3, 1.0))
                except Exception:
                    pass

            logger.debug(f"Account {self.account_id} scrolled dialogs")

        except Exception as e:
            logger.debug(f"Error scrolling dialogs: {e}")

    async def _send_random_reaction(self) -> None:
        """Send a reaction to a random post in channels."""
        try:
            dialogs = await self.client.get_dialogs(limit=40)

            # Filter to channels
            channels = [d for d in dialogs if d.is_channel and not d.is_group]
            if not channels:
                return

            channel = self._rng.choice(channels)

            # Get recent messages
            messages = await self.client.get_messages(channel.entity, limit=15)
            if not messages:
                return

            # Pick random message
            message = self._rng.choice(messages)
            if not message or not message.id:
                return

            # Send reaction
            emoji = self._rng.choice(REACTION_EMOJIS)
            await self.client(
                SendReactionRequest(
                    peer=channel.input_entity,
                    msg_id=message.id,
                    reaction=[ReactionEmoji(emoticon=emoji)],
                )
            )

            logger.debug(f"Account {self.account_id} sent reaction {emoji}")

        except FloodWaitError:
            raise
        except Exception as e:
            logger.debug(f"Error sending reaction: {e}")

    async def _view_random_profile(self) -> None:
        """View a random user's profile."""
        try:
            dialogs = await self.client.get_dialogs(limit=30)

            # Filter to users
            users = [d for d in dialogs if d.is_user and not getattr(d.entity, 'bot', False)]
            if not users:
                return

            dialog = self._rng.choice(users)

            # Get entity (simulates viewing profile)
            await self.client.get_entity(dialog.entity.id)

            # Simulate viewing time
            view_time = self._rng.uniform(1, 3)
            await asyncio.sleep(view_time)

            logger.debug(f"Account {self.account_id} viewed a profile")

        except Exception as e:
            logger.debug(f"Error viewing profile: {e}")

    async def _simulate_typing(self) -> None:
        """Simulate typing in a random chat (then cancel)."""
        try:
            dialogs = await self.client.get_dialogs(limit=20)

            # Filter to users
            users = [d for d in dialogs if d.is_user and not getattr(d.entity, 'bot', False)]
            if not users:
                return

            dialog = self._rng.choice(users)

            # Start typing
            await self.client(
                SetTypingRequest(
                    peer=dialog.input_entity,
                    action=SendMessageTypingAction(),
                )
            )

            # Type for a bit
            typing_time = self._rng.uniform(2, 6)
            await asyncio.sleep(typing_time)

            # Cancel typing (simulate thinking and not sending)
            await self.client(
                SetTypingRequest(
                    peer=dialog.input_entity,
                    action=SendMessageCancelAction(),
                )
            )

            logger.debug(f"Account {self.account_id} simulated typing")

        except Exception as e:
            logger.debug(f"Error simulating typing: {e}")


def calculate_account_offset(account_id: UUID, total_accounts: int, spread_window_seconds: float = 3600.0) -> float:
    """
    Calculate a deterministic time offset for an account to spread activity.

    This ensures accounts don't all perform activities at the same time,
    distributing them evenly across the spread window.

    Args:
        account_id: Account UUID
        total_accounts: Total number of accounts for distribution
        spread_window_seconds: Time window to spread accounts over (default 1 hour)

    Returns:
        Offset in seconds for this account
    """
    # Use hash of account_id for deterministic offset
    hash_val = hash(str(account_id))
    # Normalize to 0-1 range
    normalized = (hash_val % 10000) / 10000.0
    # Scale to spread window
    return normalized * spread_window_seconds


def get_randomized_schedule_offset(account_id: UUID, base_interval: float, variance: float = 0.3) -> float:
    """
    Get a randomized interval with account-specific variance.

    Each account gets a consistent but different multiplier,
    so Account A might always be 10% faster while Account B is 15% slower.

    Args:
        account_id: Account UUID
        base_interval: Base interval in seconds
        variance: Maximum variance (0.3 = +/- 30%)

    Returns:
        Adjusted interval for this account
    """
    # Create account-specific random generator
    rng = random.Random(str(account_id))
    # Generate multiplier between (1-variance) and (1+variance)
    multiplier = 1 + rng.uniform(-variance, variance)
    return base_interval * multiplier
