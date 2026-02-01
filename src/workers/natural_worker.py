"""
Account worker with dialogue processing.

Features:
- Message batching (waits for user to finish)
- Read receipts + typing simulation
- Special command handling ([SEND_LINKS], [NEGATIVE_FINISH], etc)
- Message splitting by |||
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator, Callable, Optional
from uuid import UUID, uuid4

import structlog

from src.domain.entities import (
    Account, 
    AccountStatus, 
    Dialogue, 
    DialogueStatus,
    MessageRole,
)
from src.domain.exceptions import (
    TelegramAuthError,
    TelegramFloodError,
    TelegramPrivacyError,
)
from src.infrastructure.database import AsyncSession
from src.infrastructure.database.repositories import (
    PostgresAccountRepository,
    PostgresCampaignRepository,
    PostgresDialogueRepository,
    PostgresUserTargetRepository,
)
from src.infrastructure.telegram import TelegramWorkerClient
from src.infrastructure.ai import OpenAIProvider
from src.application.services.dialogue_processor import (
    DialogueProcessor,
    DialogueAction,
    MessageBatcher,
    TypingSimulator,
    ParsedResponse,
)

logger = structlog.get_logger(__name__)


class NaturalAccountWorker:
    """
    Worker with human-like behavior and command handling.
    
    Flow:
    1. Receive message(s) → batch them
    2. Mark as read → simulate reading
    3. Generate response → parse commands
    4. Type → send (split by |||)
    5. Handle action (SEND_LINKS, NEGATIVE_FINISH, etc)
    """
    
    def __init__(
        self,
        account: Account,
        session_factory: Callable[[], AsyncGenerator[AsyncSession, None]],
        ai_provider: OpenAIProvider,
    ):
        self._account = account
        self._account_id = account.id
        self._session_factory = session_factory
        
        # Components
        self._processor = DialogueProcessor(ai_provider)
        self._batcher = MessageBatcher()
        self._typing = TypingSimulator()
        
        # State
        self._client: Optional[TelegramWorkerClient] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._pending_tasks: set[asyncio.Task] = set()
        self._message_queue: asyncio.Queue = asyncio.Queue()
    
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
    
    async def start(self) -> None:
        """Start worker."""
        if self._running:
            return
        
        # Cleanup old task
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("Starting worker", account_id=str(self._account_id))
        
        try:
            self._client = TelegramWorkerClient(
                account_id=str(self._account_id),
                session_data=self._account.session_data,
            )
            await self._client.connect()
            self._client.on_message(self._on_message)
            
            async with self._get_session() as session:
                repo = PostgresAccountRepository(session)
                await repo.update_status(self._account_id, AccountStatus.ACTIVE)
                await session.commit()
            
            self._running = True
            self._task = asyncio.create_task(self._run_loop())
            
            logger.info("Worker started", account_id=str(self._account_id))
            
        except TelegramAuthError as e:
            async with self._get_session() as session:
                repo = PostgresAccountRepository(session)
                await repo.update_status(
                    self._account_id, 
                    AccountStatus.AUTH_ERROR,
                    str(e),
                )
                await session.commit()
            raise
    
    async def stop(self) -> None:
        """Stop worker."""
        if not self._running:
            return
        
        logger.info("Stopping worker", account_id=str(self._account_id))
        
        self._running = False
        self._batcher.cancel_all()
        
        if self._task:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._task = None
        
        for task in list(self._pending_tasks):
            task.cancel()
        if self._pending_tasks:
            await asyncio.gather(*self._pending_tasks, return_exceptions=True)
        self._pending_tasks.clear()
        
        if self._client:
            await self._client.disconnect()
            self._client = None
        
        try:
            async with self._get_session() as session:
                repo = PostgresAccountRepository(session)
                await repo.update_status(self._account_id, AccountStatus.PAUSED)
                await session.commit()
        except Exception as e:
            logger.error("Error on stop", error=str(e))
    
    async def health_check(self) -> bool:
        if not self._running:
            return False
        if not self._client or not self._client.connected:
            return False
        if not self._task or self._task.done():
            return False
        return True
    
    async def queue_first_message(
        self,
        target_id: UUID,
        telegram_user_id: int,
        campaign_id: UUID,
    ) -> None:
        await self._message_queue.put({
            "type": "first_message",
            "target_id": target_id,
            "telegram_user_id": telegram_user_id,
            "campaign_id": campaign_id,
        })
    
    # =========================================
    # Message Handling
    # =========================================
    
    async def _on_message(
        self,
        user_id: int,
        username: Optional[str],
        text: str,
        message_id: int,
    ) -> None:
        """Handle incoming message - add to batcher."""
        logger.debug(
            "Message received",
            account_id=str(self._account_id),
            user_id=user_id,
        )
        
        await self._batcher.add_message(
            account_id=self._account_id,
            user_id=user_id,
            text=text,
            message_id=message_id,
            on_ready=lambda combined, ids: self._process_messages(
                user_id, username, combined, ids
            ),
        )
    
    async def _process_messages(
        self,
        user_id: int,
        username: Optional[str],
        combined_text: str,
        message_ids: list[int],
    ) -> None:
        """Process batched messages."""
        try:
            async with self._get_session() as session:
                # Get dialogue
                dialogue_repo = PostgresDialogueRepository(session)
                dialogue = await dialogue_repo.get_by_account_and_user(
                    self._account_id, user_id
                )
                
                if not dialogue:
                    logger.debug("No dialogue", user_id=user_id)
                    return
                
                if dialogue.status not in (DialogueStatus.ACTIVE, DialogueStatus.INITIATED):
                    logger.debug("Dialogue not active", status=dialogue.status.value)
                    return
                
                # Get campaign
                campaign_repo = PostgresCampaignRepository(session)
                campaign = await campaign_repo.get_by_id(dialogue.campaign_id)
                
                if not campaign:
                    logger.error("No campaign", campaign_id=str(dialogue.campaign_id))
                    return
                
                # Record incoming
                dialogue.add_message(
                    message_id=uuid4(),
                    role=MessageRole.USER,
                    content=combined_text,
                    telegram_message_id=message_ids[-1] if message_ids else None,
                )
                dialogue.last_user_response_at = datetime.utcnow()
                
                if dialogue.status == DialogueStatus.INITIATED:
                    dialogue.status = DialogueStatus.ACTIVE
                
                await dialogue_repo.save(dialogue)
                await session.commit()
                
                # === NATURAL FLOW ===
                
                # 1. Mark as read + simulate reading
                if self._client and message_ids:
                    await self._client.mark_as_read(user_id, max(message_ids))
                
                reading_time = self._typing.get_reading_time(combined_text)
                await asyncio.sleep(reading_time)
                
                # 2. Generate response
                context = {
                    "temperature": campaign.ai_temperature or 0.8,
                    "max_tokens": campaign.ai_max_tokens or 300,
                    "links": campaign.goal.target_message if campaign.goal else "",
                }
                
                # Build prompt from campaign
                system_prompt = self._build_prompt(campaign)
                
                parsed = await self._processor.generate_response(
                    dialogue=dialogue,
                    user_message=combined_text,
                    system_prompt=system_prompt,
                    campaign_context=context,
                )
                
                # 3. Send messages
                await self._send_parsed_response(
                    user_id=user_id,
                    dialogue=dialogue,
                    parsed=parsed,
                    dialogue_repo=dialogue_repo,
                    session=session,
                )
                
                # 4. Handle action
                await self._handle_action(
                    dialogue=dialogue,
                    parsed=parsed,
                    campaign=campaign,
                    dialogue_repo=dialogue_repo,
                    user_id=user_id,
                )
                
                # Save
                await dialogue_repo.save(dialogue)
                
                account_repo = PostgresAccountRepository(session)
                await account_repo.increment_message_count(self._account_id)
                
                await session.commit()
                
        except TelegramFloodError as e:
            logger.warning("Flood", seconds=e.wait_seconds)
            await asyncio.sleep(e.wait_seconds)
        except TelegramPrivacyError:
            await self._mark_dialogue_failed(user_id, "privacy")
        except Exception as e:
            logger.error("Process error", error=str(e))
    
    async def _send_parsed_response(
        self,
        user_id: int,
        dialogue: Dialogue,
        parsed: ParsedResponse,
        dialogue_repo,
        session,
    ) -> None:
        """Send parsed response messages."""
        if not parsed.has_messages or not self._client:
            return
        
        for i, msg_text in enumerate(parsed.messages):
            # Typing
            typing_time = self._typing.get_typing_time(msg_text)
            await self._client.type_and_wait(user_id, typing_time)
            
            # Send
            msg_id = await self._client.send_message(user_id, msg_text)
            
            if msg_id:
                dialogue.add_message(
                    message_id=uuid4(),
                    role=MessageRole.ACCOUNT,
                    content=msg_text,
                    telegram_message_id=msg_id,
                    ai_generated=True,
                )
            
            # Pause between messages
            if i < len(parsed.messages) - 1:
                await asyncio.sleep(self._typing.get_pause_between())
    
    async def _handle_action(
        self,
        dialogue: Dialogue,
        parsed: ParsedResponse,
        campaign,
        dialogue_repo,
        user_id: int,
    ) -> None:
        """Handle special action from response."""
        
        if parsed.action == DialogueAction.SEND_LINKS:
            # Send links
            links = campaign.goal.target_message if campaign.goal else ""
            if links and self._client:
                await asyncio.sleep(self._typing.get_pause_between())
                typing_time = self._typing.get_typing_time(links)
                await self._client.type_and_wait(user_id, typing_time)
                await self._client.send_message(user_id, links)
                
                dialogue.goal_message_sent = True
                dialogue.goal_message_sent_at = datetime.utcnow()
                dialogue.status = DialogueStatus.GOAL_REACHED
                
                logger.info("Links sent", dialogue_id=str(dialogue.id))
        
        elif parsed.action == DialogueAction.NEGATIVE_FINISH:
            dialogue.status = DialogueStatus.COMPLETED
            dialogue.fail_reason = "negative_finish"
            logger.info("Dialogue negative finish", dialogue_id=str(dialogue.id))
        
        elif parsed.action == DialogueAction.HANDOFF:
            dialogue.status = DialogueStatus.PAUSED
            dialogue.needs_review = True
            logger.info("Dialogue handoff", dialogue_id=str(dialogue.id))
        
        elif parsed.action == DialogueAction.CREATIVE_SENT:
            dialogue.creative_sent = True
            logger.debug("Creative sent", dialogue_id=str(dialogue.id))
    
    def _build_prompt(self, campaign) -> str:
        """Build system prompt from campaign."""
        # Use campaign's system prompt if exists
        if hasattr(campaign, 'system_prompt') and campaign.system_prompt:
            return campaign.system_prompt
        
        # Otherwise use default crypto trader prompt
        from src.application.prompts import get_crypto_trader_prompt
        links = ""
        if hasattr(campaign, 'goal') and campaign.goal:
            links = campaign.goal.target_message or ""
        return get_crypto_trader_prompt(links=links)
    
    async def _mark_dialogue_failed(self, user_id: int, reason: str) -> None:
        """Mark dialogue as failed."""
        try:
            async with self._get_session() as session:
                repo = PostgresDialogueRepository(session)
                dialogue = await repo.get_by_account_and_user(self._account_id, user_id)
                if dialogue:
                    dialogue.status = DialogueStatus.FAILED
                    dialogue.fail_reason = reason
                    await repo.save(dialogue)
                    await session.commit()
        except Exception as e:
            logger.error("Error marking failed", error=str(e))
    
    # =========================================
    # First Message
    # =========================================
    
    async def _send_first_message(
        self,
        target_id: UUID,
        telegram_user_id: int,
        campaign_id: UUID,
    ) -> None:
        """Send first outreach message."""
        async with self._get_session() as session:
            try:
                campaign_repo = PostgresCampaignRepository(session)
                campaign = await campaign_repo.get_by_id(campaign_id)
                
                if not campaign:
                    return
                
                # Generate first message
                system_prompt = self._build_prompt(campaign)
                parsed = await self._processor.generate_first_message(
                    system_prompt=system_prompt,
                )
                
                if not parsed.has_messages:
                    logger.error("No first message generated")
                    return
                
                # Random initial delay
                import random
                await asyncio.sleep(random.uniform(30, 120))
                
                dialogue = None
                
                # Send
                if self._client:
                    for i, msg_text in enumerate(parsed.messages):
                        typing_time = self._typing.get_typing_time(msg_text)
                        msg_id = await self._client.send_message_natural(
                            user_id=telegram_user_id,
                            text=msg_text,
                            typing_time=typing_time,
                        )
                        
                        if i == 0 and msg_id:
                            # Create dialogue on first message
                            dialogue_repo = PostgresDialogueRepository(session)
                            
                            dialogue = Dialogue(
                                id=uuid4(),
                                account_id=self._account_id,
                                campaign_id=campaign_id,
                                target_user_id=target_id,
                                telegram_user_id=telegram_user_id,
                                status=DialogueStatus.INITIATED,
                            )
                            
                            dialogue.add_message(
                                message_id=uuid4(),
                                role=MessageRole.ACCOUNT,
                                content=msg_text,
                                telegram_message_id=msg_id,
                                ai_generated=True,
                            )
                            
                            await dialogue_repo.save(dialogue)
                        
                        elif msg_id and dialogue:
                            # Add to existing dialogue
                            dialogue.add_message(
                                message_id=uuid4(),
                                role=MessageRole.ACCOUNT,
                                content=msg_text,
                                telegram_message_id=msg_id,
                                ai_generated=True,
                            )
                        
                        if i < len(parsed.messages) - 1:
                            await asyncio.sleep(self._typing.get_pause_between())
                    
                    # Update target
                    target_repo = PostgresUserTargetRepository(session)
                    target = await target_repo.get_by_id(target_id)
                    if target:
                        target.mark_contacted()
                        await target_repo.save(target)
                    
                    # Increment counters
                    account_repo = PostgresAccountRepository(session)
                    await account_repo.increment_conversation_count(self._account_id)
                    await account_repo.increment_message_count(self._account_id)
                    
                    await session.commit()
                    
                    logger.info(
                        "First message sent",
                        target_id=str(target_id),
                    )
                    
            except TelegramPrivacyError:
                target_repo = PostgresUserTargetRepository(session)
                target = await target_repo.get_by_id(target_id)
                if target:
                    target.mark_failed("privacy")
                    await target_repo.save(target)
                await session.commit()
            except TelegramFloodError as e:
                logger.warning("Flood on first", seconds=e.wait_seconds)
                await asyncio.sleep(e.wait_seconds)
            except Exception as e:
                logger.error("First message error", error=str(e))
    
    # =========================================
    # Main Loop
    # =========================================
    
    async def _run_loop(self) -> None:
        """Main loop."""
        while self._running:
            try:
                # Refresh account
                async with self._get_session() as session:
                    repo = PostgresAccountRepository(session)
                    account = await repo.get_by_id(self._account_id)
                    if account:
                        self._account = account
                
                # Check schedule
                if not self._account.schedule.is_active_now(datetime.utcnow()):
                    await asyncio.sleep(60)
                    continue
                
                # Process queue
                await self._process_queue()
                
                await asyncio.sleep(10)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Loop error", error=str(e))
                await asyncio.sleep(30)
    
    async def _process_queue(self) -> None:
        """Process queued tasks."""
        while not self._message_queue.empty():
            try:
                task_data = self._message_queue.get_nowait()
                
                if task_data["type"] == "first_message":
                    if not self._account.can_start_new_conversation():
                        await self._message_queue.put(task_data)
                        break
                    
                    task = asyncio.create_task(
                        self._send_first_message(
                            task_data["target_id"],
                            task_data["telegram_user_id"],
                            task_data["campaign_id"],
                        )
                    )
                    self._pending_tasks.add(task)
                    task.add_done_callback(self._pending_tasks.discard)
                    
            except asyncio.QueueEmpty:
                break


# Alias
AccountWorker = NaturalAccountWorker
