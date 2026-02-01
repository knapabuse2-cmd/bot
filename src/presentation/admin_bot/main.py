"""
Admin Bot entry point.

Telegram bot for managing the outreach system.

FIXED:
- Added close_redis() to shutdown
- Better error handling
- Graceful shutdown on signals
"""

import asyncio
import logging
import signal
import sys
from typing import Optional

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.exceptions import TelegramBadRequest

from src.config import get_settings
from src.infrastructure.database import init_database, close_database
from src.infrastructure.ai import close_ai_provider
from src.infrastructure.redis import close_redis, get_redis_client

from .handlers import register_all_handlers
from .middlewares import register_middlewares

logger = structlog.get_logger(__name__)

# Global bot instance for signal handlers
_bot: Optional[Bot] = None
_dp: Optional[Dispatcher] = None


async def on_startup(bot: Bot) -> None:
    """Actions on bot startup."""
    await init_database()
    
    # Get bot info
    bot_info = await bot.get_me()
    logger.info(
        "Bot started",
        username=bot_info.username,
        id=bot_info.id,
    )


async def on_shutdown(bot: Bot) -> None:
    """Actions on bot shutdown."""
    logger.info("Shutting down bot...")
    
    # Close all connections in proper order
    try:
        await close_ai_provider()
        logger.debug("AI provider closed")
    except Exception as e:
        logger.error("Error closing AI provider", error=str(e))
    
    try:
        await close_redis()
        logger.debug("Redis closed")
    except Exception as e:
        logger.error("Error closing Redis", error=str(e))
    
    try:
        await close_database()
        logger.debug("Database closed")
    except Exception as e:
        logger.error("Error closing database", error=str(e))
    
    logger.info("Bot stopped")


def create_bot() -> Bot:
    """Create and configure bot instance."""
    settings = get_settings()
    
    return Bot(
        token=settings.telegram.admin_bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def create_dispatcher() -> Dispatcher:
    """Create and configure dispatcher."""
    settings = get_settings()

    # Use Redis storage if available, fallback to memory
    try:
        redis_client = await get_redis_client()
        storage = RedisStorage(redis_client)
        logger.info("Using Redis FSM storage")
    except Exception as e:
        logger.warning(
            "Redis not available, using memory storage",
            error=str(e),
        )
        storage = MemoryStorage()

    dp = Dispatcher(storage=storage)

    # Register global error handler
    @dp.error()
    async def global_error_handler(event, exception):
        """Handle common errors silently."""
        if isinstance(exception, TelegramBadRequest):
            error_text = str(exception).lower()
            # Ignore "query is too old" - happens when callback takes too long
            if "query is too old" in error_text:
                logger.debug("Callback query expired (normal)", error=str(exception))
                return True
            # Ignore "message is not modified" - happens on duplicate edits
            if "message is not modified" in error_text:
                logger.debug("Message not modified (normal)", error=str(exception))
                return True
            # Ignore "message to edit not found" - happens when message was deleted
            if "message to edit not found" in error_text:
                logger.debug("Message to edit not found", error=str(exception))
                return True

        # Log other errors
        logger.error("Unhandled error in handler", error=str(exception), exc_info=True)
        return False

    # Register handlers and middlewares
    register_middlewares(dp)
    register_all_handlers(dp)

    return dp


def setup_logging() -> None:
    """Configure structured logging."""
    settings = get_settings()
    
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
            if settings.log_format == "json"
            else structlog.dev.ConsoleRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Configure standard logging
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )
    
    # Suppress noisy loggers
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


async def shutdown(signal_type: signal.Signals) -> None:
    """Handle shutdown signal."""
    logger.info(f"Received signal {signal_type.name}, shutting down...")
    
    if _dp:
        await _dp.stop_polling()


def setup_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    """Setup signal handlers for graceful shutdown."""
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda s=sig: asyncio.create_task(shutdown(s)),
        )


async def main() -> None:
    """Main entry point."""
    global _bot, _dp
    
    setup_logging()
    
    logger.info("Starting Telegram Outreach Admin Bot")
    
    _bot = create_bot()
    _dp = await create_dispatcher()
    
    # Register startup/shutdown hooks
    _dp.startup.register(on_startup)
    _dp.shutdown.register(on_shutdown)
    
    try:
        # Setup signal handlers (Unix only)
        if sys.platform != "win32":
            loop = asyncio.get_running_loop()
            setup_signal_handlers(loop)
        
        # Start polling
        await _dp.start_polling(
            _bot,
            allowed_updates=_dp.resolve_used_update_types(),
        )
    except asyncio.CancelledError:
        logger.info("Bot polling cancelled")
    except Exception as e:
        logger.error("Bot error", error=str(e))
        raise
    finally:
        await _bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
