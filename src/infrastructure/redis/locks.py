"""
Redis distributed locks.

Provides distributed locking mechanism for coordinating
work across multiple instances.
"""

import asyncio
import uuid
from typing import Optional

import redis.asyncio as redis
import structlog

logger = structlog.get_logger(__name__)


class DistributedLock:
    """
    Redis-based distributed lock.
    
    Uses SET NX with expiration for safe distributed locking.
    Implements proper cleanup to prevent deadlocks.
    
    Usage:
        lock = DistributedLock(redis_client, "my-lock", timeout=30)
        if await lock.acquire():
            try:
                # do work
            finally:
                await lock.release()
    
    Or as async context manager:
        async with DistributedLock(redis_client, "my-lock") as acquired:
            if acquired:
                # do work
    """
    
    def __init__(
        self,
        redis_client: redis.Redis,
        lock_name: str,
        timeout: int = 30,
        retry_interval: float = 0.1,
        max_retries: int = 0,
    ):
        """
        Initialize distributed lock.
        
        Args:
            redis_client: Redis client instance
            lock_name: Unique lock identifier
            timeout: Lock expiration in seconds (prevents deadlocks)
            retry_interval: Seconds between acquire retries
            max_retries: Max acquire attempts (0 = no retry)
        """
        self._redis = redis_client
        self._lock_name = f"lock:{lock_name}"
        self._timeout = timeout
        self._retry_interval = retry_interval
        self._max_retries = max_retries
        self._token = str(uuid.uuid4())
        self._acquired = False
    
    @property
    def acquired(self) -> bool:
        """Check if lock is currently held."""
        return self._acquired
    
    async def acquire(self) -> bool:
        """
        Attempt to acquire the lock.
        
        Returns:
            True if lock acquired, False otherwise
        """
        attempts = 0
        
        while True:
            # Try to set lock with NX (only if not exists)
            result = await self._redis.set(
                self._lock_name,
                self._token,
                nx=True,
                ex=self._timeout,
            )
            
            if result:
                self._acquired = True
                logger.debug(
                    "Lock acquired",
                    lock=self._lock_name,
                    token=self._token[:8],
                )
                return True
            
            # Check if we should retry
            attempts += 1
            if attempts > self._max_retries:
                logger.debug(
                    "Could not acquire lock",
                    lock=self._lock_name,
                    attempts=attempts,
                )
                return False
            
            await asyncio.sleep(self._retry_interval)
    
    async def release(self) -> bool:
        """
        Release the lock.
        
        Uses Lua script to ensure we only release our own lock.
        
        Returns:
            True if released, False if lock was not held
        """
        if not self._acquired:
            return False
        
        # Lua script for atomic check-and-delete
        # Only deletes if the value matches our token
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        
        try:
            result = await self._redis.eval(
                lua_script,
                1,
                self._lock_name,
                self._token,
            )
            
            self._acquired = False
            
            if result:
                logger.debug(
                    "Lock released",
                    lock=self._lock_name,
                    token=self._token[:8],
                )
                return True
            else:
                logger.warning(
                    "Lock was not held (expired or stolen)",
                    lock=self._lock_name,
                )
                return False
                
        except Exception as e:
            logger.error(
                "Error releasing lock",
                lock=self._lock_name,
                error=str(e),
            )
            self._acquired = False
            return False
    
    async def extend(self, additional_time: int = None) -> bool:
        """
        Extend lock expiration time.
        
        Args:
            additional_time: Seconds to add (defaults to original timeout)
            
        Returns:
            True if extended, False if lock not held
        """
        if not self._acquired:
            return False
        
        time_to_add = additional_time or self._timeout
        
        # Lua script for atomic check-and-extend
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("expire", KEYS[1], ARGV[2])
        else
            return 0
        end
        """
        
        try:
            result = await self._redis.eval(
                lua_script,
                1,
                self._lock_name,
                self._token,
                time_to_add,
            )
            
            if result:
                logger.debug(
                    "Lock extended",
                    lock=self._lock_name,
                    seconds=time_to_add,
                )
                return True
            else:
                self._acquired = False
                return False
                
        except Exception as e:
            logger.error(
                "Error extending lock",
                lock=self._lock_name,
                error=str(e),
            )
            return False
    
    async def __aenter__(self) -> bool:
        """Async context manager entry."""
        return await self.acquire()
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.release()


class LockManager:
    """
    Manages multiple distributed locks.
    
    Provides convenience methods for common locking patterns.
    """
    
    def __init__(self, redis_client: redis.Redis):
        self._redis = redis_client
        self._active_locks: dict[str, DistributedLock] = {}
    
    def create_lock(
        self,
        name: str,
        timeout: int = 30,
        **kwargs,
    ) -> DistributedLock:
        """Create a new lock instance."""
        return DistributedLock(
            self._redis,
            name,
            timeout=timeout,
            **kwargs,
        )
    
    async def with_lock(
        self,
        name: str,
        timeout: int = 30,
    ) -> Optional[DistributedLock]:
        """
        Acquire a lock and return it, or None if unavailable.
        
        Caller is responsible for releasing.
        
        Args:
            name: Lock name
            timeout: Lock timeout
            
        Returns:
            Lock if acquired, None otherwise
        """
        lock = self.create_lock(name, timeout)
        
        if await lock.acquire():
            self._active_locks[name] = lock
            return lock
        
        return None
    
    async def release_all(self) -> None:
        """Release all active locks."""
        for lock in list(self._active_locks.values()):
            await lock.release()
        self._active_locks.clear()


# Singleton lock manager
_lock_manager: Optional[LockManager] = None


async def get_lock_manager() -> LockManager:
    """Get or create lock manager singleton."""
    global _lock_manager
    
    if _lock_manager is None:
        from src.infrastructure.redis import get_redis_client
        client = await get_redis_client()
        _lock_manager = LockManager(client)
    
    return _lock_manager
