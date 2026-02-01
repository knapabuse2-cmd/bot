"""
Worker Manager entry point.

Runs the worker manager that orchestrates all account workers.
"""

import asyncio
import logging
import signal
import sys
from typing import Optional

import structlog

from src.config import get_settings
from src.infrastructure.database import init_database, close_database
from src.infrastructure.ai import close_ai_provider
from src.infrastructure.redis import close_redis

from .manager import WorkerManager, get_worker_manager, shutdown_manager

logger = structlog.get_logger(__name__)

# Global manager reference for signal handlers
_manager: Optional[WorkerManager] = None


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
    logging.getLogger("telethon").setLevel(logging.ERROR)  # Hide connection warnings
    logging.getLogger("telethon.network").setLevel(logging.ERROR)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.ERROR)  # Hide "Task was destroyed" warnings


async def shutdown(signal_type: signal.Signals) -> None:
    """Handle shutdown signal."""
    logger.info(f"Received signal {signal_type.name}, shutting down...")
    
    global _manager
    if _manager:
        await _manager.stop()


def setup_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    """Setup signal handlers for graceful shutdown."""
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda s=sig: asyncio.create_task(shutdown(s)),
        )


async def main() -> None:
    """Main entry point."""
    global _manager
    
    setup_logging()
    
    logger.info("Starting Worker Manager")
    
    try:
        # Initialize database
        await init_database()
        logger.info("Database initialized")
        
        # Get worker manager
        _manager = get_worker_manager()
        
        # Setup signal handlers (Unix only)
        if sys.platform != "win32":
            loop = asyncio.get_running_loop()
            setup_signal_handlers(loop)
        
        # Start manager
        await _manager.start()
        
        # Keep running until stopped
        while _manager.running:
            await asyncio.sleep(1)
        
    except asyncio.CancelledError:
        logger.info("Worker manager cancelled")
    except Exception as e:
        logger.error("Worker manager error", error=str(e))
        raise
    finally:
        # Cleanup
        logger.info("Cleaning up...")
        
        await shutdown_manager()
        await close_ai_provider()
        await close_redis()
        await close_database()
        
        logger.info("Worker manager stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
