"""
Database connection management.

Provides async session factory and connection pool configuration
for SQLAlchemy 2.0 with asyncpg.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from src.config import get_settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


# Engine instance (created lazily)
_engine = None
_session_factory = None


def get_engine():
    """
    Get or create the async database engine.
    
    Returns:
        AsyncEngine instance
    """
    global _engine
    
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database.async_url,
            pool_size=settings.database.pool_size,
            max_overflow=settings.database.pool_max_overflow,
            echo=settings.database.echo,
            pool_pre_ping=True,  # Verify connections before use
        )
    
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """
    Get or create the async session factory.
    
    Returns:
        Async session factory
    """
    global _session_factory
    
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Get an async database session.
    
    Usage:
        async with get_session() as session:
            # Use session
            
    Yields:
        AsyncSession instance
    """
    factory = get_session_factory()
    session = factory()
    
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def init_database() -> None:
    """
    Initialize database tables.
    
    Creates all tables defined in models if they don't exist.
    Should be called on application startup.
    """
    engine = get_engine()
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_database() -> None:
    """
    Close database connections.
    
    Should be called on application shutdown.
    """
    global _engine, _session_factory
    
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None

# Ensure ORM models are imported so Base.metadata is populated (important for tests).
from . import models  # noqa: F401
