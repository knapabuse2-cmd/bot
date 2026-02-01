"""Account worker.

Handles operations for a single Telegram account.

This worker is used by `WorkerManager` (v1).
Historically the code drifted away from the current `DialogueService` API
and called non-existent methods. This implementation is aligned with the
current service layer:
- start_dialogue
- process_incoming_message
- generate_follow_up
- list_pending_dialogues

It uses a session-factory pattern (no persistent DB session) and maintains a
small in-memory queue for "first message" tasks.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator, Callable, Optional
from uuid import UUID

import structlog

from src.application.services import AccountService, DialogueService
from src.application.services.dialogue_processor import MessageBatcher
from src.domain.entities import Account, Dialogue, MessageRole, ProxyStatus
from src.domain.exceptions import ProxyRequiredError, TelegramAuthError, TelegramFloodError, TelegramPrivacyError
from src.infrastructure.database import AsyncSession
from src.infrastructure.database.repositories import (
    PostgresAccountRepository,
    PostgresCampaignRepository,
    PostgresDialogueRepository,
    PostgresProxyRepository,
    PostgresUserTargetRepository,
    PostgresTelegramAppRepository,
)
from src.infrastructure.database.repositories.base import OptimisticLockError
from src.infrastructure.telegram import TelegramWorkerClient
from src.infrastructure.ai import OpenAIProvider
from src.utils.humanizer import Humanizer, get_humanizer
from src.workers.warmup_worker import AccountWarmupManager

logger = structlog.get_logger(__name__)


class AccountWorker:
    """Worker for a single Telegram account."""

    def __init__(
        self,
        account: Account,
        session_factory: Callable[[], AsyncGenerator[AsyncSession, None]],
        ai_provider: OpenAIProvider,
        humanizer: Optional[Humanizer] = None,
    ):
        self._account = account
        self._account_id = account.id
        self._session_factory = session_factory
        self._ai_provider = ai_provider
        self._humanizer = humanizer or get_humanizer()

        self._client: Optional[TelegramWorkerClient] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._pending_tasks: set[asyncio.Task] = set()
        self._last_health_check = datetime.utcnow()
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._dialogue_locks: dict[UUID, asyncio.Lock] = {}  # Per-dialogue locks to prevent concurrent modifications
        self._dialogue_locks_max_size: int = 500  # Limit to prevent unbounded growth
        self._message_batcher = MessageBatcher()  # Batches multiple user messages before responding

        # Warmup manager - initialized after client connection
        self._warmup_manager: Optional[AccountWarmupManager] = None
        self._warmup_initialized = False

    @property
    def account_id(self) -> UUID:
        return self._account_id

    @property
    def running(self) -> bool:
        return self._running

    @asynccontextmanager
    async def _get_session(self) -> AsyncGenerator[AsyncSession, None]:
        async with self._session_factory() as session:
            yield session

    async def _initialize_warmup(self) -> None:
        """Initialize warmup manager for the account."""
        if self._warmup_initialized or not self._client:
            return

        try:
            self._warmup_manager = AccountWarmupManager(
                account_id=self._account_id,
                client=self._client.client,  # Pass the underlying Telethon client
            )
            is_warmup = await self._warmup_manager.initialize()
            self._warmup_initialized = True

            if is_warmup:
                logger.info(
                    "Account in warmup mode",
                    account_id=str(self._account_id),
                    stage=self._warmup_manager.warmup_stage,
                    can_outreach=self._warmup_manager.can_do_outreach(),
                )
        except Exception as e:
            logger.error(
                "Failed to initialize warmup manager",
                account_id=str(self._account_id),
                error=str(e),
            )
            self._warmup_manager = None

    def _can_do_outreach(self) -> bool:
        """Check if account can do cold outreach (considering warmup)."""
        if self._warmup_manager:
            return self._warmup_manager.can_do_outreach()
        return True  # No warmup manager means no restrictions

    def _can_respond_to_messages(self) -> bool:
        """Check if account can respond to incoming messages (considering warmup)."""
        if self._warmup_manager:
            return self._warmup_manager.can_respond_to_messages()
        return True  # No warmup manager means no restrictions

    async def _get_account_service(self, session: AsyncSession) -> AccountService:
        account_repo = PostgresAccountRepository(session)
        proxy_repo = PostgresProxyRepository(session)
        return AccountService(account_repo, proxy_repo)

    async def _get_dialogue_service(self, session: AsyncSession) -> DialogueService:
        dialogue_repo = PostgresDialogueRepository(session)
        campaign_repo = PostgresCampaignRepository(session)
        target_repo = PostgresUserTargetRepository(session)
        return DialogueService(
            dialogue_repo=dialogue_repo,
            campaign_repo=campaign_repo,
            target_repo=target_repo,
            ai_provider=self._ai_provider,
            humanizer=self._humanizer,
        )

    def _get_dialogue_lock(self, dialogue_id: UUID) -> asyncio.Lock:
        """Get or create a lock for a specific dialogue to prevent concurrent modifications."""
        if dialogue_id not in self._dialogue_locks:
            # Evict unlocked entries if at capacity to prevent memory leak
            if len(self._dialogue_locks) >= self._dialogue_locks_max_size:
                to_remove = [
                    did for did, lock in self._dialogue_locks.items()
                    if not lock.locked()
                ]
                for did in to_remove:
                    del self._dialogue_locks[did]
            self._dialogue_locks[dialogue_id] = asyncio.Lock()
        return self._dialogue_locks[dialogue_id]

    async def _get_proxy_config(self, proxy_id: Optional[UUID] = None) -> Optional[dict]:
        """
        Get proxy configuration for Telethon.

        Args:
            proxy_id: Optional specific proxy ID. If None, uses account's proxy_id.

        Returns:
            Proxy config dict for Telethon or None
        """
        import python_socks

        target_proxy_id = proxy_id or self._account.proxy_id
        if not target_proxy_id:
            return None

        async with self._get_session() as session:
            proxy_repo = PostgresProxyRepository(session)
            proxy = await proxy_repo.get_by_id(target_proxy_id)

            if not proxy:
                raise ProxyRequiredError(
                    account_id=str(self._account_id),
                    context=f"proxy {target_proxy_id} not found in database"
                )

            proxy_type_map = {
                "socks5": python_socks.ProxyType.SOCKS5,
                "socks4": python_socks.ProxyType.SOCKS4,
                "http": python_socks.ProxyType.HTTP,
                "https": python_socks.ProxyType.HTTP,
            }

            return {
                "proxy_type": proxy_type_map.get(proxy.proxy_type.value, python_socks.ProxyType.SOCKS5),
                "addr": proxy.host,
                "port": proxy.port,
                "username": proxy.username,
                "password": proxy.password,
                "rdns": True,
            }

    async def _get_api_credentials(self) -> tuple[Optional[int], Optional[str]]:
        """
        Get API credentials for this account from its TelegramApp.

        Returns:
            Tuple of (api_id, api_hash) or (None, None) if not assigned
        """
        if not self._account.telegram_app_id:
            logger.debug(
                "Account has no TelegramApp assigned, using default credentials",
                account_id=str(self._account_id),
            )
            return None, None

        async with self._get_session() as session:
            app_repo = PostgresTelegramAppRepository(session)
            app = await app_repo.get_by_id(self._account.telegram_app_id)

            if not app:
                logger.warning(
                    "TelegramApp not found, using default credentials",
                    account_id=str(self._account_id),
                    app_id=str(self._account.telegram_app_id),
                )
                return None, None

            logger.debug(
                "Using TelegramApp credentials",
                account_id=str(self._account_id),
                app_name=app.name,
                api_id=app.api_id,
            )
            return app.api_id, app.api_hash

    async def _get_available_proxy(self, exclude_ids: list[UUID] = None) -> Optional[UUID]:
        """
        Find an available proxy that is not assigned or failed.

        Args:
            exclude_ids: List of proxy IDs to exclude from search

        Returns:
            Proxy UUID if found, None otherwise
        """
        exclude_ids = exclude_ids or []

        async with self._get_session() as session:
            proxy_repo = PostgresProxyRepository(session)

            # Get all available proxies (ACTIVE, SLOW, or UNKNOWN status, not assigned)
            proxies = await proxy_repo.list_available()

            # First try healthy proxies (ACTIVE or SLOW)
            for proxy in proxies:
                if proxy.id not in exclude_ids and proxy.is_healthy():
                    return proxy.id

            # If no healthy proxies, try unknown status ones
            for proxy in proxies:
                if proxy.id not in exclude_ids and proxy.status == ProxyStatus.UNKNOWN:
                    return proxy.id

        return None

    async def _mark_proxy_failed(self, proxy_id: UUID, error: str) -> None:
        """Mark a proxy as failed in the database."""
        async with self._get_session() as session:
            proxy_repo = PostgresProxyRepository(session)
            proxy = await proxy_repo.get_by_id(proxy_id)

            if proxy:
                proxy.mark_failed()
                await proxy_repo.save(proxy)
                await session.commit()

                logger.warning(
                    "Proxy marked as failed",
                    proxy_id=str(proxy_id),
                    error=error,
                )

    async def _assign_proxy_to_account(self, proxy_id: UUID) -> None:
        """Assign a new proxy to the account."""
        async with self._get_session() as session:
            account_repo = PostgresAccountRepository(session)
            account = await account_repo.get_by_id(self._account_id)

            if account:
                account.proxy_id = proxy_id
                await account_repo.save(account)
                await session.commit()

                # Update local reference
                self._account.proxy_id = proxy_id

                logger.info(
                    "New proxy assigned to account",
                    account_id=str(self._account_id),
                    proxy_id=str(proxy_id),
                )

    async def _try_reconnect_with_new_proxy(self) -> bool:
        """Attempt to reconnect with a different proxy after a runtime failure.

        Returns True if reconnection succeeded, False otherwise.
        """
        try:
            current_proxy_id = self._account.proxy_id
            if current_proxy_id:
                await self._mark_proxy_failed(current_proxy_id, "runtime connection error")

            new_proxy_id = await self._get_available_proxy(
                exclude_ids=[current_proxy_id] if current_proxy_id else [],
            )

            if not new_proxy_id:
                logger.warning("No available proxy for reconnection", account_id=str(self._account_id))
                return False

            await self._assign_proxy_to_account(new_proxy_id)

            # Disconnect old client
            if self._client:
                try:
                    await self._client.disconnect()
                except Exception:
                    pass

            # Reconnect with new proxy
            proxy_config = await self._get_proxy_config(new_proxy_id)
            await self._client.connect()

            logger.info(
                "Runtime proxy reconnection successful",
                account_id=str(self._account_id),
                new_proxy_id=str(new_proxy_id),
            )
            return True
        except Exception as e:
            logger.error(
                "Runtime proxy reconnection failed",
                account_id=str(self._account_id),
                error=str(e),
            )
            return False

    async def start(self) -> None:
        if self._running:
            return

        # Cancel any existing loop task
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("Starting worker", account_id=str(self._account_id))

        # If account was recently active, wait a bit to avoid AuthKeyDuplicatedError
        # This happens when bot restarts and old connection hasn't timed out yet
        if self._account.last_activity:
            from datetime import datetime, timedelta
            time_since_activity = datetime.utcnow() - self._account.last_activity.replace(tzinfo=None)
            if time_since_activity < timedelta(seconds=30):
                wait_time = 30 - time_since_activity.total_seconds()
                logger.info(
                    "Account was recently active, waiting before reconnect",
                    account_id=str(self._account_id),
                    wait_seconds=round(wait_time, 1),
                )
                await asyncio.sleep(wait_time)

        # Track failed proxies for retry logic
        failed_proxy_ids: list[UUID] = []
        max_proxy_retries = 3
        current_proxy_id = self._account.proxy_id

        # Get API credentials from TelegramApp (if assigned)
        api_id, api_hash = await self._get_api_credentials()

        for attempt in range(max_proxy_retries + 1):
            try:
                # Proxy is REQUIRED for security - no direct connections allowed
                if not current_proxy_id:
                    raise ProxyRequiredError(
                        account_id=str(self._account_id),
                        context="account has no proxy_id assigned"
                    )

                proxy_config = await self._get_proxy_config(current_proxy_id)
                if not proxy_config:
                    raise ProxyRequiredError(
                        account_id=str(self._account_id),
                        context=f"proxy {current_proxy_id} not found in database"
                    )

                logger.debug(
                    "Using proxy",
                    account_id=str(self._account_id),
                    proxy_id=str(current_proxy_id),
                    attempt=attempt + 1,
                )

                logger.debug("Creating TelegramWorkerClient", account_id=str(self._account_id))
                self._client = TelegramWorkerClient(
                    account_id=str(self._account_id),
                    session_data=self._account.session_data,
                    proxy_config=proxy_config,
                    api_id=api_id,
                    api_hash=api_hash,
                )
                logger.debug("Connecting to Telegram", account_id=str(self._account_id))
                await self._client.connect()
                logger.debug("Registering message handler", account_id=str(self._account_id))
                self._client.on_message(self._handle_incoming_message)

                logger.debug("Getting session for activate", account_id=str(self._account_id))
                # Mark account active
                async with self._get_session() as session:
                    logger.debug("Getting account service", account_id=str(self._account_id))
                    service = await self._get_account_service(session)
                    logger.debug("Calling activate_account", account_id=str(self._account_id))
                    await service.activate_account(self._account_id)
                    logger.debug("Committing session", account_id=str(self._account_id))
                    await session.commit()

                self._running = True

                # Initialize warmup manager
                await self._initialize_warmup()

                self._task = asyncio.create_task(self._run_loop())

                logger.info(
                    "Worker started",
                    account_id=str(self._account_id),
                    proxy_id=str(current_proxy_id) if current_proxy_id else None,
                    is_warmup=self._warmup_manager.is_warmup_active if self._warmup_manager else False,
                )
                return  # Success - exit the retry loop

            except TelegramAuthError as e:
                # Auth errors are not proxy-related, don't retry with different proxy
                error_str = str(e)
                async with self._get_session() as session:
                    service = await self._get_account_service(session)
                    # set_account_error already sets status to ERROR
                    await service.set_account_error(self._account_id, error_str)
                    await session.commit()

                    # Log warning for auth key issues
                    if "AuthKeyDuplicated" in error_str or "session" in error_str.lower():
                        logger.warning(
                            "Account disabled due to auth error - needs re-login",
                            account_id=str(self._account_id),
                            error=error_str,
                        )
                raise

            except (OSError, ConnectionError, TimeoutError) as e:
                # Connection errors - likely proxy issue, try another proxy
                error_msg = str(e)
                logger.warning(
                    "Proxy connection failed",
                    account_id=str(self._account_id),
                    proxy_id=str(current_proxy_id) if current_proxy_id else None,
                    error=error_msg,
                    attempt=attempt + 1,
                )

                # Mark current proxy as failed
                if current_proxy_id:
                    await self._mark_proxy_failed(current_proxy_id, error_msg)
                    failed_proxy_ids.append(current_proxy_id)

                # Disconnect the failed client
                if self._client:
                    try:
                        await self._client.disconnect()
                    except Exception:
                        pass
                    self._client = None

                # Try to find another available proxy
                if attempt < max_proxy_retries:
                    new_proxy_id = await self._get_available_proxy(exclude_ids=failed_proxy_ids)

                    if new_proxy_id:
                        logger.info(
                            "Retrying with different proxy",
                            account_id=str(self._account_id),
                            old_proxy_id=str(current_proxy_id) if current_proxy_id else None,
                            new_proxy_id=str(new_proxy_id),
                        )
                        await self._assign_proxy_to_account(new_proxy_id)
                        current_proxy_id = new_proxy_id
                        continue
                    else:
                        logger.warning(
                            "No more available proxies to try",
                            account_id=str(self._account_id),
                            failed_proxies=len(failed_proxy_ids),
                        )

                # All retries exhausted
                async with self._get_session() as session:
                    service = await self._get_account_service(session)
                    await service.set_account_error(
                        self._account_id,
                        f"Proxy connection failed after {attempt + 1} attempts: {error_msg}"
                    )
                    await session.commit()
                raise TelegramAuthError(f"All proxy connections failed: {error_msg}")

            except Exception as e:
                # Other errors - check if it's a proxy-related error
                error_msg = str(e).lower()
                is_proxy_error = any(keyword in error_msg for keyword in [
                    "proxy", "connection", "timeout", "refused", "reset",
                    "network", "unreachable", "connect", "socket"
                ])

                if is_proxy_error and current_proxy_id and attempt < max_proxy_retries:
                    logger.warning(
                        "Possible proxy error, trying another proxy",
                        account_id=str(self._account_id),
                        proxy_id=str(current_proxy_id),
                        error=str(e),
                        attempt=attempt + 1,
                    )

                    await self._mark_proxy_failed(current_proxy_id, str(e))
                    failed_proxy_ids.append(current_proxy_id)

                    if self._client:
                        try:
                            await self._client.disconnect()
                        except Exception:
                            pass
                        self._client = None

                    new_proxy_id = await self._get_available_proxy(exclude_ids=failed_proxy_ids)
                    if new_proxy_id:
                        await self._assign_proxy_to_account(new_proxy_id)
                        current_proxy_id = new_proxy_id
                        continue

                # Not a proxy error or no more proxies - fail
                async with self._get_session() as session:
                    service = await self._get_account_service(session)
                    await service.set_account_error(self._account_id, str(e))
                    await session.commit()
                raise

    async def stop(self) -> None:
        if not self._running:
            return

        logger.info("Stopping worker", account_id=str(self._account_id))
        self._running = False

        # Cancel message batcher first to stop new tasks
        self._message_batcher.cancel_all()

        # Cancel main loop task
        if self._task:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._task = None

        # Cancel pending tasks
        for task in list(self._pending_tasks):
            task.cancel()
        if self._pending_tasks:
            await asyncio.gather(*self._pending_tasks, return_exceptions=True)
        self._pending_tasks.clear()

        # Disconnect Telegram client properly
        if self._client:
            try:
                await asyncio.wait_for(self._client.disconnect(), timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception) as e:
                logger.debug("Error disconnecting client", error=str(e))
            self._client = None

        # Clear dialogue locks to prevent memory leak
        self._dialogue_locks.clear()

        # Pause account in DB
        try:
            async with self._get_session() as session:
                service = await self._get_account_service(session)
                await service.pause_account(self._account_id)
                await session.commit()
        except Exception as e:
            logger.error("Error updating account status on stop", error=str(e))

        logger.info("Worker stopped", account_id=str(self._account_id))

    async def health_check(self) -> bool:
        if not self._running or not self._client:
            return False
        try:
            if not self._client.connected:
                return False
            if self._task is None or self._task.done():
                return False
            self._last_health_check = datetime.utcnow()
            return True
        except Exception as e:
            logger.error("Health check failed", account_id=str(self._account_id), error=str(e))
            return False

    async def queue_first_message(
        self,
        target_id: UUID,
        telegram_user_id: int = 0,
        telegram_username: Optional[str] = None,
        campaign_id: UUID | None = None,
    ) -> None:
        # campaign_id is required, but keep default for backward compatibility
        if campaign_id is None:
            raise ValueError("campaign_id is required")
        await self._message_queue.put(
            {
                "type": "first_message",
                "target_id": target_id,
                "telegram_user_id": int(telegram_user_id or 0),
                "telegram_username": telegram_username,
                "campaign_id": campaign_id,
            }
        )

    async def _run_loop(self) -> None:
        import random

        while self._running:
            try:
                # Refresh account snapshot
                async with self._get_session() as session:
                    account_repo = PostgresAccountRepository(session)
                    fresh = await account_repo.get_by_id(self._account_id)
                    if fresh:
                        self._account = fresh

                # Check if account is in sleep period (anti-detection)
                if self._account.schedule.is_sleeping(
                    datetime.utcnow(),
                    account_id=str(self._account_id),
                ):
                    sleep_start, sleep_end = self._account.schedule.get_sleep_window(
                        str(self._account_id)
                    )
                    logger.debug(
                        "Account sleeping",
                        account_id=str(self._account_id),
                        sleep_window=f"{sleep_start}:00-{sleep_end}:00",
                    )
                    # Sleep for 5-15 minutes before checking again
                    await asyncio.sleep(random.uniform(300, 900))
                    continue

                # Run warmup cycle if applicable
                await self._run_warmup_cycle()

                # Check if warmup allows outreach
                if self._can_do_outreach():
                    await self._process_message_queue()
                    await self._process_pending_dialogues()
                else:
                    # In warmup mode without outreach capability - only process incoming
                    # Incoming messages are handled by callback, no action needed here
                    logger.debug(
                        "Account in warmup, skipping outreach",
                        account_id=str(self._account_id),
                        warmup_stage=self._warmup_manager.warmup_stage if self._warmup_manager else None,
                    )

                # Random loop interval (8-15 seconds instead of fixed 10)
                await asyncio.sleep(random.uniform(8, 15))

            except asyncio.CancelledError:
                break
            except (OSError, ConnectionError, TimeoutError) as e:
                # Proxy/network error during runtime — attempt reconnection
                logger.warning(
                    "Network error in worker loop, attempting proxy reconnection",
                    account_id=str(self._account_id),
                    error=str(e),
                )
                reconnected = await self._try_reconnect_with_new_proxy()
                if not reconnected:
                    logger.error(
                        "Proxy reconnection failed, stopping worker",
                        account_id=str(self._account_id),
                    )
                    break
                await asyncio.sleep(random.uniform(5, 10))
            except Exception as e:
                error_str = str(e).lower()
                proxy_keywords = ("proxy", "connection", "timeout", "refused",
                                  "reset", "network", "unreachable", "socket")
                if any(kw in error_str for kw in proxy_keywords):
                    logger.warning(
                        "Possible proxy error in worker loop, attempting reconnection",
                        account_id=str(self._account_id),
                        error=str(e),
                    )
                    reconnected = await self._try_reconnect_with_new_proxy()
                    if not reconnected:
                        logger.error(
                            "Proxy reconnection failed, stopping worker",
                            account_id=str(self._account_id),
                        )
                        break
                    await asyncio.sleep(random.uniform(5, 10))
                else:
                    logger.error("Worker loop error", account_id=str(self._account_id), error=str(e))
                    # Random error sleep (25-40 seconds instead of fixed 30)
                    await asyncio.sleep(random.uniform(25, 40))

    async def _run_warmup_cycle(self) -> None:
        """Run warmup cycle if account is in warmup mode."""
        if not self._warmup_manager:
            return

        try:
            # Refresh warmup state periodically
            await self._warmup_manager.refresh_warmup_state()

            if self._warmup_manager.is_warmup_active:
                warmup_executed = await self._warmup_manager.run_warmup_cycle()
                if warmup_executed:
                    logger.debug(
                        "Warmup cycle completed",
                        account_id=str(self._account_id),
                        warmup_info=self._warmup_manager.get_warmup_info(),
                    )
        except Exception as e:
            logger.error(
                "Error in warmup cycle",
                account_id=str(self._account_id),
                error=str(e),
            )

    async def _process_message_queue(self) -> None:
        while not self._message_queue.empty():
            try:
                task_data = self._message_queue.get_nowait()

                if task_data.get("type") == "first_message":
                    task = asyncio.create_task(
                        self._send_first_message(
                            target_id=task_data["target_id"],
                            telegram_user_id=task_data.get("telegram_user_id", 0),
                            telegram_username=task_data.get("telegram_username"),
                            campaign_id=task_data["campaign_id"],
                        )
                    )
                    self._pending_tasks.add(task)
                    task.add_done_callback(self._pending_tasks.discard)

            except asyncio.QueueEmpty:
                break
            except Exception as e:
                logger.error("Error processing queue", error=str(e))

    async def _process_pending_dialogues(self) -> None:
        async with self._get_session() as session:
            dialogue_service = await self._get_dialogue_service(session)
            pending = await dialogue_service.list_pending_dialogues(account_id=self._account_id, limit=5)

            for dialogue in pending:
                if not self._account.can_send_message():
                    break

                # Use per-dialogue lock to prevent concurrent modifications
                lock = self._get_dialogue_lock(dialogue.id)
                if lock.locked():
                    # Skip this dialogue if it's being processed (e.g., by incoming message handler)
                    logger.debug("Dialogue locked, skipping follow-up", dialogue_id=str(dialogue.id))
                    continue

                async with lock:
                    try:
                        await self._send_follow_up(dialogue, session)
                    except TelegramFloodError as e:
                        logger.warning("Flood wait", account_id=str(self._account_id), seconds=e.wait_seconds)
                        await asyncio.sleep(e.wait_seconds)
                        break
                    except Exception as e:
                        logger.error("Error sending follow-up", dialogue_id=str(dialogue.id), error=str(e))

    async def _send_first_message(
        self,
        target_id: UUID,
        telegram_user_id: int,
        telegram_username: Optional[str],
        campaign_id: UUID,
    ) -> None:
        dialogue: Optional[Dialogue] = None

        async with self._get_session() as session:
            try:
                dialogue_service = await self._get_dialogue_service(session)
                account_service = await self._get_account_service(session)

                dialogue, message_text = await dialogue_service.start_dialogue(
                    account_id=self._account_id,
                    campaign_id=campaign_id,
                    target_id=target_id,
                    telegram_user_id=telegram_user_id or None,
                    telegram_username=telegram_username,
                )

                await self._humanizer.random_delay(30, 120)

                recipient = telegram_user_id if telegram_user_id else telegram_username
                if not recipient:
                    raise ValueError("Target has neither telegram_user_id nor telegram_username")

                if self._client:
                    # Split by ||| for multiple messages
                    parts = [p.strip() for p in message_text.split("|||") if p.strip()]
                    if not parts:
                        parts = [message_text]

                    # Calculate typing time for each part
                    typing_times = [self._humanizer.get_typing_duration(p) for p in parts]

                    # Send messages with typing simulation
                    sent_ids = await self._client.send_messages_natural(
                        user_id=recipient,
                        messages=parts,
                        typing_times=typing_times,
                        pause_between=1.5,
                    )

                    msg_id = sent_ids[-1] if sent_ids else None

                    if sent_ids:
                        # Persist telegram message id on the last outgoing message
                        try:
                            dlg = await dialogue_service.get_dialogue(dialogue.id)
                            for m in reversed(dlg.messages):
                                if m.role == MessageRole.ACCOUNT and m.telegram_message_id is None:
                                    m.telegram_message_id = msg_id
                                    break
                            await dialogue_service.update_dialogue(dlg)
                        except Exception:
                            logger.debug("Failed to persist telegram_message_id", exc_info=True)

                        await account_service.increment_conversation_count(self._account_id)

                await session.commit()

                logger.info("First message sent", account_id=str(self._account_id), target_id=str(target_id))

            except TelegramPrivacyError:
                # User has privacy settings, mark target + dialogue as failed
                try:
                    target_repo = PostgresUserTargetRepository(session)
                    target = await target_repo.get_by_id(target_id)
                    if target:
                        target.mark_failed("privacy_settings")
                        await target_repo.save(target)

                    if dialogue:
                        await dialogue_service.mark_dialogue_failed(dialogue.id, "privacy_settings")

                    await session.commit()
                except Exception:
                    await session.rollback()

            except Exception as e:
                logger.error(
                    "Error sending first message",
                    account_id=str(self._account_id),
                    target_id=str(target_id),
                    error=str(e),
                )
                await session.rollback()

    async def _send_follow_up(self, dialogue: Dialogue, session: AsyncSession) -> None:
        dialogue_service = await self._get_dialogue_service(session)
        account_service = await self._get_account_service(session)

        message_text = await dialogue_service.generate_follow_up(dialogue.id)
        if not message_text:
            return

        await self._humanizer.random_delay(5, 30)

        recipient = dialogue.telegram_user_id or dialogue.telegram_username
        if not recipient:
            logger.warning("Dialogue has no recipient identifiers", dialogue_id=str(dialogue.id))
            return

        if self._client:
            # Split by ||| for multiple messages
            parts = [p.strip() for p in message_text.split("|||") if p.strip()]
            if not parts:
                parts = [message_text]

            # Calculate typing time for each part
            typing_times = [self._humanizer.get_typing_duration(p) for p in parts]

            # Send messages with typing simulation
            sent_ids = await self._client.send_messages_natural(
                user_id=recipient,
                messages=parts,
                typing_times=typing_times,
                pause_between=1.5,
            )

            msg_id = sent_ids[-1] if sent_ids else None

            if sent_ids:
                try:
                    dlg = await dialogue_service.get_dialogue(dialogue.id)
                    for m in reversed(dlg.messages):
                        if m.role == MessageRole.ACCOUNT and m.telegram_message_id is None:
                            m.telegram_message_id = msg_id
                            break
                    await dialogue_service.update_dialogue(dlg)
                except Exception:
                    logger.debug("Failed to persist telegram_message_id", exc_info=True)

                await account_service.increment_message_count(self._account_id)

        await session.commit()

    async def _handle_incoming_message(
        self,
        user_id: int,
        username: Optional[str],
        text: str,
        message_id: int,
    ) -> None:
        logger.debug(
            "Incoming message",
            account_id=str(self._account_id),
            user_id=user_id,
            text_preview=(text[:50] if text else ""),
        )

        # Check if account can respond (warmup accounts should not respond)
        if not self._can_respond_to_messages():
            logger.debug(
                "Account in warmup, ignoring incoming message",
                account_id=str(self._account_id),
                user_id=user_id,
            )
            return

        # First, find the dialogue to get its ID for locking
        dialogue_id: Optional[UUID] = None
        try:
            async with self._get_session() as session:
                dialogue_repo = PostgresDialogueRepository(session)
                dialogue = await dialogue_repo.get_by_account_and_user(
                    self._account_id, user_id, username
                )
                if dialogue:
                    dialogue_id = dialogue.id
        except Exception as e:
            logger.error("Error finding dialogue", error=str(e))
            return

        if not dialogue_id:
            logger.debug("No dialogue found for user", user_id=user_id)
            return

        # Use message batcher to collect multiple messages before responding
        # This handles the case when user sends messages one by one
        async def process_batched_messages(combined_text: str, message_ids: list[int]) -> None:
            await self._process_batched_incoming(
                user_id=user_id,
                username=username,
                text=combined_text,
                message_ids=message_ids,
                dialogue_id=dialogue_id,
            )

        await self._message_batcher.add_message(
            account_id=self._account_id,
            user_id=user_id,
            text=text or "",
            message_id=message_id,
            on_ready=process_batched_messages,
        )

    async def _process_batched_incoming(
        self,
        user_id: int,
        username: Optional[str],
        text: str,
        message_ids: list[int],
        dialogue_id: UUID,
    ) -> None:
        """Process batched incoming messages after user stops typing."""
        # Use per-dialogue lock to prevent concurrent modifications
        lock = self._get_dialogue_lock(dialogue_id)
        async with lock:
            try:
                async with self._get_session() as session:
                    dialogue_service = await self._get_dialogue_service(session)
                    account_service = await self._get_account_service(session)

                    # Use the last message_id for tracking
                    last_message_id = message_ids[-1] if message_ids else None

                    processed = await dialogue_service.process_incoming_message(
                        account_id=self._account_id,
                        telegram_user_id=user_id,
                        text=text,
                        telegram_message_id=last_message_id,
                        telegram_username=username,
                    )

                    if not processed:
                        return

                    dialogue, response_text = processed
                    if not response_text:
                        return

                    if self._client:
                        # Mark all messages as read (shows "seen" status)
                        if last_message_id:
                            await self._client.mark_as_read(user_id, last_message_id)

                        # Human-like delay based on message complexity (reading time)
                        await asyncio.sleep(self._humanizer.get_response_delay(len(text or "")))

                        # Split by ||| for multiple messages
                        parts = [p.strip() for p in response_text.split("|||") if p.strip()]
                        if not parts:
                            parts = [response_text]

                        # Calculate typing time for each part
                        typing_times = [self._humanizer.get_typing_duration(p) for p in parts]

                        # Send messages with typing simulation
                        sent_ids = await self._client.send_messages_natural(
                            user_id=user_id,
                            messages=parts,
                            typing_times=typing_times,
                            pause_between=1.5,
                        )

                        resp_id = sent_ids[-1] if sent_ids else None

                        if sent_ids:
                            await account_service.increment_message_count(self._account_id)

                            # Update telegram_message_id in a separate session
                            try:
                                async with self._get_session() as msg_session:
                                    msg_dialogue_service = await self._get_dialogue_service(msg_session)
                                    dlg = await msg_dialogue_service.get_dialogue(dialogue.id)
                                    for m in reversed(dlg.messages):
                                        if m.role == MessageRole.ACCOUNT and m.telegram_message_id is None:
                                            m.telegram_message_id = resp_id
                                            break
                                    await msg_dialogue_service.update_dialogue(dlg)
                                    await msg_session.commit()
                            except Exception:
                                logger.debug("Failed to persist telegram_message_id", exc_info=True)

                    await session.commit()

            except TelegramFloodError as e:
                logger.warning(
                    "Flood wait on incoming handling",
                    account_id=str(self._account_id),
                    seconds=e.wait_seconds,
                )
                await asyncio.sleep(e.wait_seconds)

            except Exception as e:
                logger.error(
                    "Error handling batched incoming message",
                    account_id=str(self._account_id),
                    user_id=user_id,
                    error=str(e),
                )
