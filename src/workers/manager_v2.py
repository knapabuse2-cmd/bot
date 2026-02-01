"""
Worker manager v2.

Improved orchestration with:
- Redis task queue for distribution
- Sequential per-account processing
- Proper startup/shutdown
- Health monitoring
- Scalable architecture
"""

import asyncio
from typing import Optional
from uuid import UUID, uuid4

import structlog

from src.domain.entities import Account, AccountStatus
from src.infrastructure.database import get_session
from src.infrastructure.database.repositories import (
    PostgresAccountRepository,
    PostgresCampaignRepository,
    PostgresUserTargetRepository,
)
from src.infrastructure.ai import get_ai_provider

from .account_worker_v2 import AccountWorkerV2
from .task_queue import Task, TaskQueue, TaskType, get_task_queue
from .scheduler import Scheduler

logger = structlog.get_logger(__name__)


class WorkerManagerV2:
    """
    Manages account workers with queue-based task distribution.
    
    Architecture:
    - Each account has its own worker
    - Each account has its own Redis queue
    - Targets are distributed to queues
    - Workers process queues sequentially
    
    This ensures:
    - Rate limiting per account
    - No concurrent DB sessions per account
    - Reliable task processing
    - Easy scaling
    """
    
    def __init__(
        self,
        max_workers: int = 100,
        distribute_interval: int = 30,
    ):
        self._workers: dict[UUID, AccountWorkerV2] = {}
        self._running = False
        self._scheduler: Optional[Scheduler] = None
        self._task_queue: Optional[TaskQueue] = None
        self._max_workers = max_workers
        self._distribute_interval = distribute_interval
    
    @property
    def running(self) -> bool:
        return self._running
    
    @property
    def worker_count(self) -> int:
        return len(self._workers)
    
    @property
    def active_worker_count(self) -> int:
        return sum(1 for w in self._workers.values() if w.running)
    
    async def start(self) -> None:
        """Start the worker manager."""
        if self._running:
            return
        
        logger.info("Starting worker manager v2")
        self._running = True
        
        # Initialize task queue
        self._task_queue = await get_task_queue()
        
        # Recover any stuck tasks from previous run
        recovered = await self._task_queue.recover_processing_tasks()
        if recovered > 0:
            logger.info(f"Recovered {recovered} stuck tasks")
        
        # Initialize scheduler
        self._scheduler = Scheduler()
        
        # Distribute targets every N seconds
        self._scheduler.add_task(
            name="distribute_targets",
            func=self._distribute_targets,
            interval_seconds=self._distribute_interval,
            run_immediately=False,  # Let workers start first
        )
        
        # Health check every minute
        self._scheduler.add_task(
            name="health_check",
            func=self._check_workers_health,
            interval_seconds=60,
            run_immediately=False,
        )
        
        # Sync workers with DB every 5 minutes
        self._scheduler.add_task(
            name="sync_workers",
            func=self._sync_workers_with_db,
            interval_seconds=300,
            run_immediately=False,
        )
        
        # Reset counters
        self._scheduler.add_task(
            name="reset_hourly_counters",
            func=self._reset_hourly_counters,
            interval_seconds=3600,
            run_immediately=False,
        )
        
        self._scheduler.add_task(
            name="reset_daily_counters",
            func=self._reset_daily_counters,
            interval_seconds=86400,
            run_immediately=False,
        )
        
        await self._scheduler.start()
        
        # Start workers for active accounts
        await self._start_active_workers()
        
        # Initial distribution after workers are up
        await asyncio.sleep(5)  # Give workers time to connect
        await self._distribute_targets()
        
        logger.info(
            "Worker manager v2 started",
            workers=self.worker_count,
            active=self.active_worker_count,
        )
    
    async def stop(self) -> None:
        """Stop the worker manager and all workers."""
        if not self._running:
            return
        
        logger.info("Stopping worker manager v2")
        self._running = False
        
        # Stop scheduler
        if self._scheduler:
            await self._scheduler.stop()
        
        # Stop all workers
        await self._stop_all_workers()
        
        # Disconnect task queue
        if self._task_queue:
            await self._task_queue.disconnect()
        
        logger.info("Worker manager v2 stopped")
    
    async def _start_active_workers(self) -> None:
        """Start workers for all active accounts with campaigns."""
        async with get_session() as session:
            account_repo = PostgresAccountRepository(session)
            accounts = await account_repo.list_by_status(AccountStatus.ACTIVE)
            
            logger.info(f"Found {len(accounts)} active accounts")
            
            started = 0
            for account in accounts:
                # Check prerequisites
                if not account.campaign_id:
                    logger.debug(
                        "Account has no campaign, skipping",
                        account_id=str(account.id),
                    )
                    continue
                
                if not account.session_data:
                    logger.warning(
                        "Account has no session, skipping",
                        account_id=str(account.id),
                    )
                    continue
                
                if len(self._workers) >= self._max_workers:
                    logger.warning(
                        f"Max workers ({self._max_workers}) reached",
                    )
                    break
                
                # Start worker
                success = await self.start_worker(account)
                if success:
                    started += 1
                
                # Small delay between worker starts to avoid overwhelming
                await asyncio.sleep(0.5)
            
            logger.info(f"Started {started} workers")
    
    async def start_worker(self, account: Account) -> bool:
        """Start a worker for an account."""
        if account.id in self._workers:
            logger.debug("Worker already exists", account_id=str(account.id))
            return True
        
        try:
            worker = AccountWorkerV2(
                account=account,
                ai_provider=get_ai_provider(),
                task_queue=self._task_queue,
            )
            
            await worker.start()
            self._workers[account.id] = worker
            
            logger.info(
                "Worker started",
                account_id=str(account.id),
                phone=account.phone,
            )
            return True
            
        except Exception as e:
            logger.error(
                "Failed to start worker",
                account_id=str(account.id),
                error=str(e),
            )
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
        
        logger.info(f"Stopping {len(self._workers)} workers")
        
        # Stop all workers concurrently
        tasks = [w.stop() for w in self._workers.values()]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        self._workers.clear()
    
    async def _distribute_targets(self) -> None:
        """
        Distribute pending targets to account queues.
        
        This adds tasks to Redis queues, workers will pick them up.
        """
        if not self._running:
            return
        
        logger.debug("Distributing targets...")
        
        async with get_session() as session:
            campaign_repo = PostgresCampaignRepository(session)
            target_repo = PostgresUserTargetRepository(session)
            account_repo = PostgresAccountRepository(session)
            
            # Get active campaigns
            campaigns = await campaign_repo.list_active()
            
            total_distributed = 0
            
            for campaign in campaigns:
                # Get pending targets
                pending = await target_repo.list_pending(
                    campaign_id=campaign.id,
                    limit=100,  # Process in batches
                )
                
                if not pending:
                    continue
                
                # Get accounts for this campaign
                accounts = await account_repo.list_by_campaign(campaign.id)
                
                # Filter to accounts with running workers
                available = [
                    a for a in accounts
                    if a.id in self._workers
                    and self._workers[a.id].running
                    and a.can_start_new_conversation()
                ]
                
                if not available:
                    logger.debug(
                        "No available workers for campaign",
                        campaign_id=str(campaign.id),
                        pending=len(pending),
                    )
                    continue
                
                logger.info(
                    "Distributing targets",
                    campaign_id=str(campaign.id),
                    pending=len(pending),
                    available_workers=len(available),
                )
                
                # Round-robin distribution to queues
                for i, target in enumerate(pending):
                    account = available[i % len(available)]
                    
                    # Create task
                    task = Task(
                        id=str(uuid4()),
                        task_type=TaskType.SEND_FIRST_MESSAGE,
                        account_id=str(account.id),
                        campaign_id=str(campaign.id),
                        target_id=str(target.id),
                        recipient=str(target.telegram_id or target.username),
                    )
                    
                    # Enqueue task
                    await self._task_queue.enqueue(task)
                    
                    # Mark target as assigned
                    target.assign_to_account(account.id)
                    await target_repo.save(target)
                    
                    total_distributed += 1
                
            if total_distributed > 0:
                logger.info(f"Distributed {total_distributed} targets to queues")
    
    async def _check_workers_health(self) -> None:
        """Check health of all workers."""
        if not self._running:
            return
        
        dead_workers = []
        
        for account_id, worker in self._workers.items():
            if not worker.running:
                dead_workers.append(account_id)
        
        if dead_workers:
            logger.warning(f"Found {len(dead_workers)} dead workers")
        
        # Restart dead workers
        for account_id in dead_workers:
            logger.info("Restarting dead worker", account_id=str(account_id))
            
            # Remove old worker
            del self._workers[account_id]
            
            # Get fresh account data
            async with get_session() as session:
                account_repo = PostgresAccountRepository(session)
                account = await account_repo.get_by_id(account_id)
                
                if account and account.status == AccountStatus.ACTIVE:
                    await self.start_worker(account)
    
    async def _sync_workers_with_db(self) -> None:
        """
        Sync workers with database state.
        
        - Start workers for newly activated accounts
        - Stop workers for deactivated accounts
        """
        if not self._running:
            return
        
        async with get_session() as session:
            account_repo = PostgresAccountRepository(session)
            
            # Get all active accounts with campaigns
            active_accounts = await account_repo.list_by_status(AccountStatus.ACTIVE)
            active_with_campaign = {
                a.id: a for a in active_accounts
                if a.campaign_id and a.session_data
            }
            
            # Stop workers for accounts no longer active
            to_stop = set(self._workers.keys()) - set(active_with_campaign.keys())
            for account_id in to_stop:
                logger.info("Stopping worker for inactive account", account_id=str(account_id))
                await self.stop_worker(account_id)
            
            # Start workers for newly active accounts
            to_start = set(active_with_campaign.keys()) - set(self._workers.keys())
            for account_id in to_start:
                if len(self._workers) >= self._max_workers:
                    break
                account = active_with_campaign[account_id]
                logger.info("Starting worker for new account", account_id=str(account_id))
                await self.start_worker(account)
    
    async def _reset_hourly_counters(self) -> None:
        """Reset hourly message counters for all accounts."""
        async with get_session() as session:
            account_repo = PostgresAccountRepository(session)
            await account_repo.reset_hourly_counters()
            logger.info("Reset hourly counters")
    
    async def _reset_daily_counters(self) -> None:
        """Reset daily conversation counters for all accounts."""
        async with get_session() as session:
            account_repo = PostgresAccountRepository(session)
            await account_repo.reset_daily_counters()
            logger.info("Reset daily counters")
    
    def get_stats(self) -> dict:
        """Get manager statistics."""
        worker_stats = [w.stats for w in self._workers.values()]
        
        return {
            "running": self._running,
            "worker_count": self.worker_count,
            "active_workers": self.active_worker_count,
            "workers": worker_stats,
        }
    
    async def get_queue_stats(self) -> dict:
        """Get queue statistics."""
        if not self._task_queue:
            return {}
        
        return await self._task_queue.get_stats()
