"""
Task scheduler.

Handles periodic tasks like:
- Counter resets
- Health checks
- Target distribution

Anti-detection features:
- Random jitter on intervals (±20-30%)
- Random initial offset to desynchronize tasks
"""

import asyncio
import random
from datetime import datetime, timedelta
from typing import Callable, Optional

import structlog

logger = structlog.get_logger(__name__)


def _add_jitter(base_interval: float, jitter_percent: float = 0.25) -> float:
    """
    Add random jitter to interval.

    Args:
        base_interval: Base interval in seconds
        jitter_percent: Jitter range as percentage (0.25 = ±25%)

    Returns:
        Interval with random jitter applied
    """
    jitter_range = base_interval * jitter_percent
    return base_interval + random.uniform(-jitter_range, jitter_range)


class ScheduledTask:
    """
    Represents a scheduled periodic task.

    Anti-detection features:
    - Random initial offset (0 to interval) to desynchronize tasks
    - Jitter on each interval (±25%) to avoid predictable patterns
    """

    def __init__(
        self,
        name: str,
        func: Callable,
        interval_seconds: float,
        run_immediately: bool = False,
        jitter_percent: float = 0.25,
        randomize_start: bool = True,
    ):
        self.name = name
        self.func = func
        self.base_interval = interval_seconds
        self.run_immediately = run_immediately
        self.jitter_percent = jitter_percent
        self.randomize_start = randomize_start

        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_run: Optional[datetime] = None
        self._run_count = 0
        self._error_count = 0

    @property
    def interval(self) -> float:
        """Get current interval with jitter applied."""
        return _add_jitter(self.base_interval, self.jitter_percent)
    
    @property
    def running(self) -> bool:
        return self._running
    
    @property
    def stats(self) -> dict:
        return {
            "name": self.name,
            "running": self._running,
            "base_interval": self.base_interval,
            "jitter_percent": self.jitter_percent,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "run_count": self._run_count,
            "error_count": self._error_count,
        }
    
    async def start(self) -> None:
        """Start the scheduled task."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        
        logger.info(
            "Scheduled task started",
            name=self.name,
            interval=self.interval,
        )
    
    async def stop(self) -> None:
        """Stop the scheduled task."""
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("Scheduled task stopped", name=self.name)
    
    async def _run_loop(self) -> None:
        """Main loop for the scheduled task."""
        # Random initial offset to desynchronize tasks across workers
        if self.randomize_start and not self.run_immediately:
            # Random offset between 0 and 50% of base interval
            initial_offset = random.uniform(0, self.base_interval * 0.5)
            logger.debug(
                "Applying random start offset",
                name=self.name,
                offset_seconds=round(initial_offset, 1),
            )
            await asyncio.sleep(initial_offset)
        elif not self.run_immediately:
            # Still apply jitter to initial delay
            await asyncio.sleep(self.interval)

        while self._running:
            try:
                await self._execute()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._error_count += 1
                logger.error(
                    "Scheduled task error",
                    name=self.name,
                    error=str(e),
                )

            # Get new jittered interval for next iteration
            next_interval = self.interval
            logger.debug(
                "Next scheduled run",
                name=self.name,
                interval_seconds=round(next_interval, 1),
            )
            await asyncio.sleep(next_interval)
    
    async def _execute(self) -> None:
        """Execute the task."""
        logger.debug("Executing scheduled task", name=self.name)
        
        self._last_run = datetime.utcnow()
        self._run_count += 1
        
        result = self.func()
        if asyncio.iscoroutine(result):
            await result


class Scheduler:
    """
    Manages multiple scheduled tasks.
    """
    
    def __init__(self):
        self._tasks: dict[str, ScheduledTask] = {}
        self._running = False
    
    @property
    def running(self) -> bool:
        return self._running
    
    def add_task(
        self,
        name: str,
        func: Callable,
        interval_seconds: float,
        run_immediately: bool = False,
        jitter_percent: float = 0.25,
        randomize_start: bool = True,
    ) -> None:
        """
        Add a scheduled task.

        Args:
            name: Unique task name
            func: Function to execute
            interval_seconds: Base interval between executions
            run_immediately: If True, run task immediately on start
            jitter_percent: Random jitter range (0.25 = ±25%)
            randomize_start: If True, add random offset on first run
        """
        if name in self._tasks:
            raise ValueError(f"Task {name} already exists")

        self._tasks[name] = ScheduledTask(
            name=name,
            func=func,
            interval_seconds=interval_seconds,
            run_immediately=run_immediately,
            jitter_percent=jitter_percent,
            randomize_start=randomize_start,
        )
    
    def remove_task(self, name: str) -> bool:
        """Remove a scheduled task."""
        if name not in self._tasks:
            return False
        
        del self._tasks[name]
        return True
    
    async def start(self) -> None:
        """Start all scheduled tasks."""
        if self._running:
            return
        
        self._running = True
        
        for task in self._tasks.values():
            await task.start()
        
        logger.info(
            "Scheduler started",
            tasks=len(self._tasks),
        )
    
    async def stop(self) -> None:
        """Stop all scheduled tasks."""
        self._running = False
        
        tasks = [task.stop() for task in self._tasks.values()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        logger.info("Scheduler stopped")
    
    def get_stats(self) -> dict:
        """Get scheduler statistics."""
        return {
            "running": self._running,
            "tasks": [task.stats for task in self._tasks.values()],
        }


def create_worker_scheduler(
    reset_hourly_func: Callable,
    reset_daily_func: Callable,
    distribute_targets_func: Callable,
    health_check_func: Callable,
) -> Scheduler:
    """
    Create scheduler with standard worker tasks.

    Anti-detection: All intervals have ±25% jitter and random start offsets
    to avoid synchronized patterns across workers.

    Args:
        reset_hourly_func: Function to reset hourly counters
        reset_daily_func: Function to reset daily counters
        distribute_targets_func: Function to distribute targets
        health_check_func: Function to check worker health

    Returns:
        Configured scheduler
    """
    scheduler = Scheduler()

    # Reset hourly counters ~every hour (±15 min with jitter)
    scheduler.add_task(
        name="reset_hourly_counters",
        func=reset_hourly_func,
        interval_seconds=3600,  # 1 hour base
        run_immediately=False,
        jitter_percent=0.25,
        randomize_start=True,
    )

    # Reset daily counters ~every 24h (with significant jitter)
    scheduler.add_task(
        name="reset_daily_counters",
        func=reset_daily_func,
        interval_seconds=86400,  # 24 hours base
        run_immediately=False,
        jitter_percent=0.15,  # ±3.6 hours
        randomize_start=True,
    )

    # Distribute targets every ~25-45 seconds (was fixed 30s)
    scheduler.add_task(
        name="distribute_targets",
        func=distribute_targets_func,
        interval_seconds=35,  # Slightly higher base
        run_immediately=True,
        jitter_percent=0.30,  # ±30% = 24.5-45.5s range
        randomize_start=False,  # Run immediately anyway
    )

    # Health check every ~45-75 seconds (was fixed 60s)
    scheduler.add_task(
        name="health_check",
        func=health_check_func,
        interval_seconds=60,
        run_immediately=False,
        jitter_percent=0.25,
        randomize_start=True,
    )

    return scheduler
