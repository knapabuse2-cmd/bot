"""
Telegram alerts service.

Sends notifications to admin users about important events.

Anti-detection: Uses proxy for all outgoing requests to avoid
exposing the server's real IP to Telegram.
"""

import asyncio
import random
from typing import Optional

import aiohttp
import python_socks
import structlog
from aiohttp_socks import ProxyConnector

from src.config.settings import get_settings

logger = structlog.get_logger(__name__)


class TelegramAlertService:
    """
    Service for sending alerts to Telegram admins.

    Uses raw HTTP API to avoid dependency on aiogram in worker process.
    Anti-detection: Routes requests through proxy to hide server IP.
    """

    def __init__(self):
        self._settings = get_settings()
        self._bot_token = self._settings.telegram.admin_bot_token.get_secret_value()
        self._admin_ids = self._settings.telegram.admin_user_ids
        self._base_url = f"https://api.telegram.org/bot{self._bot_token}"
        self._session: Optional[aiohttp.ClientSession] = None
        self._connector: Optional[ProxyConnector] = None

    async def _get_random_proxy(self) -> Optional[dict]:
        """
        Get a random active proxy from the database.

        Returns:
            Proxy config dict or None if no proxies available
        """
        try:
            from src.infrastructure.database import get_session
            from src.infrastructure.database.repositories import PostgresProxyRepository
            from src.domain.entities import ProxyStatus

            async with get_session() as session:
                proxy_repo = PostgresProxyRepository(session)
                proxies = await proxy_repo.list_available()

                # Filter for active/slow proxies
                healthy_proxies = [
                    p for p in proxies
                    if p.status in (ProxyStatus.ACTIVE, ProxyStatus.SLOW, ProxyStatus.UNKNOWN)
                ]

                if not healthy_proxies:
                    return None

                proxy = random.choice(healthy_proxies)

                proxy_type_map = {
                    "socks5": python_socks.ProxyType.SOCKS5,
                    "socks4": python_socks.ProxyType.SOCKS4,
                    "http": python_socks.ProxyType.HTTP,
                    "https": python_socks.ProxyType.HTTP,
                }

                return {
                    "proxy_type": proxy_type_map.get(proxy.proxy_type.value, python_socks.ProxyType.SOCKS5),
                    "host": proxy.host,
                    "port": proxy.port,
                    "username": proxy.username,
                    "password": proxy.password,
                }

        except Exception as e:
            logger.warning("Failed to get proxy for alerts", error=str(e))
            return None

    async def _get_session(self) -> Optional[aiohttp.ClientSession]:
        """
        Get or create aiohttp session with proxy support.

        Returns None if no proxy is available (no fallback to direct connection).
        """
        if self._session is None or self._session.closed:
            # Try to get a proxy - NO FALLBACK to direct connection
            proxy_config = await self._get_random_proxy()

            if not proxy_config:
                logger.warning("No proxy available for alerts, skipping")
                return None

            try:
                self._connector = ProxyConnector(
                    proxy_type=proxy_config["proxy_type"],
                    host=proxy_config["host"],
                    port=proxy_config["port"],
                    username=proxy_config.get("username"),
                    password=proxy_config.get("password"),
                    rdns=True,
                )
                self._session = aiohttp.ClientSession(connector=self._connector)
                logger.debug(
                    "Alert service using proxy",
                    host=proxy_config["host"],
                    port=proxy_config["port"],
                )
            except Exception as e:
                logger.warning("Failed to create proxy connector for alerts", error=str(e))
                return None

        return self._session

    async def close(self) -> None:
        """Close the session and connector."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        if self._connector:
            await self._connector.close()
            self._connector = None

    async def _rotate_session(self) -> None:
        """Close current session and get new one with different proxy."""
        await self.close()
        # Next _get_session() call will create new session with new proxy

    async def send_alert(self, message: str, parse_mode: str = "HTML") -> bool:
        """
        Send alert to all admin users.

        Args:
            message: Alert message text
            parse_mode: Telegram parse mode (HTML, Markdown, etc.)

        Returns:
            True if sent to at least one admin
        """
        if not self._admin_ids:
            logger.warning("No admin IDs configured for alerts")
            return False

        success_count = 0
        retry_count = 0
        max_retries = 2

        for admin_id in self._admin_ids:
            sent = False
            for attempt in range(max_retries + 1):
                try:
                    session = await self._get_session()
                    if session is None:
                        logger.warning("Cannot send alert - no proxy available")
                        return False

                    async with session.post(
                        f"{self._base_url}/sendMessage",
                        json={
                            "chat_id": admin_id,
                            "text": message,
                            "parse_mode": parse_mode,
                        },
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as response:
                        if response.status == 200:
                            success_count += 1
                            sent = True
                            break
                        else:
                            data = await response.json()
                            logger.warning(
                                "Failed to send alert",
                                admin_id=admin_id,
                                status=response.status,
                                error=data.get("description"),
                                attempt=attempt + 1,
                            )
                except Exception as e:
                    logger.error(
                        "Error sending alert",
                        admin_id=admin_id,
                        error=str(e),
                        attempt=attempt + 1,
                    )
                    # Rotate to different proxy on connection error
                    if attempt < max_retries:
                        await self._rotate_session()
                        await asyncio.sleep(1)

            if not sent:
                retry_count += 1

        return success_count > 0

    async def alert_account_error(
        self,
        phone: str,
        error: str,
        account_id: str,
    ) -> bool:
        """
        Send alert about account error.

        Args:
            phone: Account phone number
            error: Error message
            account_id: Account UUID
        """
        # Truncate error if too long
        if len(error) > 500:
            error = error[:500] + "..."

        message = (
            f"⚠️ <b>Аккаунт отвалился!</b>\n\n"
            f"📱 <b>Телефон:</b> <code>{phone}</code>\n"
            f"🆔 <b>ID:</b> <code>{account_id}</code>\n\n"
            f"❌ <b>Ошибка:</b>\n<code>{error}</code>\n\n"
            f"💡 Рассылка продолжается на других аккаунтах."
        )

        return await self.send_alert(message)

    async def alert_worker_restart(
        self,
        phone: str,
        account_id: str,
        reason: str,
    ) -> bool:
        """Alert about worker restart attempt."""
        message = (
            f"🔄 <b>Перезапуск воркера</b>\n\n"
            f"📱 <b>Телефон:</b> <code>{phone}</code>\n"
            f"🆔 <b>ID:</b> <code>{account_id}</code>\n\n"
            f"📝 <b>Причина:</b> {reason}"
        )

        return await self.send_alert(message)

    async def alert_campaign_issue(
        self,
        campaign_name: str,
        issue: str,
    ) -> bool:
        """Alert about campaign issue."""
        message = (
            f"⚠️ <b>Проблема с кампанией</b>\n\n"
            f"📋 <b>Кампания:</b> {campaign_name}\n\n"
            f"❌ <b>Проблема:</b>\n{issue}"
        )

        return await self.send_alert(message)


# Singleton instance
_alert_service: Optional[TelegramAlertService] = None


def get_alert_service() -> TelegramAlertService:
    """Get or create alert service singleton."""
    global _alert_service

    if _alert_service is None:
        _alert_service = TelegramAlertService()

    return _alert_service


async def close_alert_service() -> None:
    """Close the alert service."""
    global _alert_service

    if _alert_service is not None:
        await _alert_service.close()
        _alert_service = None
