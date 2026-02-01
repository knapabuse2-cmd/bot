"""
Redis-based task queue for scalable message distribution.

Each account has its own queue to ensure sequential processing
and proper rate limiting per account.
"""

import json
import asyncio
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional
from uuid import UUID

import structlog
from redis import asyncio as aioredis

from src.config import get_settings

logger = structlog.get_logger(__name__)


class TaskStatus(str, Enum):
    """Task status in queue."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY = "retry"


class TaskType(str, Enum):
    """Type of task."""
    SEND_FIRST_MESSAGE = "send_first_message"
    SEND_RESPONSE = "send_response"
    SEND_FOLLOW_UP = "send_follow_up"


@dataclass
class Task:
    """Task to be processed by worker."""
    id: str
    task_type: TaskType
    account_id: str
    campaign_id: str
    target_id: Optional[str] = None
    dialogue_id: Optional[str] = None
    recipient: Optional[str] = None  # telegram_id or username
    created_at: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    error: Optional[str] = None
    
    def to_json(self) -> str:
        """Serialize to JSON."""
        data = asdict(self)
        data['task_type'] = self.task_type.value
        return json.dumps(data)
    
    @classmethod
    def from_json(cls, data: str) -> 'Task':
        """Deserialize from JSON."""
        parsed = json.loads(data)
        parsed['task_type'] = TaskType(parsed['task_type'])
        return cls(**parsed)


class TaskQueue:
    """
    Redis-based task queue with per-account queues.
    
    Features:
    - Separate queue per account for rate limiting
    - Task persistence (survives restarts)
    - Retry logic with exponential backoff
    - Priority support
    - Dead letter queue for failed tasks
    """
    
    QUEUE_PREFIX = "outreach:queue:"
    PROCESSING_PREFIX = "outreach:processing:"
    STATS_PREFIX = "outreach:stats:"
    DLQ_KEY = "outreach:dlq"
    
    def __init__(self, redis_url: Optional[str] = None):
        self._redis_url = redis_url or get_settings().redis.url
        self._redis: Optional[aioredis.Redis] = None
    
    async def connect(self) -> None:
        """Connect to Redis."""
        if self._redis is None:
            self._redis = await aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            logger.info("Task queue connected to Redis")
    
    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.close()
            self._redis = None
    
    def _queue_key(self, account_id: str) -> str:
        """Get queue key for account."""
        return f"{self.QUEUE_PREFIX}{account_id}"
    
    def _processing_key(self, account_id: str) -> str:
        """Get processing set key for account."""
        return f"{self.PROCESSING_PREFIX}{account_id}"
    
    async def enqueue(
        self,
        task: Task,
        priority: bool = False,
    ) -> bool:
        """
        Add task to account's queue.
        
        Args:
            task: Task to enqueue
            priority: If True, add to front of queue
            
        Returns:
            True if successful
        """
        if not self._redis:
            await self.connect()
        
        task.created_at = datetime.utcnow().isoformat()
        queue_key = self._queue_key(task.account_id)
        
        try:
            if priority:
                await self._redis.lpush(queue_key, task.to_json())
            else:
                await self._redis.rpush(queue_key, task.to_json())
            
            # Update stats
            await self._redis.hincrby(
                f"{self.STATS_PREFIX}enqueued",
                task.account_id,
                1,
            )
            
            logger.debug(
                "Task enqueued",
                task_id=task.id,
                account_id=task.account_id,
                task_type=task.task_type.value,
            )
            return True
            
        except Exception as e:
            logger.error("Failed to enqueue task", error=str(e))
            return False
    
    async def dequeue(
        self,
        account_id: str,
        timeout: int = 1,
    ) -> Optional[Task]:
        """
        Get next task from account's queue.
        
        Uses blocking pop with timeout for efficiency.
        Moves task to processing set for reliability.
        
        Args:
            account_id: Account to get task for
            timeout: Seconds to wait for task
            
        Returns:
            Task or None if queue empty
        """
        if not self._redis:
            await self.connect()
        
        queue_key = self._queue_key(account_id)
        processing_key = self._processing_key(account_id)
        
        try:
            # Blocking pop with timeout
            result = await self._redis.blpop(queue_key, timeout=timeout)
            
            if result is None:
                return None
            
            _, task_json = result
            task = Task.from_json(task_json)
            
            # Move to processing set
            await self._redis.hset(processing_key, task.id, task_json)
            
            logger.debug(
                "Task dequeued",
                task_id=task.id,
                account_id=account_id,
            )
            return task
            
        except Exception as e:
            logger.error("Failed to dequeue task", error=str(e))
            return None
    
    async def complete(self, task: Task) -> None:
        """
        Mark task as completed.
        
        Removes from processing set and updates stats.
        """
        if not self._redis:
            return
        
        processing_key = self._processing_key(task.account_id)
        
        await self._redis.hdel(processing_key, task.id)
        await self._redis.hincrby(
            f"{self.STATS_PREFIX}completed",
            task.account_id,
            1,
        )
        
        logger.debug("Task completed", task_id=task.id)
    
    async def fail(
        self,
        task: Task,
        error: str,
        retry: bool = True,
    ) -> None:
        """
        Mark task as failed.
        
        If retry=True and retries remaining, re-enqueue with delay.
        Otherwise, move to dead letter queue.
        """
        if not self._redis:
            return
        
        processing_key = self._processing_key(task.account_id)
        await self._redis.hdel(processing_key, task.id)
        
        task.error = error
        task.retry_count += 1
        
        if retry and task.retry_count <= task.max_retries:
            # Re-enqueue with exponential backoff delay
            delay = min(300, 10 * (2 ** task.retry_count))  # Max 5 min
            
            logger.warning(
                "Task failed, will retry",
                task_id=task.id,
                retry_count=task.retry_count,
                delay=delay,
            )
            
            # Schedule retry
            await asyncio.sleep(delay)
            await self.enqueue(task, priority=True)
        else:
            # Move to dead letter queue
            await self._redis.rpush(self.DLQ_KEY, task.to_json())
            await self._redis.hincrby(
                f"{self.STATS_PREFIX}failed",
                task.account_id,
                1,
            )
            
            logger.error(
                "Task failed permanently",
                task_id=task.id,
                error=error,
            )
    
    async def get_queue_length(self, account_id: str) -> int:
        """Get number of pending tasks for account."""
        if not self._redis:
            await self.connect()
        
        return await self._redis.llen(self._queue_key(account_id))
    
    async def get_all_queue_lengths(self) -> dict[str, int]:
        """Get queue lengths for all accounts."""
        if not self._redis:
            await self.connect()
        
        result = {}
        cursor = 0
        
        while True:
            cursor, keys = await self._redis.scan(
                cursor,
                match=f"{self.QUEUE_PREFIX}*",
            )
            
            for key in keys:
                account_id = key.replace(self.QUEUE_PREFIX, "")
                length = await self._redis.llen(key)
                result[account_id] = length
            
            if cursor == 0:
                break
        
        return result
    
    async def get_stats(self) -> dict:
        """Get queue statistics."""
        if not self._redis:
            await self.connect()
        
        enqueued = await self._redis.hgetall(f"{self.STATS_PREFIX}enqueued")
        completed = await self._redis.hgetall(f"{self.STATS_PREFIX}completed")
        failed = await self._redis.hgetall(f"{self.STATS_PREFIX}failed")
        dlq_size = await self._redis.llen(self.DLQ_KEY)
        
        return {
            "enqueued": {k: int(v) for k, v in enqueued.items()},
            "completed": {k: int(v) for k, v in completed.items()},
            "failed": {k: int(v) for k, v in failed.items()},
            "dlq_size": dlq_size,
        }
    
    async def clear_account_queue(self, account_id: str) -> int:
        """Clear all tasks for account. Returns count deleted."""
        if not self._redis:
            await self.connect()
        
        queue_key = self._queue_key(account_id)
        processing_key = self._processing_key(account_id)
        
        queue_len = await self._redis.llen(queue_key)
        await self._redis.delete(queue_key, processing_key)
        
        return queue_len
    
    async def recover_processing_tasks(self) -> int:
        """
        Recover tasks stuck in processing state.
        
        Call on startup to handle tasks from crashed workers.
        Returns count of recovered tasks.
        """
        if not self._redis:
            await self.connect()
        
        recovered = 0
        cursor = 0
        
        while True:
            cursor, keys = await self._redis.scan(
                cursor,
                match=f"{self.PROCESSING_PREFIX}*",
            )
            
            for key in keys:
                account_id = key.replace(self.PROCESSING_PREFIX, "")
                tasks = await self._redis.hgetall(key)
                
                for task_id, task_json in tasks.items():
                    # Re-enqueue with priority
                    task = Task.from_json(task_json)
                    await self.enqueue(task, priority=True)
                    recovered += 1
                
                # Clear processing set
                await self._redis.delete(key)
            
            if cursor == 0:
                break
        
        if recovered > 0:
            logger.info(f"Recovered {recovered} stuck tasks")
        
        return recovered


# Singleton instance
_task_queue: Optional[TaskQueue] = None


async def get_task_queue() -> TaskQueue:
    """Get global task queue instance."""
    global _task_queue
    
    if _task_queue is None:
        _task_queue = TaskQueue()
        await _task_queue.connect()
    
    return _task_queue
