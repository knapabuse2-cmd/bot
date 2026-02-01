"""
Redis infrastructure module.

Provides:
- Task queuing with priority and retry logic
- Distributed locking for coordination
- Connection management
"""

from .queue import (
    Task,
    TaskType,
    QueueManager,
    get_redis_client,
    get_queue_manager,
    close_redis,
)
from .locks import (
    DistributedLock,
    LockManager,
    get_lock_manager,
)

__all__ = [
    # Queue
    "Task",
    "TaskType",
    "QueueManager",
    "get_redis_client",
    "get_queue_manager",
    "close_redis",
    # Locks
    "DistributedLock",
    "LockManager",
    "get_lock_manager",
]
