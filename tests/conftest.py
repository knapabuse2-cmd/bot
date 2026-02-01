"""
Pytest configuration and shared fixtures.
"""

import asyncio
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.infrastructure.database.connection import Base


# ============================================================
# Event Loop
# ============================================================

@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ============================================================
# Database Fixtures
# ============================================================

@pytest_asyncio.fixture
async def async_engine():
    """Create async SQLite engine for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create database session for testing."""
    async_session_factory = sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    async with async_session_factory() as session:
        yield session
        await session.rollback()


# ============================================================
# Mock Fixtures
# ============================================================

@pytest.fixture
def mock_redis():
    """Create mock Redis client."""
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value=None)
    redis.delete = AsyncMock(return_value=1)
    redis.zadd = AsyncMock(return_value=1)
    redis.zpopmin = AsyncMock(return_value=[])
    redis.hset = AsyncMock(return_value=1)
    redis.hdel = AsyncMock(return_value=1)
    redis.eval = AsyncMock(return_value=1)
    redis.sismember = AsyncMock(return_value=False)
    redis.sadd = AsyncMock(return_value=1)
    redis.expire = AsyncMock(return_value=True)
    redis.close = AsyncMock()
    return redis


@pytest.fixture
def mock_ai_provider():
    """Create mock AI provider."""
    from src.infrastructure.ai import AIResponse
    
    provider = AsyncMock()
    provider.generate = AsyncMock(return_value=AIResponse(
        content="Test response",
        model="gpt-4o-mini",
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
    ))
    provider.check_health = AsyncMock(return_value=True)
    provider.close = AsyncMock()
    return provider


@pytest.fixture
def mock_telegram_client():
    """Create mock Telegram client."""
    client = AsyncMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.send_message = AsyncMock(return_value=12345)
    client.connected = True
    return client


# ============================================================
# Domain Entity Factories
# ============================================================

@pytest.fixture
def account_factory():
    """Factory for creating test Account entities."""
    from src.domain.entities import Account, AccountStatus, AccountSchedule, AccountLimits
    
    def create(
        phone: str = "+79001234567",
        status: AccountStatus = AccountStatus.ACTIVE,
        **kwargs,
    ) -> Account:
        return Account(
            id=kwargs.get("id", uuid4()),
            phone=phone,
            status=status,
            session_data=kwargs.get("session_data", b"test_session"),
            schedule=kwargs.get("schedule", AccountSchedule()),
            limits=kwargs.get("limits", AccountLimits()),
            **{k: v for k, v in kwargs.items() 
               if k not in ("id", "session_data", "schedule", "limits")},
        )
    
    return create


@pytest.fixture
def campaign_factory():
    """Factory for creating test Campaign entities."""
    from src.domain.entities import Campaign, CampaignStatus, CampaignGoal, CampaignPrompt
    
    def create(
        name: str = "Test Campaign",
        status: CampaignStatus = CampaignStatus.ACTIVE,
        **kwargs,
    ) -> Campaign:
        return Campaign(
            id=kwargs.get("id", uuid4()),
            name=name,
            status=status,
            goal=kwargs.get("goal", CampaignGoal()),
            prompt=kwargs.get("prompt", CampaignPrompt()),
            **{k: v for k, v in kwargs.items()
               if k not in ("id", "goal", "prompt")},
        )
    
    return create


@pytest.fixture
def dialogue_factory():
    """Factory for creating test Dialogue entities."""
    from src.domain.entities import Dialogue, DialogueStatus
    
    def create(
        account_id: uuid4 = None,
        campaign_id: uuid4 = None,
        telegram_user_id: int = 12345,
        status: DialogueStatus = DialogueStatus.ACTIVE,
        **kwargs,
    ) -> Dialogue:
        return Dialogue(
            id=kwargs.get("id", uuid4()),
            account_id=account_id or uuid4(),
            campaign_id=campaign_id or uuid4(),
            telegram_user_id=telegram_user_id,
            status=status,
            **{k: v for k, v in kwargs.items() if k != "id"},
        )
    
    return create


@pytest.fixture
def target_factory():
    """Factory for creating test UserTarget entities."""
    from src.domain.entities import UserTarget, TargetStatus
    
    def create(
        campaign_id: uuid4 = None,
        telegram_id: int = 12345,
        status: TargetStatus = TargetStatus.PENDING,
        **kwargs,
    ) -> UserTarget:
        return UserTarget(
            id=kwargs.get("id", uuid4()),
            campaign_id=campaign_id or uuid4(),
            telegram_id=telegram_id,
            status=status,
            **{k: v for k, v in kwargs.items() if k != "id"},
        )
    
    return create


# ============================================================
# Settings Override
# ============================================================

@pytest.fixture(autouse=True)
def override_settings(monkeypatch):
    """Override settings for testing."""
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "test_hash")
    monkeypatch.setenv("TELEGRAM_ADMIN_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("TELEGRAM_ADMIN_USER_IDS", "123")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SECURITY_SESSION_ENCRYPTION_KEY", 
                       "dGVzdF9rZXlfMzJfYnl0ZXNfbG9uZ19fXw==")
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_DATABASE", "test")
