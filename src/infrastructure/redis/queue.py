"""
Redis queue manager.

Handles task queuing and distribution using Redis.
"""

import asyncio
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional
from uuid import UUID

import redis.asyncio as redis
import structlog

from src.config import get_settings

logger = structlog.get_logger(__name__)


class TaskType(str, Enum):
    """Types of tasks that can be queued."""
    
    SEND_FIRST_MESSAGE = "send_first_message"
    SEND_FOLLOW_UP = "send_follow_up"
    PROCESS_INCOMING = "process_incoming"
    CHECK_ACCOUNT_HEALTH = "check_account_health"
    RESET_COUNTERS = "reset_counters"


@dataclass
class Task:
    """Represents a queued task."""
    
    task_id: str
    task_type: TaskType
    payload: dict
    created_at: datetime
    priority: int = 0
    retry_count: int = 0
    max_retries: int = 3
    
    def to_json(self) -> str:
        """Serialize task to JSON."""
        data = asdict(self)
        data["task_type"] = self.task_type.value
        data["created_at"] = self.created_at.isoformat()
        return json.dumps(data)
    
    @classmethod
    def from_json(cls, data: str) -> "Task":
        """Deserialize task from JSON."""
        parsed = json.loads(data)
        parsed["task_type"] = TaskType(parsed["task_type"])
        parsed["created_at"] = datetime.fromisoformat(parsed["created_at"])
        return cls(**parsed)


class QueueManager:
    """
    Manages Redis-based task queues.
    
    Features:
    - Priority queues per account
    - Task deduplication
    - Retry logic
    - Dead letter queue
    """
    
    QUEUE_PREFIX = "outreach:queue"
    PROCESSING_PREFIX = "outreach:processing"
    DEAD_LETTER_PREFIX = "outreach:dead"
    TASK_SET_PREFIX = "outreach:tasks"
    
    def __init__(self, redis_client: redis.Redis):
        self._redis = redis_client
        self._handlers: dict[TaskType, Callable] = {}
        self._running = False
    
    @property
    def running(self) -> bool:
        return self._running
    
    def register_handler(
        self,
        task_type: TaskType,
        handler: Callable[[Task], Any],
    ) -> None:
        """Register a handler for a task type."""
        self._handlers[task_type] = handler
    
    async def enqueue(
        self,
        task_type: TaskType,
        payload: dict,
        account_id: Optional[UUID] = None,
        priority: int = 0,
        deduplicate: bool = True,
    ) -> Optional[str]:
        """
        Add a task to the queue.
        
        Args:
            task_type: Type of task
            payload: Task data
            account_id: Optional account ID for routing
            priority: Task priority (higher = more urgent)
            deduplicate: Skip if similar task exists
            
        Returns:
            Task ID if enqueued, None if deduplicated
        """
        import uuid
        
        task_id = str(uuid.uuid4())
        task = Task(
            task_id=task_id,
            task_type=task_type,
            payload=payload,
            created_at=datetime.utcnow(),
            priority=priority,
        )
        
        # Deduplication key
        if deduplicate:
            dedup_key = f"{task_type.value}:{json.dumps(payload, sort_keys=True)}"
            task_set_key = f"{self.TASK_SET_PREFIX}:{account_id or 'global'}"
            
            # Check if already queued
            if await self._redis.sismember(task_set_key, dedup_key):
                logger.debug(
                    "Task deduplicated",
                    task_type=task_type.value,
                )
                return None
            
            # Add to set with expiry
            await self._redis.sadd(task_set_key, dedup_key)
            await self._redis.expire(task_set_key, 3600)  # 1 hour
        
        # Queue key
        queue_key = f"{self.QUEUE_PREFIX}:{account_id or 'global'}"
        
        # Add to sorted set (score = priority, timestamp for FIFO within priority)
        score = -priority * 1_000_000_000 + datetime.utcnow().timestamp()
        await self._redis.zadd(queue_key, {task.to_json(): score})
        
        logger.debug(
            "Task enqueued",
            task_id=task_id,
            task_type=task_type.value,
            account_id=str(account_id) if account_id else None,
        )
        
        return task_id
    
    async def dequeue(
        self,
        account_id: Optional[UUID] = None,
        timeout: float = 1.0,
    ) -> Optional[Task]:
        """
        Get next task from queue.
        
        Args:
            account_id: Account-specific queue or global
            timeout: How long to wait
            
        Returns:
            Task if available, None otherwise
        """
        queue_key = f"{self.QUEUE_PREFIX}:{account_id or 'global'}"
        processing_key = f"{self.PROCESSING_PREFIX}:{account_id or 'global'}"
        
        # Atomically move from queue to processing
        result = await self._redis.zpopmin(queue_key, count=1)
        
        if not result:
            return None
        
        task_data, score = result[0]
        task = Task.from_json(task_data)
        
        # Add to processing set
        await self._redis.hset(
            processing_key,
            task.task_id,
            task.to_json(),
        )
        
        return task
    
    async def complete(
        self,
        task: Task,
        account_id: Optional[UUID] = None,
    ) -> None:
        """Mark task as completed."""
        processing_key = f"{self.PROCESSING_PREFIX}:{account_id or 'global'}"
        await self._redis.hdel(processing_key, task.task_id)
        
        logger.debug(
            "Task completed",
            task_id=task.task_id,
            task_type=task.task_type.value,
        )
    
    async def fail(
        self,
        task: Task,
        error: str,
        account_id: Optional[UUID] = None,
    ) -> None:
        """
        Handle task failure.
        
        Retries or moves to dead letter queue.
        """
        processing_key = f"{self.PROCESSING_PREFIX}:{account_id or 'global'}"
        await self._redis.hdel(processing_key, task.task_id)
        
        if task.retry_count < task.max_retries:
            # Retry
            task.retry_count += 1
            queue_key = f"{self.QUEUE_PREFIX}:{account_id or 'global'}"
            
            # Add back with delay (exponential backoff)
            delay = 2 ** task.retry_count * 10  # 20s, 40s, 80s
            score = datetime.utcnow().timestamp() + delay
            
            await self._redis.zadd(queue_key, {task.to_json(): score})
            
            logger.warning(
                "Task retry scheduled",
                task_id=task.task_id,
                retry=task.retry_count,
                delay=delay,
            )
        else:
            # Dead letter
            dead_key = f"{self.DEAD_LETTER_PREFIX}:{account_id or 'global'}"
            
            dead_data = {
                "task": task.to_json(),
                "error": error,
                "failed_at": datetime.utcnow().isoformat(),
            }
            
            await self._redis.lpush(dead_key, json.dumps(dead_data))
            await self._redis.ltrim(dead_key, 0, 999)  # Keep last 1000
            
            logger.error(
                "Task moved to dead letter",
                task_id=task.task_id,
                error=error,
            )
    
    async def get_queue_stats(
        self,
        account_id: Optional[UUID] = None,
    ) -> dict:
        """Get queue statistics."""
        queue_key = f"{self.QUEUE_PREFIX}:{account_id or 'global'}"
        processing_key = f"{self.PROCESSING_PREFIX}:{account_id or 'global'}"
        dead_key = f"{self.DEAD_LETTER_PREFIX}:{account_id or 'global'}"
        
        return {
            "queued": await self._redis.zcard(queue_key),
            "processing": await self._redis.hlen(processing_key),
            "dead": await self._redis.llen(dead_key),
        }
    
    async def process_loop(
        self,
        account_id: Optional[UUID] = None,
        poll_interval: float = 1.0,
    ) -> None:
        """
        Process tasks in a loop.
        
        Args:
            account_id: Process account-specific queue
            poll_interval: How often to check for tasks
        """
        self._running = True
        
        while self._running:
            try:
                task = await self.dequeue(account_id)
                
                if task is None:
                    await asyncio.sleep(poll_interval)
                    continue
                
                handler = self._handlers.get(task.task_type)
                
                if handler is None:
                    logger.warning(
                        "No handler for task type",
                        task_type=task.task_type.value,
                    )
                    await self.complete(task, account_id)
                    continue
                
                try:
                    await handler(task)
                    await self.complete(task, account_id)
                except Exception as e:
                    await self.fail(task, str(e), account_id)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Queue processing error", error=str(e))
                await asyncio.sleep(poll_interval)
        
        self._running = False
    
    def stop(self) -> None:
        """Stop the processing loop."""
        self._running = False


# Connection management
_redis_client: Optional[redis.Redis] = None
_queue_manager: Optional[QueueManager] = None


async def get_redis_client() -> redis.Redis:
    """Get or create Redis client."""
    global _redis_client
    
    if _redis_client is None:
        settings = get_settings()
        _redis_client = redis.from_url(
            settings.redis.url,
            encoding="utf-8",
            decode_responses=True,
        )
    
    return _redis_client


async def get_queue_manager() -> QueueManager:
    """Get or create queue manager."""
    global _queue_manager
    
    if _queue_manager is None:
        client = await get_redis_client()
        _queue_manager = QueueManager(client)
    
    return _queue_manager


async def close_redis() -> None:
    """Close Redis connection."""
    global _redis_client, _queue_manager
    
    if _queue_manager:
        _queue_manager.stop()
        _queue_manager = None
    
    if _redis_client:
        await _redis_client.close()
        _redis_client = None
