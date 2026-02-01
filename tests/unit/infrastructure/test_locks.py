"""
Unit tests for Redis distributed locks.
"""

import pytest
from unittest.mock import AsyncMock, patch

from src.infrastructure.redis.locks import DistributedLock, LockManager


class TestDistributedLock:
    """Tests for DistributedLock."""
    
    @pytest.fixture
    def lock(self, mock_redis):
        """Create lock instance with mock Redis."""
        return DistributedLock(
            mock_redis,
            "test-lock",
            timeout=30,
        )
    
    @pytest.mark.asyncio
    async def test_acquire_success(self, lock, mock_redis):
        """Test successful lock acquisition."""
        mock_redis.set = AsyncMock(return_value=True)
        
        result = await lock.acquire()
        
        assert result is True
        assert lock.acquired is True
        mock_redis.set.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_acquire_failure(self, lock, mock_redis):
        """Test failed lock acquisition."""
        mock_redis.set = AsyncMock(return_value=False)
        
        result = await lock.acquire()
        
        assert result is False
        assert lock.acquired is False
    
    @pytest.mark.asyncio
    async def test_release_success(self, lock, mock_redis):
        """Test successful lock release."""
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.eval = AsyncMock(return_value=1)
        
        # Acquire first
        await lock.acquire()
        
        # Then release
        result = await lock.release()
        
        assert result is True
        assert lock.acquired is False
    
    @pytest.mark.asyncio
    async def test_release_without_acquire(self, lock, mock_redis):
        """Test release without prior acquire."""
        result = await lock.release()
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_release_expired_lock(self, lock, mock_redis):
        """Test release when lock has expired."""
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.eval = AsyncMock(return_value=0)  # Lock not held
        
        await lock.acquire()
        result = await lock.release()
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_extend_success(self, lock, mock_redis):
        """Test successful lock extension."""
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.eval = AsyncMock(return_value=1)
        
        await lock.acquire()
        result = await lock.extend(60)
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_extend_without_lock(self, lock, mock_redis):
        """Test extend without holding lock."""
        result = await lock.extend(60)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_context_manager_acquire(self, mock_redis):
        """Test using lock as context manager."""
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.eval = AsyncMock(return_value=1)
        
        lock = DistributedLock(mock_redis, "test-lock")
        
        async with lock as acquired:
            assert acquired is True
            assert lock.acquired is True
        
        # Should be released after context
        assert lock.acquired is False
    
    @pytest.mark.asyncio
    async def test_context_manager_acquire_failure(self, mock_redis):
        """Test context manager when acquire fails."""
        mock_redis.set = AsyncMock(return_value=False)
        
        lock = DistributedLock(mock_redis, "test-lock")
        
        async with lock as acquired:
            assert acquired is False
    
    @pytest.mark.asyncio
    async def test_acquire_with_retry(self, mock_redis):
        """Test acquire with retries."""
        # Fail first, succeed second
        mock_redis.set = AsyncMock(side_effect=[False, True])
        
        lock = DistributedLock(
            mock_redis,
            "test-lock",
            max_retries=2,
            retry_interval=0.01,
        )
        
        result = await lock.acquire()
        
        assert result is True
        assert mock_redis.set.call_count == 2


class TestLockManager:
    """Tests for LockManager."""
    
    @pytest.fixture
    def manager(self, mock_redis):
        """Create lock manager with mock Redis."""
        return LockManager(mock_redis)
    
    def test_create_lock(self, manager):
        """Test creating a lock."""
        lock = manager.create_lock("test-lock", timeout=60)
        
        assert lock is not None
        assert lock._lock_name == "lock:test-lock"
    
    @pytest.mark.asyncio
    async def test_with_lock_success(self, manager, mock_redis):
        """Test with_lock acquiring successfully."""
        mock_redis.set = AsyncMock(return_value=True)
        
        lock = await manager.with_lock("test-lock")
        
        assert lock is not None
        assert lock.acquired is True
    
    @pytest.mark.asyncio
    async def test_with_lock_failure(self, manager, mock_redis):
        """Test with_lock when acquire fails."""
        mock_redis.set = AsyncMock(return_value=False)
        
        lock = await manager.with_lock("test-lock")
        
        assert lock is None
    
    @pytest.mark.asyncio
    async def test_release_all(self, manager, mock_redis):
        """Test releasing all locks."""
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.eval = AsyncMock(return_value=1)
        
        # Acquire some locks
        await manager.with_lock("lock1")
        await manager.with_lock("lock2")
        
        assert len(manager._active_locks) == 2
        
        # Release all
        await manager.release_all()
        
        assert len(manager._active_locks) == 0
