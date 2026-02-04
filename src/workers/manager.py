"""
Worker manager.

Orchestrates all account workers, handling:
- Starting/stopping workers
- Load balancing
- Health monitoring
- Target distribution
- Scheduled tasks (counter resets)

FIXED:
- Session lifecycle (session per operation)
- Distributed lock for target assignment
- Proper cleanup on shutdown
"""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional
from uuid import UUID

import structlog

from src.application.services import AccountService, DialogueService
from src.domain.entities import Account, AccountStatus
from src.infrastructure.database import get_session
from src.infrastructure.database.repositories import (
    PostgresAccountRepository,
    PostgresCampaignRepository,
    PostgresDialogueRepository,
    PostgresProxyRepository,
    PostgresUserTargetRepository,
)
from src.infrastructure.ai import get_ai_provider
from src.infrastructure.redis import get_redis_client, close_redis
from src.infrastructure.redis.locks import DistributedLock
from src.infrastructure.notifications import get_alert_service, close_alert_service
from src.services.warmup_service import WarmupService

from src.infrastructure.proxy.checker import get_proxy_checker

from .account_worker import AccountWorker
from .scheduler import Scheduler
from .warmup_worker import WarmupScheduler

logger = structlog.get_logger(__name__)


class WorkerManager:
    """
    Manages all account workers.
    
    Responsible for:
    - Starting workers for active accounts
    - Distributing targets to workers
    - Monitoring worker health
    - Graceful shutdown
    - Scheduled maintenance tasks
    """
    
    # Lock names
    DISTRIBUTE_LOCK = "outreach:lock:distribute_targets"
    HEALTH_CHECK_LOCK = "outreach:lock:health_check"
    
    def __init__(self):
        self._workers: dict[UUID, AccountWorker] = {}
        self._running = False
        self._scheduler: Optional[Scheduler] = None
        self._warmup_scheduler: Optional[WarmupScheduler] = None
        self._warmup_scheduler_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
    
    @property
    def running(self) -> bool:
        return self._running
    
    @property
    def worker_count(self) -> int:
        return len(self._workers)
    
    @property
    def active_worker_count(self) -> int:
        return sum(1 for w in self._workers.values() if w.running)
    
    def get_stats(self) -> dict:
        """Get manager statistics."""
        return {
            "running": self._running,
            "total_workers": self.worker_count,
            "active_workers": self.active_worker_count,
            "worker_ids": [str(wid) for wid in self._workers.keys()],
            "warmup_scheduler_running": self._warmup_scheduler is not None and self._warmup_scheduler._running,
        }
    
    async def start(self) -> None:
        """Start the worker manager."""
        if self._running:
            return
        
        logger.info("Starting worker manager")
        self._running = True
        self._shutdown_event.clear()
        
        # Initialize scheduler
        self._scheduler = Scheduler()
        self._scheduler.add_task(
            name="distribute_targets",
            func=self._distribute_targets,
            interval_seconds=30,
            run_immediately=True,
        )
        self._scheduler.add_task(
            name="health_check",
            func=self._check_workers_health,
            interval_seconds=60,
            run_immediately=False,
        )
        self._scheduler.add_task(
            name="sync_workers",
            func=self._sync_workers,
            interval_seconds=15,
            run_immediately=False,
        )
        self._scheduler.add_task(
            name="reset_hourly_counters",
            func=self._reset_hourly_counters,
            interval_seconds=3600,
            run_immediately=False,
        )
        # Run daily reset check every hour (each account has its own reset hour)
        # This distributes resets across 24 hours to avoid synchronized spikes
        self._scheduler.add_task(
            name="reset_daily_counters",
            func=self._reset_daily_counters,
            interval_seconds=3600,  # Check every hour
            run_immediately=True,   # Initialize reset hours on startup
        )
        # Run warmup daily reset check every hour as well
        self._scheduler.add_task(
            name="reset_warmup_daily_counters",
            func=self._reset_warmup_daily_counters,
            interval_seconds=3600,  # Check every hour
            run_immediately=False,
        )
        # NOTE: Automatic proxy health check removed to save traffic
        # Proxies are now checked on-demand when account interacts with Telegram

        await self._scheduler.start()

        # Start warmup scheduler
        self._warmup_scheduler = WarmupScheduler()
        self._warmup_scheduler_task = asyncio.create_task(self._warmup_scheduler.start())
        logger.info("Warmup scheduler started")

        # Start workers for active accounts
        await self._start_active_workers()

        logger.info(
            "Worker manager started",
            workers=self.worker_count,
        )
    
    async def stop(self) -> None:
        """Stop the worker manager and all workers."""
        if not self._running:
            return
        
        logger.info("Stopping worker manager")
        self._running = False
        self._shutdown_event.set()
        
        # Stop scheduler
        if self._scheduler:
            await self._scheduler.stop()
            self._scheduler = None

        # Stop warmup scheduler
        if self._warmup_scheduler:
            await self._warmup_scheduler.stop()
            self._warmup_scheduler = None
        if self._warmup_scheduler_task:
            self._warmup_scheduler_task.cancel()
            try:
                await self._warmup_scheduler_task
            except asyncio.CancelledError:
                pass
            self._warmup_scheduler_task = None
        logger.info("Warmup scheduler stopped")

        # Stop all workers gracefully
        await self._stop_all_workers()

        # Close Redis connection
        await close_redis()

        # Close alert service
        await close_alert_service()

        logger.info("Worker manager stopped")
    
    async def _start_active_workers(self) -> None:
        """Start workers for all active accounts with random delays to avoid detection."""
        import random

        async with get_session() as session:
            account_repo = PostgresAccountRepository(session)
            accounts = await account_repo.list_by_status(AccountStatus.ACTIVE)

            # Shuffle accounts to randomize connection order
            accounts_list = list(accounts)
            random.shuffle(accounts_list)

            for i, account in enumerate(accounts_list):
                await self.start_worker(account.id)

                # Add random delay between connections (3-10 seconds)
                # Skip delay after last account
                if i < len(accounts_list) - 1:
                    delay = random.uniform(3.0, 10.0)
                    logger.debug(
                        "Waiting before next worker start",
                        delay_seconds=round(delay, 1),
                        remaining=len(accounts_list) - i - 1,
                    )
                    await asyncio.sleep(delay)
    
    async def start_worker(self, account_id: UUID) -> bool:
        """
        Start a worker for an account.
        
        Args:
            account_id: Account UUID
            
        Returns:
            True if started successfully
        """
        if account_id in self._workers:
            logger.warning(
                "Worker already exists",
                account_id=str(account_id),
            )
            return False
        
        try:
            # Load account data
            async with get_session() as session:
                account_repo = PostgresAccountRepository(session)
                account = await account_repo.get_by_id(account_id)
                
                if account is None:
                    logger.error("Account not found", account_id=str(account_id))
                    return False
                
                if account.status != AccountStatus.ACTIVE:
                    logger.warning(
                        "Account not active",
                        account_id=str(account_id),
                        status=account.status.value,
                    )
                    return False
            
            # Create worker with session factory (NOT persistent session)
            worker = AccountWorker(
                account=account,
                session_factory=get_session,
                ai_provider=get_ai_provider(),
            )
            
            await worker.start()
            self._workers[account_id] = worker
            
            logger.info(
                "Worker started",
                account_id=str(account_id),
            )
            return True
            
        except Exception as e:
            import traceback
            import sys
            tb = traceback.format_exc()
            sys.stderr.write(f"TRACEBACK FOR WORKER START FAILURE:\n{tb}\n")
            sys.stderr.flush()
            logger.error(
                "Failed to start worker",
                account_id=str(account_id),
                error=str(e),
            )

            # Send alert to admins
            try:
                alert_service = get_alert_service()
                await alert_service.alert_account_error(
                    phone=account.phone if account else "unknown",
                    error=str(e),
                    account_id=str(account_id),
                )
            except Exception as alert_error:
                logger.error("Failed to send alert", error=str(alert_error))

            return False
    
    async def stop_worker(self, account_id: UUID) -> bool:
        """Stop a specific worker."""
        worker = self._workers.get(account_id)
        if not worker:
            return False
        
        await worker.stop()
        del self._workers[account_id]
        
        logger.info("Worker stopped", account_id=str(account_id))
        return True
    
    async def _stop_all_workers(self) -> None:
        """Stop all workers gracefully."""
        if not self._workers:
            return
        
        logger.info(f"Stopping {len(self._workers)} workers...")
        
        # Stop all workers concurrently with timeout
        tasks = [w.stop() for w in self._workers.values()]
        
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Some workers did not stop in time")
        
        self._workers.clear()
    
    async def _distribute_targets(self) -> None:
        """
        Distribute pending targets to available workers based on campaign sending settings.

        Each campaign has:
        - send_interval_hours: How often to send batches
        - messages_per_batch: How many first messages per batch
        - message_delay_min/max: Delay between messages in batch

        Targets are distributed evenly among available workers.
        """
        redis_client = await get_redis_client()
        lock = DistributedLock(redis_client, self.DISTRIBUTE_LOCK, timeout=25)

        if not await lock.acquire():
            logger.debug("Could not acquire distribute lock, skipping")
            return

        try:
            async with get_session() as session:
                campaign_repo = PostgresCampaignRepository(session)
                target_repo = PostgresUserTargetRepository(session)
                account_repo = PostgresAccountRepository(session)

                # Get active campaigns
                campaigns = await campaign_repo.list_active()

                for campaign in campaigns:
                    # Check if it's time to send next batch based on campaign settings
                    if not campaign.sending.can_send_batch():
                        logger.debug(
                            "Campaign batch not ready yet",
                            campaign_id=str(campaign.id),
                            last_batch=str(campaign.sending.last_batch_at),
                            interval_hours=campaign.sending.send_interval_hours,
                        )
                        continue

                    # Get available accounts for this campaign first
                    accounts = await account_repo.list_by_campaign(campaign.id)
                    available = [
                        a for a in accounts
                        if a.id in self._workers
                        and self._workers[a.id].running
                        and a.can_start_new_conversation()
                    ]

                    if not available:
                        logger.warning(
                            "No available accounts for campaign",
                            campaign_id=str(campaign.id),
                        )
                        continue

                    # Calculate dynamic batch size: sum of remaining capacity for each account
                    # Each account can send (max_new_conversations_per_day - daily_conversations_count)
                    batch_size = sum(
                        a.limits.max_new_conversations_per_day - a.daily_conversations_count
                        for a in available
                    )

                    if batch_size <= 0:
                        logger.debug(
                            "All accounts reached daily limit",
                            campaign_id=str(campaign.id),
                        )
                        continue

                    # Get pending targets with FOR UPDATE lock (limit by calculated batch size)
                    pending = await target_repo.list_pending_for_update(
                        campaign_id=campaign.id,
                        limit=batch_size,
                    )

                    if not pending:
                        continue

                    logger.info(
                        "Distributing batch",
                        campaign_id=str(campaign.id),
                        targets=len(pending),
                        accounts=len(available),
                        batch_size=batch_size,
                        delay_range=f"{campaign.sending.message_delay_min}-{campaign.sending.message_delay_max}s",
                    )

                    # Build capacity map: how many targets each account can still take
                    account_capacity = {
                        a.id: a.limits.max_new_conversations_per_day - a.daily_conversations_count
                        for a in available
                    }

                    # Distribute targets based on remaining capacity
                    for i, target in enumerate(pending):
                        # Find account with remaining capacity (round-robin among those with capacity)
                        account = None
                        for _ in range(len(available)):
                            candidate = available[i % len(available)]
                            if account_capacity.get(candidate.id, 0) > 0:
                                account = candidate
                                account_capacity[candidate.id] -= 1
                                break
                            i += 1

                        if not account:
                            # No accounts with remaining capacity
                            logger.warning(
                                "No accounts with remaining capacity",
                                remaining_targets=len(pending) - i,
                            )
                            break

                        # Assign target to account
                        target.assign_to_account(account.id)
                        await target_repo.save(target)

                        # Queue task for worker with delay based on index
                        worker = self._workers.get(account.id)
                        if worker:
                            await worker.queue_first_message(
                                target_id=target.id,
                                telegram_user_id=target.telegram_id or 0,
                                telegram_username=target.username,
                                campaign_id=campaign.id,
                            )

                    # Record that batch was sent
                    campaign.sending.record_batch_sent()
                    await campaign_repo.save(campaign)

                    # Commit after each campaign
                    await session.commit()

                    logger.info(
                        "Batch distributed",
                        campaign_id=str(campaign.id),
                        targets_count=len(pending),
                        next_batch_in_hours=campaign.sending.send_interval_hours,
                    )

        except Exception as e:
            logger.error("Error distributing targets", error=str(e))
        finally:
            await lock.release()
    
    async def _sync_workers(self) -> None:
        """
        Sync workers with active accounts.

        - Start workers for newly activated accounts
        - Stop workers for deactivated accounts
        """
        try:
            async with get_session() as session:
                account_repo = PostgresAccountRepository(session)
                active_accounts = await account_repo.list_by_status(AccountStatus.ACTIVE)
                active_ids = {a.id for a in active_accounts}

                # Start workers for active accounts without workers
                for account in active_accounts:
                    if account.id not in self._workers:
                        logger.info(
                            "Starting worker for newly activated account",
                            account_id=str(account.id),
                        )
                        await self.start_worker(account.id)

                # Stop workers for accounts no longer active
                for account_id in list(self._workers.keys()):
                    if account_id not in active_ids:
                        logger.info(
                            "Stopping worker for deactivated account",
                            account_id=str(account_id),
                        )
                        await self.stop_worker(account_id)

        except Exception as e:
            logger.error("Error syncing workers", error=str(e))

    async def _check_workers_health(self) -> None:
        """Check health of all workers."""
        redis_client = await get_redis_client()
        lock = DistributedLock(redis_client, self.HEALTH_CHECK_LOCK, timeout=55)
        
        if not await lock.acquire():
            return
        
        try:
            unhealthy = []
            
            for account_id, worker in list(self._workers.items()):
                if not worker.running:
                    unhealthy.append(account_id)
                    continue
                
                # Check if worker is responsive
                if not await worker.health_check():
                    unhealthy.append(account_id)
            
            # Restart unhealthy workers
            for account_id in unhealthy:
                logger.warning(
                    "Restarting unhealthy worker",
                    account_id=str(account_id),
                )

                # Get account phone for alert
                phone = "unknown"
                try:
                    async with get_session() as session:
                        account_repo = PostgresAccountRepository(session)
                        account = await account_repo.get_by_id(account_id)
                        if account:
                            phone = account.phone
                except Exception:
                    pass

                # Send alert
                try:
                    alert_service = get_alert_service()
                    await alert_service.alert_worker_restart(
                        phone=phone,
                        account_id=str(account_id),
                        reason="Worker health check failed",
                    )
                except Exception as alert_error:
                    logger.error("Failed to send alert", error=str(alert_error))

                await self.stop_worker(account_id)
                await self.start_worker(account_id)
                
        except Exception as e:
            logger.error("Error in health check", error=str(e))
        finally:
            await lock.release()
    
    async def _reset_hourly_counters(self) -> None:
        """Reset hourly message counters for all accounts."""
        async with get_session() as session:
            account_repo = PostgresAccountRepository(session)
            await account_repo.reset_hourly_counters()
            await session.commit()
        
        logger.info("Hourly counters reset")
    
    async def _reset_daily_counters(self) -> None:
        """Reset daily conversation counters for accounts whose reset hour has come.

        Each account has a randomized daily_reset_hour (0-23) to avoid all accounts
        resetting at the same time (which could be detected by Telegram).
        This method runs every hour and only resets accounts whose hour matches.
        """
        from datetime import datetime

        current_hour = datetime.utcnow().hour

        async with get_session() as session:
            account_repo = PostgresAccountRepository(session)

            # First run: initialize reset hours for accounts that don't have one
            initialized = await account_repo.initialize_daily_reset_hours()
            if initialized > 0:
                logger.info(
                    "Initialized daily reset hours for accounts",
                    count=initialized,
                )

            # Reset only accounts whose reset hour is now
            count = await account_repo.reset_daily_counters(current_hour)
            await session.commit()

        if count > 0:
            logger.info(
                "Daily counters reset for accounts",
                count=count,
                hour=current_hour,
            )

    async def _reset_warmup_daily_counters(self) -> None:
        """Reset daily warmup counters for accounts whose reset hour has come.

        Each warmup has a randomized daily_reset_hour (0-23) to avoid all warmups
        resetting at the same time (which could be detected by Telegram).
        This method runs every hour and only resets warmups whose hour matches.
        """
        from datetime import datetime

        current_hour = datetime.utcnow().hour

        try:
            async with get_session() as session:
                service = WarmupService(session)

                # First run: initialize reset hours for warmups that don't have one
                initialized = await service.initialize_daily_reset_hours()
                if initialized > 0:
                    logger.info(
                        "Initialized daily reset hours for warmups",
                        count=initialized,
                    )

                # Reset only warmups whose reset hour is now
                count = await service.reset_daily_counters(current_hour)
                await session.commit()

            if count > 0:
                logger.info(
                    "Warmup daily counters reset",
                    count=count,
                    hour=current_hour,
                )
        except Exception as e:
            logger.error(f"Error resetting warmup daily counters: {e}")



# Singleton manager
_manager: Optional[WorkerManager] = None


def get_worker_manager() -> WorkerManager:
    """Get or create worker manager singleton."""
    global _manager
    
    if _manager is None:
        _manager = WorkerManager()
    
    return _manager


async def shutdown_manager() -> None:
    """Shutdown the worker manager."""
    global _manager
    
    if _manager is not None:
        await _manager.stop()
        _manager = None
