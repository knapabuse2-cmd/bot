"""
Premium subscription purchase service.

Handles purchasing Telegram Premium via @PremiumBot with card payment.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import (
    GetBotCallbackAnswerRequest,
    StartBotRequest,
)
from telethon.tl.types import (
    KeyboardButtonCallback,
    KeyboardButtonUrl,
    KeyboardButtonWebView,
    ReplyInlineMarkup,
    Message,
)
import python_socks

from src.config import get_settings
from src.domain.entities import Account

logger = logging.getLogger(__name__)


@dataclass
class PremiumPurchaseResult:
    """Result of premium purchase attempt."""
    success: bool
    payment_url: Optional[str] = None
    error: Optional[str] = None
    message: Optional[str] = None


class PremiumService:
    """Service for purchasing Telegram Premium."""

    PREMIUM_BOT_USERNAME = "PremiumBot"

    # Button text patterns (may vary by language)
    SUBSCRIBE_PATTERNS = [
        "Subscribe", "Подписаться", "Оформить подписку",
        "Get Premium", "Получить Premium", "🌟",
    ]
    ONE_MONTH_PATTERNS = [
        "1 month", "1 месяц", "месяц", "month",
        "12", "1 мес", "Monthly",
    ]
    CARD_PATTERNS = [
        "Card", "Карта", "💳", "Bank card", "Банковская карта",
        "Credit card", "Debit card", "Кредитная", "Дебетовая",
    ]

    def __init__(self):
        self.settings = get_settings()

    async def purchase_premium(
        self,
        account: Account,
        proxy_host: Optional[str] = None,
        proxy_port: Optional[int] = None,
        proxy_username: Optional[str] = None,
        proxy_password: Optional[str] = None,
    ) -> PremiumPurchaseResult:
        """
        Start premium purchase flow for account.

        Returns payment URL for 3DS confirmation.
        """
        if not account.session_data:
            return PremiumPurchaseResult(
                success=False,
                error="Account has no session data"
            )

        # Build proxy config
        proxy_dict = None
        if proxy_host and proxy_port:
            proxy_dict = {
                'proxy_type': python_socks.ProxyType.SOCKS5,
                'addr': proxy_host,
                'port': proxy_port,
                'username': proxy_username,
                'password': proxy_password,
                'rdns': True,
            }

        # Get session string
        session_string = account.session_data
        if isinstance(session_string, bytes):
            session_string = session_string.decode('utf-8')

        client = TelegramClient(
            StringSession(session_string),
            self.settings.telegram.api_id,
            self.settings.telegram.api_hash.get_secret_value(),
            proxy=proxy_dict,
        )

        try:
            await client.connect()

            if not await client.is_user_authorized():
                return PremiumPurchaseResult(
                    success=False,
                    error="Account session is invalid"
                )

            # Get @PremiumBot entity
            try:
                premium_bot = await client.get_entity(self.PREMIUM_BOT_USERNAME)
            except Exception as e:
                return PremiumPurchaseResult(
                    success=False,
                    error=f"Could not find @{self.PREMIUM_BOT_USERNAME}: {e}"
                )

            # Start conversation with bot
            logger.info(f"Starting conversation with @{self.PREMIUM_BOT_USERNAME}")

            await client(StartBotRequest(
                bot=premium_bot,
                peer=premium_bot,
                start_param=""
            ))

            # Wait for bot response
            await asyncio.sleep(2)

            # Get bot messages
            messages = await client.get_messages(premium_bot, limit=5)

            if not messages:
                return PremiumPurchaseResult(
                    success=False,
                    error="No response from @PremiumBot"
                )

            # Find subscribe button
            subscribe_button = None
            target_message = None

            for msg in messages:
                if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
                    for row in msg.reply_markup.rows:
                        for button in row.buttons:
                            if isinstance(button, KeyboardButtonCallback):
                                if any(p.lower() in button.text.lower() for p in self.SUBSCRIBE_PATTERNS):
                                    subscribe_button = button
                                    target_message = msg
                                    break
                        if subscribe_button:
                            break
                if subscribe_button:
                    break

            if not subscribe_button:
                return PremiumPurchaseResult(
                    success=False,
                    error="Could not find Subscribe button in @PremiumBot"
                )

            # Click subscribe button
            logger.info("Clicking Subscribe button")
            await client(GetBotCallbackAnswerRequest(
                peer=premium_bot,
                msg_id=target_message.id,
                data=subscribe_button.data,
            ))

            await asyncio.sleep(2)

            # Get updated messages to find duration selection
            messages = await client.get_messages(premium_bot, limit=5)

            # Find 1 month button
            month_button = None
            target_message = None

            for msg in messages:
                if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
                    for row in msg.reply_markup.rows:
                        for button in row.buttons:
                            if isinstance(button, KeyboardButtonCallback):
                                if any(p.lower() in button.text.lower() for p in self.ONE_MONTH_PATTERNS):
                                    month_button = button
                                    target_message = msg
                                    break
                        if month_button:
                            break
                if month_button:
                    break

            if not month_button:
                # Try to find any duration button that looks like 1 month
                for msg in messages:
                    if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
                        for row in msg.reply_markup.rows:
                            for button in row.buttons:
                                if isinstance(button, KeyboardButtonCallback):
                                    # First button in first row is usually 1 month
                                    month_button = button
                                    target_message = msg
                                    break
                            if month_button:
                                break
                    if month_button:
                        break

            if not month_button:
                return PremiumPurchaseResult(
                    success=False,
                    error="Could not find 1 month option"
                )

            # Click 1 month button
            logger.info("Selecting 1 month subscription")
            await client(GetBotCallbackAnswerRequest(
                peer=premium_bot,
                msg_id=target_message.id,
                data=month_button.data,
            ))

            await asyncio.sleep(2)

            # Get updated messages to find payment method
            messages = await client.get_messages(premium_bot, limit=5)

            # Find card payment button or WebView
            payment_url = None
            card_button = None
            target_message = None

            for msg in messages:
                if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
                    for row in msg.reply_markup.rows:
                        for button in row.buttons:
                            # Check for WebView (card input form)
                            if isinstance(button, KeyboardButtonWebView):
                                if any(p.lower() in button.text.lower() for p in self.CARD_PATTERNS):
                                    payment_url = button.url
                                    break
                            # Check for URL button
                            elif isinstance(button, KeyboardButtonUrl):
                                if any(p.lower() in button.text.lower() for p in self.CARD_PATTERNS):
                                    payment_url = button.url
                                    break
                            # Check for callback button to select card payment
                            elif isinstance(button, KeyboardButtonCallback):
                                if any(p.lower() in button.text.lower() for p in self.CARD_PATTERNS):
                                    card_button = button
                                    target_message = msg
                                    break
                        if payment_url:
                            break
                    if payment_url:
                        break
                if payment_url:
                    break

            # If found callback button for card, click it
            if card_button and not payment_url:
                logger.info("Selecting card payment method")
                await client(GetBotCallbackAnswerRequest(
                    peer=premium_bot,
                    msg_id=target_message.id,
                    data=card_button.data,
                ))

                await asyncio.sleep(2)

                # Get updated messages to find payment URL
                messages = await client.get_messages(premium_bot, limit=5)

                for msg in messages:
                    if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
                        for row in msg.reply_markup.rows:
                            for button in row.buttons:
                                if isinstance(button, (KeyboardButtonWebView, KeyboardButtonUrl)):
                                    # Any URL/WebView at this point is likely the payment
                                    if hasattr(button, 'url'):
                                        payment_url = button.url
                                        break
                            if payment_url:
                                break
                    if payment_url:
                        break

            if payment_url:
                return PremiumPurchaseResult(
                    success=True,
                    payment_url=payment_url,
                    message="Payment URL generated. Complete 3DS verification to activate Premium."
                )
            else:
                # Get last message text for debugging
                last_msg_text = messages[0].text if messages else "No messages"
                return PremiumPurchaseResult(
                    success=False,
                    error=f"Could not find payment URL. Last message: {last_msg_text[:200]}"
                )

        except Exception as e:
            logger.exception("Error during premium purchase")
            return PremiumPurchaseResult(
                success=False,
                error=str(e)
            )
        finally:
            await client.disconnect()

    async def check_premium_status(self, account: Account) -> bool:
        """Check if account has active Premium subscription."""
        if not account.session_data:
            return False

        session_string = account.session_data
        if isinstance(session_string, bytes):
            session_string = session_string.decode('utf-8')

        client = TelegramClient(
            StringSession(session_string),
            self.settings.telegram.api_id,
            self.settings.telegram.api_hash.get_secret_value(),
        )

        try:
            await client.connect()

            if not await client.is_user_authorized():
                return False

            me = await client.get_me()
            return getattr(me, 'premium', False)

        except Exception:
            return False
        finally:
            await client.disconnect()
