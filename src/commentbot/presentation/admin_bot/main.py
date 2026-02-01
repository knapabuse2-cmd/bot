"""Main entry point for comment bot admin."""

import asyncio
from pathlib import Path

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.commentbot.config import get_config
from src.commentbot.infrastructure.database.models import Base
from src.commentbot.presentation.admin_bot.handlers import accounts, common, campaigns

logger = structlog.get_logger(__name__)


async def create_db_engine():
    """Create database engine and tables."""
    config = get_config()

    # Ensure data directory exists
    db_path = Path(config.db_sqlite_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(
        config.database_url,
        echo=False,
    )

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    return engine


def create_session_maker(engine):
    """Create session maker."""
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


class DatabaseMiddleware:
    """Middleware to inject database session."""

    def __init__(self, session_maker):
        self.session_maker = session_maker

    async def __call__(self, handler, event, data):
        async with self.session_maker() as session:
            data["session"] = session
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise


async def main():
    """Run the bot."""
    config = get_config()

    # Setup logging
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(config.log_level),
    )

    logger.info("Starting Comment Bot Admin...")

    # Create database
    engine = await create_db_engine()
    session_maker = create_session_maker(engine)

    # Create bot and dispatcher
    bot = Bot(
        token=config.commentbot_bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Add middleware
    dp.message.outer_middleware(DatabaseMiddleware(session_maker))
    dp.callback_query.outer_middleware(DatabaseMiddleware(session_maker))

    # Register handlers (order matters - specific handlers before common)
    dp.include_router(accounts.router)
    dp.include_router(campaigns.router)
    dp.include_router(common.router)

    # Start polling
    logger.info("Bot started, polling...")

    try:
        await dp.start_polling(bot)
    finally:
        await engine.dispose()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
