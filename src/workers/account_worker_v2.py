"""
Account worker v2.

Improved worker with:
- Redis task queue integration
- Sequential task processing (1 at a time)
- Proper rate limiting
- Session-per-operation for DB
- Robust error handling
"""

import asyncio
from datetime import datetime
from typing import Optional
from uuid import UUID

import structlog

from src.application.services import AccountService, DialogueService
from src.domain.entities import Account, DialogueStatus
from src.domain.exceptions import (
    ProxyRequiredError,
    TelegramAuthError,
    TelegramFloodError,
    TelegramPrivacyError,
)
from src.infrastructure.ai import OpenAIProvider
from src.infrastructure.database import get_session
from src.infrastructure.database.repositories import (
    PostgresAccountRepository,
    PostgresCampaignRepository,
    PostgresDialogueRepository,
    PostgresProxyRepository,
    PostgresUserTargetRepository,
)
from src.infrastructure.telegram import TelegramWorkerClient
from src.utils.humanizer import Humanizer, get_humanizer

from .task_queue import Task, TaskQueue, TaskType, get_task_queue
from .warmup_worker import AccountWarmupManager
from .background_activity import BackgroundActivityManager, get_randomized_schedule_offset

logger = structlog.get_logger(__name__)


class AccountWorkerV2:
    """
    Worker for a single Telegram account with queue-based task processing.
    
    Features:
    - Sequential task processing from Redis queue
    - Rate limiting: configurable delay between messages
    - Automatic retry on transient failures
    - Proper session management for DB operations
    - Graceful shutdown
    """
    
    def __init__(
        self,
        account: Account,
        ai_provider: OpenAIProvider,
        task_queue: Optional[TaskQueue] = None,
        humanizer: Optional[Humanizer] = None,
        min_delay_between_messages: float = 30.0,
        max_delay_between_messages: float = 120.0,
    ):
        self.account = account
        self.account_id = account.id
        self.ai_provider = ai_provider
        self.humanizer = humanizer or get_humanizer()
        
        self._task_queue = task_queue
        self._client: Optional[TelegramWorkerClient] = None
        self._running = False
        self._task_loop: Optional[asyncio.Task] = None
        self._listener_task: Optional[asyncio.Task] = None
        
        # Rate limiting
        self._min_delay = min_delay_between_messages
        self._max_delay = max_delay_between_messages
        self._last_message_time: Optional[datetime] = None

        # Stats
        self._messages_sent = 0
        self._errors = 0

        # Warmup manager - initialized after client connection
        self._warmup_manager: Optional[AccountWarmupManager] = None
        self._warmup_initialized = False

        # Background activity manager - runs parallel human-like activities
        self._background_activity: Optional[BackgroundActivityManager] = None

        # Account-specific timing offset for desynchronization
        # This prevents all accounts from sending messages at the same time
        self._timing_offset = get_randomized_schedule_offset(
            account_id=account.id,
            base_interval=1.0,  # Base multiplier
            variance=0.3,  # +/- 30% variance per account
        )
    
    @property
    def running(self) -> bool:
        return self._running
    
    @property
    def stats(self) -> dict:
        warmup_info = self._warmup_manager.get_warmup_info() if self._warmup_manager else {"is_warmup": False}
        bg_activity_info = self._background_activity.stats if self._background_activity else {"running": False}
        return {
            "account_id": str(self.account_id),
            "running": self._running,
            "messages_sent": self._messages_sent,
            "errors": self._errors,
            "last_message": self._last_message_time.isoformat() if self._last_message_time else None,
            "warmup": warmup_info,
            "background_activity": bg_activity_info,
            "timing_offset": self._timing_offset,
        }

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

    async def _initialize_warmup(self) -> None:
        """Initialize warmup manager for the account."""
        if self._warmup_initialized or not self._client:
            return

        try:
            self._warmup_manager = AccountWarmupManager(
                account_id=self.account_id,
                client=self._client.client,  # Pass the underlying Telethon client
            )
            is_warmup = await self._warmup_manager.initialize()
            self._warmup_initialized = True

            if is_warmup:
                logger.info(
                    "Account in warmup mode",
                    account_id=str(self.account_id),
                    stage=self._warmup_manager.warmup_stage,
                    can_outreach=self._warmup_manager.can_do_outreach(),
                )
        except Exception as e:
            logger.error(
                "Failed to initialize warmup manager",
                account_id=str(self.account_id),
                error=str(e),
            )
            self._warmup_manager = None

    async def _initialize_background_activity(self) -> None:
        """Initialize background activity manager for human-like behavior."""
        if self._background_activity or not self._client:
            return

        try:
            # Use account_id as seed for consistent but unique timing
            seed = int(str(self.account_id).replace("-", "")[:8], 16)

            self._background_activity = BackgroundActivityManager(
                account_id=self.account_id,
                client=self._client.client,  # Underlying Telethon client
                # Randomize intervals per account for natural behavior
                min_activity_interval=90.0 * self._timing_offset,   # ~1.5-3 min
                max_activity_interval=420.0 * self._timing_offset,  # ~7-14 min
                min_online_duration=45.0 * self._timing_offset,     # ~45s-90s
                max_online_duration=240.0 * self._timing_offset,    # ~4-8 min
                min_offline_duration=180.0 * self._timing_offset,   # ~3-6 min
                max_offline_duration=1200.0 * self._timing_offset,  # ~20-40 min
                timing_offset_seed=seed,
            )

            # Start background activity loop
            await self._background_activity.start()

            logger.info(
                "Background activity initialized",
                account_id=str(self.account_id),
                timing_offset=f"{self._timing_offset:.2f}x",
            )
        except Exception as e:
            logger.error(
                "Failed to initialize background activity",
                account_id=str(self.account_id),
                error=str(e),
            )
            self._background_activity = None

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
                        account_id=str(self.account_id),
                        warmup_info=self._warmup_manager.get_warmup_info(),
                    )
        except Exception as e:
            logger.error(
                "Error in warmup cycle",
                account_id=str(self.account_id),
                error=str(e),
            )
    
    async def start(self) -> None:
        """Start the worker."""
        if self._running:
            return
        
        logger.info("Starting worker v2", account_id=str(self.account_id))
        
        # Get task queue
        if self._task_queue is None:
            self._task_queue = await get_task_queue()
        
        try:
            # Get proxy config - REQUIRED for security
            if not self.account.proxy_id:
                raise ProxyRequiredError(
                    account_id=str(self.account_id),
                    context="account has no proxy_id assigned"
                )

            proxy_config = await self._get_proxy_config()
            if not proxy_config:
                raise ProxyRequiredError(
                    account_id=str(self.account_id),
                    context="proxy not found in database"
                )

            # Connect Telegram client
            self._client = TelegramWorkerClient(
                account_id=str(self.account_id),
                session_data=self.account.session_data,
                proxy=proxy_config,
            )
            await self._client.connect()
            
            # Set up message handler
            self._client.on_message(self._handle_incoming_message)
            
            # Update account status
            await self._activate_account()

            self._running = True

            # Initialize warmup manager
            await self._initialize_warmup()

            # Initialize background activity (human-like behavior)
            await self._initialize_background_activity()

            # Start task processing loop
            self._task_loop = asyncio.create_task(self._process_tasks_loop())

            logger.info(
                "Worker v2 started",
                account_id=str(self.account_id),
                phone=self.account.phone,
                is_warmup=self._warmup_manager.is_warmup_active if self._warmup_manager else False,
                bg_activity=self._background_activity.is_running if self._background_activity else False,
            )
            
        except TelegramAuthError as e:
            await self._set_account_error(str(e))
            raise
        except Exception as e:
            logger.error(
                "Failed to start worker",
                account_id=str(self.account_id),
                error=str(e),
            )
            raise
    
    async def stop(self) -> None:
        """Stop the worker gracefully."""
        if not self._running:
            return

        logger.info("Stopping worker v2", account_id=str(self.account_id))

        self._running = False

        # Stop background activity first
        if self._background_activity:
            await self._background_activity.stop()

        # Cancel task loop
        if self._task_loop:
            self._task_loop.cancel()
            try:
                await self._task_loop
            except asyncio.CancelledError:
                pass

        # Disconnect Telegram
        if self._client:
            await self._client.disconnect()

        # Update account status
        await self._pause_account()

        logger.info("Worker v2 stopped", account_id=str(self.account_id))
    
    async def _process_tasks_loop(self) -> None:
        """Main loop: take tasks from queue and process sequentially."""
        account_id_str = str(self.account_id)

        while self._running:
            try:
                # Run warmup cycle if applicable
                await self._run_warmup_cycle()

                # Check schedule
                if not self.account.schedule.is_active_now(datetime.utcnow()):
                    logger.debug("Outside schedule, sleeping", account_id=account_id_str)
                    await asyncio.sleep(60)
                    continue

                # Check rate limit
                if not self.account.can_send_message():
                    logger.debug("Rate limit reached, sleeping", account_id=account_id_str)
                    await asyncio.sleep(60)
                    continue

                # Check if warmup allows outreach
                if not self._can_do_outreach():
                    logger.debug(
                        "Account in warmup, skipping outreach tasks",
                        account_id=account_id_str,
                        warmup_stage=self._warmup_manager.warmup_stage if self._warmup_manager else None,
                    )
                    await asyncio.sleep(30)
                    continue

                # Get task from queue (blocking with timeout)
                task = await self._task_queue.dequeue(account_id_str, timeout=5)

                if task is None:
                    # No tasks, continue loop
                    continue

                # Process task
                logger.info(
                    "Processing task",
                    task_id=task.id,
                    task_type=task.task_type.value,
                    account_id=account_id_str,
                )

                success = await self._process_task(task)

                if success:
                    await self._task_queue.complete(task)
                    self._messages_sent += 1
                    self._last_message_time = datetime.utcnow()

                    # Rate limiting delay with per-account variance
                    # Each account has its own timing offset so they don't sync up
                    base_delay = self.humanizer.get_random_delay(
                        self._min_delay,
                        self._max_delay,
                    )
                    # Apply account-specific timing multiplier
                    delay = base_delay * self._timing_offset
                    logger.debug(f"Rate limit delay: {delay:.1f}s (offset: {self._timing_offset:.2f}x)")
                    await asyncio.sleep(delay)
                else:
                    self._errors += 1
                    # Task will be retried by fail() method

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "Task loop error",
                    account_id=account_id_str,
                    error=str(e),
                )
                await asyncio.sleep(10)
    
    async def _process_task(self, task: Task) -> bool:
        """
        Process a single task.
        
        Returns True on success, False on failure.
        """
        try:
            if task.task_type == TaskType.SEND_FIRST_MESSAGE:
                return await self._send_first_message(task)
            elif task.task_type == TaskType.SEND_RESPONSE:
                return await self._send_response_task(task)
            elif task.task_type == TaskType.SEND_FOLLOW_UP:
                return await self._send_follow_up(task)
            else:
                logger.warning(f"Unknown task type: {task.task_type}")
                return False
                
        except TelegramFloodError as e:
            logger.warning(
                "Flood wait",
                seconds=e.wait_seconds,
                task_id=task.id,
            )
            await self._task_queue.fail(task, f"FloodWait: {e.wait_seconds}s", retry=True)
            await asyncio.sleep(e.wait_seconds)
            return False
            
        except TelegramPrivacyError:
            logger.warning(
                "Privacy restricted",
                task_id=task.id,
                recipient=task.recipient,
            )
            await self._task_queue.fail(task, "Privacy restricted", retry=False)
            return False
            
        except TelegramAuthError as e:
            logger.error(
                "Auth error",
                task_id=task.id,
                error=str(e),
            )
            await self._set_account_error(str(e))
            await self._task_queue.fail(task, f"Auth error: {e}", retry=False)
            self._running = False  # Stop worker
            return False
            
        except Exception as e:
            logger.error(
                "Task processing error",
                task_id=task.id,
                error=str(e),
            )
            await self._task_queue.fail(task, str(e), retry=True)
            return False
    
    async def _send_first_message(self, task: Task) -> bool:
        """Send first message to target."""
        if not self._client:
            return False
        
        if not self.account.can_start_new_conversation():
            logger.debug("Cannot start new conversation, daily limit reached")
            # Re-queue for later
            await self._task_queue.fail(task, "Daily limit reached", retry=True)
            return False
        
        async with get_session() as session:
            dialogue_service = self._create_dialogue_service(session)
            
            # Determine recipient
            recipient = task.recipient
            if recipient and recipient.isdigit():
                recipient = int(recipient)
            
            # Start dialogue
            dialogue, message = await dialogue_service.start_dialogue(
                account_id=self.account_id,
                campaign_id=UUID(task.campaign_id),
                target_id=UUID(task.target_id),
                telegram_user_id=recipient if isinstance(recipient, int) else None,
                telegram_username=recipient if isinstance(recipient, str) else None,
            )
            
            # Simulate typing
            await self.humanizer.simulate_typing(message)
            
            # Send message
            sent_msg = await self._client.send_message(recipient, message)
            
            # Update telegram_user_id if sent by username
            if isinstance(recipient, str) and sent_msg:
                try:
                    peer = await self._client.client.get_entity(recipient)
                    dialogue.telegram_user_id = peer.id
                    await dialogue_service.update_dialogue(dialogue)
                except Exception:
                    pass
            
            # Record stats
            await self._record_new_conversation()
            
            logger.info(
                "First message sent",
                task_id=task.id,
                recipient=str(recipient),
                dialogue_id=str(dialogue.id),
            )
            
            return True
    
    async def _send_response_task(self, task: Task) -> bool:
        """Send response to user message (used when message comes in)."""
        # This is handled by _handle_incoming_message
        return True
    
    async def _send_follow_up(self, task: Task) -> bool:
        """Send follow-up message to continue dialogue."""
        if not self._client or not task.dialogue_id:
            return False
        
        async with get_session() as session:
            dialogue_service = self._create_dialogue_service(session)
            
            # Get dialogue
            dialogue_id = UUID(task.dialogue_id)
            response = await dialogue_service.generate_follow_up(dialogue_id)
            
            if not response:
                logger.debug("No follow-up needed", dialogue_id=task.dialogue_id)
                return True
            
            # Get dialogue for telegram_user_id
            dialogue = await PostgresDialogueRepository(session).get_by_id(dialogue_id)
            if not dialogue:
                return False
            
            # Simulate typing
            await self.humanizer.simulate_typing(response)
            
            # Send
            await self._client.send_message(dialogue.telegram_user_id, response)
            
            # Record stats
            await self._record_message_sent()
            
            logger.info(
                "Follow-up sent",
                task_id=task.id,
                dialogue_id=task.dialogue_id,
            )
            
            return True
    
    async def _handle_incoming_message(
        self,
        user_id: int,
        username: Optional[str],
        text: str,
        message_id: int,
    ) -> None:
        """Handle incoming message from user."""
        logger.info(
            "Incoming message",
            account_id=str(self.account_id),
            user_id=user_id,
            text=text[:50] + "..." if len(text) > 50 else text,
        )

        # Check if account can respond (warmup accounts should not respond)
        if not self._can_respond_to_messages():
            logger.debug(
                "Account in warmup, ignoring incoming message",
                account_id=str(self.account_id),
                user_id=user_id,
            )
            return

        try:
            async with get_session() as session:
                dialogue_service = self._create_dialogue_service(session)
                
                result = await dialogue_service.process_incoming_message(
                    account_id=self.account_id,
                    telegram_user_id=user_id,
                    text=text,
                    telegram_message_id=message_id,
                    telegram_username=username,
                )
                
                if result:
                    dialogue, response = result

                    # Simulate typing
                    await self.humanizer.simulate_typing(response)

                    # Send response
                    await self._client.send_message(user_id, response)

                    # Record stats (use response counter, not outreach counter)
                    await self._record_response_sent()
                    self._messages_sent += 1
                    self._last_message_time = datetime.utcnow()
                    
                    logger.info(
                        "Response sent",
                        dialogue_id=str(dialogue.id),
                        user_id=user_id,
                    )
                    
        except Exception as e:
            logger.error(
                "Failed to handle incoming message",
                account_id=str(self.account_id),
                user_id=user_id,
                error=str(e),
            )
    
    # =========================================================================
    # Helper methods
    # =========================================================================
    
    def _create_dialogue_service(self, session) -> DialogueService:
        """Create dialogue service with given session."""
        return DialogueService(
            dialogue_repo=PostgresDialogueRepository(session),
            campaign_repo=PostgresCampaignRepository(session),
            target_repo=PostgresUserTargetRepository(session),
            ai_provider=self.ai_provider,
        )
    
    async def _get_proxy_config(self) -> dict:
        """Get proxy configuration for Telethon.

        Returns:
            Proxy config dict for Telethon client.

        Raises:
            ProxyRequiredError: If proxy is not found in database.
        """
        import python_socks

        if not self.account.proxy_id:
            raise ProxyRequiredError(
                account_id=str(self.account_id),
                context="account has no proxy_id assigned"
            )

        async with get_session() as session:
            proxy_repo = PostgresProxyRepository(session)
            proxy = await proxy_repo.get_by_id(self.account.proxy_id)

            if not proxy:
                raise ProxyRequiredError(
                    account_id=str(self.account_id),
                    context=f"proxy {self.account.proxy_id} not found in database"
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
    
    async def _activate_account(self) -> None:
        """Activate account in database."""
        async with get_session() as session:
            account_repo = PostgresAccountRepository(session)
            proxy_repo = PostgresProxyRepository(session)
            service = AccountService(account_repo, proxy_repo)
            await service.activate_account(self.account_id)
    
    async def _pause_account(self) -> None:
        """Pause account in database."""
        async with get_session() as session:
            account_repo = PostgresAccountRepository(session)
            proxy_repo = PostgresProxyRepository(session)
            service = AccountService(account_repo, proxy_repo)
            await service.pause_account(self.account_id)
    
    async def _set_account_error(self, error: str) -> None:
        """Set account error in database."""
        async with get_session() as session:
            account_repo = PostgresAccountRepository(session)
            proxy_repo = PostgresProxyRepository(session)
            service = AccountService(account_repo, proxy_repo)
            await service.set_account_error(self.account_id, error)
    
    async def _record_message_sent(self) -> None:
        """Record cold outreach message sent in database."""
        async with get_session() as session:
            account_repo = PostgresAccountRepository(session)
            proxy_repo = PostgresProxyRepository(session)
            service = AccountService(account_repo, proxy_repo)
            await service.record_message_sent(self.account_id)

    async def _record_response_sent(self) -> None:
        """Record response to incoming message in database."""
        async with get_session() as session:
            account_repo = PostgresAccountRepository(session)
            proxy_repo = PostgresProxyRepository(session)
            service = AccountService(account_repo, proxy_repo)
            await service.record_response_sent(self.account_id)

    async def _record_new_conversation(self) -> None:
        """Record new conversation in database."""
        async with get_session() as session:
            account_repo = PostgresAccountRepository(session)
            proxy_repo = PostgresProxyRepository(session)
            service = AccountService(account_repo, proxy_repo)
            await service.record_new_conversation(self.account_id)
