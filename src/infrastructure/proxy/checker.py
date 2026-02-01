"""
Proxy checker service.

Validates proxy connectivity and measures latency.
"""

import asyncio
import time
from datetime import datetime
from typing import Optional

import structlog
from aiohttp import ClientSession, ClientTimeout
from aiohttp_socks import ProxyConnector, ProxyType

from src.domain.entities import Proxy, ProxyStatus
from src.infrastructure.database import get_session
from src.infrastructure.database.repositories import PostgresProxyRepository

logger = structlog.get_logger(__name__)


# Mapping our proxy types to aiohttp-socks types
PROXY_TYPE_MAP = {
    "socks5": ProxyType.SOCKS5,
    "socks4": ProxyType.SOCKS4,
    "http": ProxyType.HTTP,
    "https": ProxyType.HTTP,
}


class ProxyChecker:
    """Service for checking proxy health and connectivity."""
    
    def __init__(
        self,
        timeout: float = 15.0,
        max_concurrent: int = 10,
    ):
        self._timeout = timeout
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
    
    async def check_proxy(self, proxy: Proxy) -> bool:
        """Check single proxy connectivity."""
        async with self._semaphore:
            return await self._do_check(proxy)
    
    async def check_single(self, proxy_id) -> tuple[bool, Optional[int], Optional[str]]:
        """
        Check single proxy by ID.
        
        Returns:
            Tuple of (is_working, latency_ms, error_message)
        """
        async with get_session() as session:
            repo = PostgresProxyRepository(session)
            proxy = await repo.get_by_id(proxy_id)
            
            if not proxy:
                return False, None, "Proxy not found"
            
            result = await self._do_check(proxy)
            
            if result:
                return True, proxy.last_check_latency_ms, None
            else:
                return False, None, "Connection failed"
    
    async def _do_check(self, proxy: Proxy) -> bool:
        """Perform actual proxy check."""
        logger.debug(
            "Checking proxy",
            host=proxy.host,
            port=proxy.port,
            proxy_type=proxy.proxy_type.value,
        )
        
        try:
            proxy_type = PROXY_TYPE_MAP.get(proxy.proxy_type.value, ProxyType.SOCKS5)
            
            connector = ProxyConnector(
                proxy_type=proxy_type,
                host=proxy.host,
                port=proxy.port,
                username=proxy.username,
                password=proxy.password,
                rdns=True,
            )
            
            timeout = ClientTimeout(total=self._timeout)
            
            async with ClientSession(connector=connector, timeout=timeout) as session:
                start_time = time.monotonic()
                
                async with session.get("https://api.telegram.org") as response:
                    latency_ms = int((time.monotonic() - start_time) * 1000)
                    
                    if response.status == 200:
                        await self._mark_active(proxy, latency_ms)
                        return True
                    else:
                        await self._mark_failed(proxy, f"HTTP {response.status}")
                        return False
                        
        except asyncio.TimeoutError:
            logger.warning("Proxy timeout", host=proxy.host, port=proxy.port)
            await self._mark_failed(proxy, "timeout")
            return False
            
        except Exception as e:
            error_msg = str(e) if str(e) else type(e).__name__
            logger.warning(
                "Proxy check failed",
                host=proxy.host,
                port=proxy.port,
                error=error_msg,
            )
            await self._mark_failed(proxy, error_msg)
            return False
    
    async def _mark_active(self, proxy: Proxy, latency_ms: int) -> None:
        """Mark proxy as active with new DB session."""
        try:
            proxy.status = ProxyStatus.ACTIVE
            proxy.last_check = datetime.utcnow()
            proxy.last_check_latency_ms = latency_ms
            proxy.failure_count = 0
            
            async with get_session() as session:
                repo = PostgresProxyRepository(session)
                await repo.save(proxy)
            
            logger.info(
                "Proxy check passed",
                host=proxy.host,
                port=proxy.port,
                latency_ms=latency_ms,
            )
        except Exception as e:
            logger.error(
                "Failed to save active proxy",
                host=proxy.host,
                port=proxy.port,
                error=repr(e),
            )
    
    async def _mark_failed(self, proxy: Proxy, reason: str) -> None:
        """Mark proxy as failed with new DB session."""
        try:
            proxy.failure_count += 1
            proxy.last_check = datetime.utcnow()
            
            if proxy.failure_count >= 3:
                proxy.status = ProxyStatus.UNAVAILABLE
            
            async with get_session() as session:
                repo = PostgresProxyRepository(session)
                await repo.save(proxy)
                
        except Exception as e:
            logger.error(
                "Failed to save failed proxy",
                host=proxy.host,
                port=proxy.port,
                error=repr(e),
            )
    
    async def check_all(self) -> dict:
        """Check all proxies in database."""
        async with get_session() as session:
            repo = PostgresProxyRepository(session)
            proxies = await repo.list_all(limit=1000)
        
        if not proxies:
            return {"total": 0, "passed": 0, "failed": 0}
        
        logger.info("Starting batch proxy check", count=len(proxies))
        
        tasks = [self.check_proxy(p) for p in proxies]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        passed = sum(1 for r in results if r is True)
        failed = len(results) - passed
        
        logger.info(
            "Batch proxy check completed",
            total=len(proxies),
            passed=passed,
            failed=failed,
        )
        
        return {
            "total": len(proxies),
            "passed": passed,
            "failed": failed,
        }
    
    async def check_accounts_proxies(self, account_ids: list) -> dict:
        """
        Check proxies for specific accounts.
        
        Returns dict of account_id -> {proxy_id, status, latency, error}
        """
        results = {}
        
        async with get_session() as session:
            from src.infrastructure.database.repositories import PostgresAccountRepository
            
            account_repo = PostgresAccountRepository(session)
            proxy_repo = PostgresProxyRepository(session)
            
            for account_id in account_ids:
                account = await account_repo.get_by_id(account_id)
                
                if not account:
                    results[str(account_id)] = {
                        "status": "error",
                        "error": "Account not found"
                    }
                    continue
                
                if not account.proxy_id:
                    results[str(account_id)] = {
                        "status": "no_proxy",
                        "error": "No proxy assigned"
                    }
                    continue
                
                proxy = await proxy_repo.get_by_id(account.proxy_id)
                
                if not proxy:
                    results[str(account_id)] = {
                        "proxy_id": str(account.proxy_id),
                        "status": "error",
                        "error": "Proxy not found in database"
                    }
                    continue
        
        # Check proxies outside session context
        for account_id in account_ids:
            result = results.get(str(account_id))
            if result and result.get("status") in ["error", "no_proxy"]:
                continue
            
            # Get proxy again for check
            async with get_session() as session:
                account_repo = PostgresAccountRepository(session)
                proxy_repo = PostgresProxyRepository(session)
                
                account = await account_repo.get_by_id(account_id)
                if not account or not account.proxy_id:
                    continue
                    
                proxy = await proxy_repo.get_by_id(account.proxy_id)
                if not proxy:
                    continue
            
            # Now check outside session
            is_working = await self._do_check(proxy)
            
            results[str(account_id)] = {
                "proxy_id": str(proxy.id),
                "proxy_host": proxy.host,
                "proxy_port": proxy.port,
                "status": "ok" if is_working else "failed",
                "latency": proxy.last_check_latency_ms if is_working else None,
                "error": None if is_working else "Connection failed"
            }
        
        return results
    
    async def get_best_proxy(self) -> Optional[Proxy]:
        """Get the best available proxy (lowest latency, not assigned)."""
        async with get_session() as session:
            repo = PostgresProxyRepository(session)
            proxies = await repo.list_available()
        
        if not proxies:
            return None
        
        available = [p for p in proxies if p.assigned_account_id is None]
        
        if not available:
            return None
        
        available.sort(key=lambda p: p.last_check_latency_ms or 99999)
        
        return available[0]


# Global instance
_checker: Optional[ProxyChecker] = None


def get_proxy_checker() -> ProxyChecker:
    """Get or create ProxyChecker instance."""
    global _checker
    if _checker is None:
        _checker = ProxyChecker()
    return _checker
