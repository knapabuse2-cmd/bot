"""
Bot middlewares.

Handles:
- Admin access control
- Database session injection
- Logging
"""

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware, Dispatcher
from aiogram.types import Message, CallbackQuery, TelegramObject

import structlog

from src.config import get_settings
from src.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


class AdminAccessMiddleware(BaseMiddleware):
    """
    Middleware to check admin access.
    
    Only allows users listed in TELEGRAM_ADMIN_USER_IDS.
    """
    
    def __init__(self):
        settings = get_settings()
        self.admin_ids = settings.telegram.admin_user_ids
        # Debug: log loaded admin IDs
        logger.info(
            "AdminAccessMiddleware initialized",
            admin_ids=self.admin_ids,
            raw_value=settings.telegram.admin_user_ids_raw,
        )
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Get user from event
        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user
        
        if user is None:
            return
        
        # Check admin access (re-read settings in case env changed)
        admin_ids = get_settings().telegram.admin_user_ids
        
        if user.id not in admin_ids:
            logger.warning(
                "Unauthorized access attempt",
                user_id=user.id,
                username=user.username,
                allowed_ids=admin_ids,
            )
            
            if isinstance(event, Message):
                await event.answer(
                    "⛔ Доступ запрещён.\n"
                    "Вы не являетесь администратором системы."
                )
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔ Доступ запрещён", show_alert=True)
            
            return
        
        # Add user info to data
        data["admin_user"] = user
        
        return await handler(event, data)


class DatabaseMiddleware(BaseMiddleware):
    """
    Middleware to inject database session.
    
    Provides async session to handlers via data dict.
    """
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        async with get_session() as session:
            data["session"] = session
            return await handler(event, data)


class LoggingMiddleware(BaseMiddleware):
    """Middleware for request logging."""
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = None
        event_type = type(event).__name__
        
        if isinstance(event, Message):
            user = event.from_user
            text = event.text[:50] if event.text else "<no text>"
            logger.debug(
                "Message received",
                user_id=user.id if user else None,
                text=text,
            )
        elif isinstance(event, CallbackQuery):
            user = event.from_user
            logger.debug(
                "Callback received",
                user_id=user.id if user else None,
                data=event.data,
            )
        
        return await handler(event, data)


def register_middlewares(dp: Dispatcher) -> None:
    """Register all middlewares."""
    # Order matters - first registered = first executed
    dp.message.middleware(LoggingMiddleware())
    dp.message.middleware(AdminAccessMiddleware())
    dp.message.middleware(DatabaseMiddleware())
    
    dp.callback_query.middleware(LoggingMiddleware())
    dp.callback_query.middleware(AdminAccessMiddleware())
    dp.callback_query.middleware(DatabaseMiddleware())
