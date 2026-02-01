"""
Scraper service for collecting targets from Telegram channels.

Handles:
- Connecting with scraper account
- Joining channels
- Collecting usernames from messages and comments
- Saving targets to campaign
"""

import asyncio
import random
from typing import Optional, Callable
from uuid import UUID

import structlog

from src.domain.entities import (
    Account,
    ScrapeTask,
    ScrapeTaskStatus,
    UserTarget,
    TargetStatus,
)
from src.infrastructure.telegram import TelegramWorkerClient
from src.domain.exceptions import TelegramFloodError

logger = structlog.get_logger(__name__)


class ScraperService:
    """
    Service for scraping targets from Telegram channels.

    Manages the full scraping workflow:
    1. Connect with scraper account
    2. Join channels from source list
    3. Collect usernames from messages/comments
    4. Save as targets (optionally to campaign)
    5. Leave channels (optional cleanup)
    """

    def __init__(
        self,
        account: Account,
        on_progress: Optional[Callable[[ScrapeTask], None]] = None,
        existing_usernames: Optional[set[str]] = None,
    ):
        """
        Initialize scraper service.

        Args:
            account: Account to use for scraping
            on_progress: Optional callback for progress updates
            existing_usernames: Set of usernames to skip (already in DB)
        """
        self._account = account
        self._client: Optional[TelegramWorkerClient] = None
        self._on_progress = on_progress
        self._cancelled = False
        self._existing_usernames = existing_usernames or set()

    async def start(self) -> None:
        """Connect the scraper account."""
        self._client = TelegramWorkerClient(
            account_id=str(self._account.id),
            session_data=self._account.session_data,
        )
        await self._client.connect()
        logger.info("Scraper connected", account_id=str(self._account.id))

    async def stop(self) -> None:
        """Disconnect the scraper account."""
        if self._client:
            await self._client.disconnect()
            self._client = None
        logger.info("Scraper disconnected", account_id=str(self._account.id))

    def cancel(self) -> None:
        """Cancel current scraping task."""
        self._cancelled = True

    async def run_scrape_task(self, task: ScrapeTask) -> ScrapeTask:
        """
        Run a scraping task.

        Args:
            task: Scrape task configuration

        Returns:
            Updated task with results
        """
        if not self._client:
            raise RuntimeError("Scraper not started. Call start() first.")

        self._cancelled = False
        task.start()
        self._notify_progress(task)

        collected_usernames: set[str] = set()
        joined_channels: list[str] = []

        try:
            for source in task.sources:
                if self._cancelled:
                    task.cancel()
                    break

                task.set_current_source(source)
                self._notify_progress(task)

                try:
                    # Join channel and get entity
                    channel_entity = await self._client.join_channel(source)
                    if channel_entity:
                        joined_channels.append(source)
                        # Random delay after joining (anti-detection)
                        await asyncio.sleep(random.uniform(1.5, 4.0))
                    else:
                        task.mark_source_failed(source, "Could not join channel")
                        self._notify_progress(task)
                        continue

                    # First try to get participants directly (more efficient for groups)
                    users = await self._client.scrape_group_participants(
                        entity=channel_entity,
                        max_users=task.max_users_per_source,
                        skip_bots=task.skip_bots,
                        skip_no_username=task.skip_no_username,
                    )

                    # If GetParticipants didn't work well, fall back to message scraping
                    if len(users) < 10:
                        logger.info("Few participants found, falling back to message scraping")
                        message_users = await self._client.scrape_channel_users_from_entity(
                            entity=channel_entity,
                            max_users=task.max_users_per_source,
                            scrape_comments=task.scrape_comments,
                            skip_bots=task.skip_bots,
                            skip_no_username=task.skip_no_username,
                        )
                        # Merge users, avoiding duplicates by user id
                        existing_ids = {u.get("id") for u in users}
                        for user in message_users:
                            if user.get("id") not in existing_ids:
                                users.append(user)

                    # Collect usernames (excluding already existing in DB)
                    new_usernames = []
                    skipped_existing = 0
                    for user in users:
                        username = user.get("username")
                        if not username:
                            continue
                        # Skip if already collected in this session
                        if username in collected_usernames:
                            continue
                        # Skip if already exists in database
                        if username.lower() in {u.lower() for u in self._existing_usernames}:
                            skipped_existing += 1
                            continue
                        collected_usernames.add(username)
                        new_usernames.append(username)

                    if skipped_existing > 0:
                        logger.info(
                            "Skipped existing usernames",
                            count=skipped_existing,
                            source=source,
                        )

                    task.mark_source_processed(source, len(new_usernames))
                    task.add_usernames(new_usernames)
                    self._notify_progress(task)

                    # Random delay between channels (anti-detection)
                    await asyncio.sleep(random.uniform(2.0, 5.0))

                except TelegramFloodError as e:
                    task.mark_source_failed(source, f"Flood wait: {e.wait_seconds}s")
                    self._notify_progress(task)
                    # Wait out the flood
                    await asyncio.sleep(e.wait_seconds)

                except Exception as e:
                    task.mark_source_failed(source, str(e))
                    self._notify_progress(task)
                    logger.error(
                        "Failed to scrape source",
                        source=source,
                        error=str(e),
                    )

            # Leave channels (cleanup)
            for channel in joined_channels:
                try:
                    await self._client.leave_channel(channel)
                    await asyncio.sleep(random.uniform(0.8, 2.0))
                except Exception as e:
                    logger.debug("Failed to leave channel", channel=channel, error=str(e))

            # Mark completed
            if not self._cancelled:
                task.complete(
                    users_added=len(task.collected_usernames),
                    users_skipped=task.total_users_found - len(task.collected_usernames),
                )

        except Exception as e:
            task.fail(str(e))
            logger.error("Scrape task failed", error=str(e))

        self._notify_progress(task)
        return task

    def _notify_progress(self, task: ScrapeTask) -> None:
        """Notify progress callback if set."""
        if self._on_progress:
            try:
                self._on_progress(task)
            except Exception as e:
                logger.debug("Progress callback error", error=str(e))


class ParallelScraperService:
    """
    Service for parallel scraping using multiple accounts.

    Distributes channels across accounts and scrapes them concurrently.
    """

    def __init__(
        self,
        accounts: list[Account],
        on_progress: Optional[Callable[[ScrapeTask], None]] = None,
        existing_usernames: Optional[set[str]] = None,
        max_concurrent_per_account: int = 1,
    ):
        """
        Initialize parallel scraper.

        Args:
            accounts: List of accounts to use for scraping
            on_progress: Optional callback for progress updates
            existing_usernames: Set of usernames to skip
            max_concurrent_per_account: Max concurrent operations per account
        """
        self._accounts = accounts
        self._on_progress = on_progress
        self._existing_usernames = existing_usernames or set()
        self._existing_usernames_lower = {u.lower() for u in self._existing_usernames}
        self._max_concurrent = max_concurrent_per_account
        self._clients: dict[UUID, TelegramWorkerClient] = {}
        self._cancelled = False
        self._lock = asyncio.Lock()
        self._collected_usernames: set[str] = set()

    async def start(self) -> int:
        """Connect all accounts. Returns number of successfully connected."""
        connected = 0
        for account in self._accounts:
            try:
                client = TelegramWorkerClient(
                    account_id=str(account.id),
                    session_data=account.session_data,
                )
                await client.connect()
                self._clients[account.id] = client
                connected += 1
                logger.info("Parallel scraper: account connected", account_id=str(account.id))
            except Exception as e:
                logger.error("Failed to connect account", account_id=str(account.id), error=str(e))
        return connected

    async def stop(self) -> None:
        """Disconnect all accounts."""
        for account_id, client in self._clients.items():
            try:
                await client.disconnect()
            except Exception as e:
                logger.debug("Error disconnecting", account_id=str(account_id), error=str(e))
        self._clients.clear()
        logger.info("Parallel scraper: all accounts disconnected")

    def cancel(self) -> None:
        """Cancel scraping."""
        self._cancelled = True

    async def run_scrape_task(self, task: ScrapeTask) -> ScrapeTask:
        """
        Run scraping task using multiple accounts in parallel.

        Distributes sources across available accounts.
        """
        if not self._clients:
            raise RuntimeError("No accounts connected. Call start() first.")

        self._cancelled = False
        task.start()
        self._notify_progress(task)

        # Distribute sources across accounts
        sources = list(task.sources)
        account_ids = list(self._clients.keys())
        num_accounts = len(account_ids)

        # Create source queues for each account
        source_queues: dict[UUID, list[str]] = {acc_id: [] for acc_id in account_ids}
        for i, source in enumerate(sources):
            acc_id = account_ids[i % num_accounts]
            source_queues[acc_id].append(source)

        joined_channels: list[tuple[UUID, str]] = []  # (account_id, channel)

        async def scrape_source(account_id: UUID, source: str) -> tuple[list[str], Optional[str]]:
            """Scrape a single source. Returns (usernames, error)."""
            if self._cancelled:
                return [], "Cancelled"

            client = self._clients[account_id]
            try:
                # Join channel
                channel_entity = await client.join_channel(source)
                if not channel_entity:
                    return [], "Could not join channel"

                async with self._lock:
                    joined_channels.append((account_id, source))

                await asyncio.sleep(random.uniform(1.5, 4.0))

                # Get participants
                users = await client.scrape_group_participants(
                    entity=channel_entity,
                    max_users=task.max_users_per_source,
                    skip_bots=task.skip_bots,
                    skip_no_username=task.skip_no_username,
                )

                # Fallback to message scraping if needed
                if len(users) < 10:
                    message_users = await client.scrape_channel_users_from_entity(
                        entity=channel_entity,
                        max_users=task.max_users_per_source,
                        scrape_comments=task.scrape_comments,
                        skip_bots=task.skip_bots,
                        skip_no_username=task.skip_no_username,
                    )
                    existing_ids = {u.get("id") for u in users}
                    for user in message_users:
                        if user.get("id") not in existing_ids:
                            users.append(user)

                # Filter usernames
                new_usernames = []
                async with self._lock:
                    for user in users:
                        username = user.get("username")
                        if not username:
                            continue
                        if username in self._collected_usernames:
                            continue
                        if username.lower() in self._existing_usernames_lower:
                            continue
                        self._collected_usernames.add(username)
                        new_usernames.append(username)

                return new_usernames, None

            except TelegramFloodError as e:
                await asyncio.sleep(e.wait_seconds)
                return [], f"Flood wait: {e.wait_seconds}s"
            except Exception as e:
                return [], str(e)

        async def process_account_queue(account_id: UUID, sources_queue: list[str]):
            """Process all sources for one account."""
            for source in sources_queue:
                if self._cancelled:
                    break

                async with self._lock:
                    task.set_current_source(source)
                    self._notify_progress(task)

                usernames, error = await scrape_source(account_id, source)

                async with self._lock:
                    if error:
                        task.mark_source_failed(source, error)
                    else:
                        task.mark_source_processed(source, len(usernames))
                        task.add_usernames(usernames)
                    self._notify_progress(task)

                await asyncio.sleep(random.uniform(2.0, 5.0))  # Random delay between channels

        try:
            # Run all account queues concurrently
            await asyncio.gather(*[
                process_account_queue(acc_id, sources_queue)
                for acc_id, sources_queue in source_queues.items()
            ])

            # Cleanup: leave all joined channels
            for account_id, channel in joined_channels:
                try:
                    client = self._clients.get(account_id)
                    if client:
                        await client.leave_channel(channel)
                        await asyncio.sleep(random.uniform(0.3, 1.0))
                except Exception as e:
                    logger.debug("Failed to leave channel", channel=channel, error=str(e))

            if not self._cancelled:
                task.complete(
                    users_added=len(task.collected_usernames),
                    users_skipped=task.total_users_found - len(task.collected_usernames),
                )

        except Exception as e:
            task.fail(str(e))
            logger.error("Parallel scrape task failed", error=str(e))

        self._notify_progress(task)
        return task

    def _notify_progress(self, task: ScrapeTask) -> None:
        """Notify progress callback."""
        if self._on_progress:
            try:
                self._on_progress(task)
            except Exception as e:
                logger.debug("Progress callback error", error=str(e))


def create_targets_from_usernames(
    usernames: list[str],
    campaign_id: Optional[UUID] = None,
    source: str = "scraper",
) -> list[UserTarget]:
    """
    Create UserTarget entities from collected usernames.

    Args:
        usernames: List of Telegram usernames
        campaign_id: Campaign to add targets to
        source: Source identifier

    Returns:
        List of UserTarget entities (not saved to DB yet)
    """
    targets = []
    for username in usernames:
        # Clean username
        username = username.strip().lstrip("@")
        if not username:
            continue

        target = UserTarget(
            campaign_id=campaign_id,
            username=username,
            source=source,
            status=TargetStatus.PENDING,
        )
        targets.append(target)

    return targets
