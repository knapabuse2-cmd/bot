"""
Proxy entity representing a proxy server configuration.

Each account should use a dedicated proxy to avoid
detection and rate limiting.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from .base import AggregateRoot


class ProxyType(str, Enum):
    """Supported proxy types."""
    
    SOCKS5 = "socks5"
    SOCKS4 = "socks4"
    HTTP = "http"
    HTTPS = "https"
    MTPROTO = "mtproto"


class ProxyStatus(str, Enum):
    """Proxy health status."""
    
    UNKNOWN = "unknown"       # Not yet tested
    ACTIVE = "active"         # Working properly
    SLOW = "slow"             # Working but slow
    UNAVAILABLE = "unavailable"  # Currently down
    BANNED = "banned"         # Blocked by Telegram


@dataclass
class Proxy(AggregateRoot):
    """
    Proxy server configuration entity.
    
    Attributes:
        host: Proxy server hostname or IP
        port: Proxy server port
        proxy_type: Type of proxy (socks5, http, etc.)
        username: Authentication username (if required)
        password: Authentication password (if required)
        status: Current proxy status
        assigned_account_id: Account using this proxy
        country: Proxy country code (for geo-targeting)
        provider: Proxy provider name
        last_check: Last health check timestamp
        last_check_latency_ms: Latency from last check
        failure_count: Consecutive failure count
        total_requests: Total requests through this proxy
        notes: Admin notes
    """
    
    host: str = ""
    port: int = 0
    proxy_type: ProxyType = ProxyType.SOCKS5
    
    username: Optional[str] = None
    password: Optional[str] = None
    
    status: ProxyStatus = ProxyStatus.UNKNOWN
    assigned_account_id: Optional[UUID] = None
    
    # Metadata
    country: str = ""
    provider: str = ""
    
    # Health tracking
    last_check: Optional[datetime] = None
    last_check_latency_ms: Optional[int] = None
    failure_count: int = 0
    total_requests: int = 0
    
    notes: str = ""

    # Backward compatible aliases (used by API/UI)
    @property
    def last_check_at(self) -> Optional[datetime]:
        return self.last_check

    @last_check_at.setter
    def last_check_at(self, value: Optional[datetime]) -> None:
        self.last_check = value

    @property
    def fail_count(self) -> int:
        return self.failure_count

    @fail_count.setter
    def fail_count(self, value: int) -> None:
        self.failure_count = value
    
    @property
    def address(self) -> str:
        """Get proxy address in host:port format."""
        return f"{self.host}:{self.port}"
    
    @property
    def url(self) -> str:
        """Get proxy URL for connection."""
        auth = ""
        if self.username and self.password:
            auth = f"{self.username}:{self.password}@"
        return f"{self.proxy_type.value}://{auth}{self.host}:{self.port}"
    
    def to_telethon_proxy(self) -> tuple:
        """
        Convert to Telethon proxy format.
        
        Returns:
            Tuple of (proxy_type, host, port, rdns, username, password)
        """
        import socks
        
        type_map = {
            ProxyType.SOCKS5: socks.SOCKS5,
            ProxyType.SOCKS4: socks.SOCKS4,
            ProxyType.HTTP: socks.HTTP,
            ProxyType.HTTPS: socks.HTTP,
        }
        
        proxy_type = type_map.get(self.proxy_type, socks.SOCKS5)
        
        return (
            proxy_type,
            self.host,
            self.port,
            True,  # rdns
            self.username,
            self.password,
        )
    
    def to_aiohttp_proxy(self) -> str:
        """Get proxy URL for aiohttp."""
        return self.url
    
    def mark_active(self, latency_ms: int) -> None:
        """Mark proxy as active after successful check."""
        self.status = ProxyStatus.ACTIVE
        self.last_check = datetime.utcnow()
        self.last_check_latency_ms = latency_ms
        self.failure_count = 0
        
        # Mark as slow if latency > 5 seconds
        if latency_ms > 5000:
            self.status = ProxyStatus.SLOW
        
        self.touch()
    
    def mark_failed(self) -> None:
        """Record a failed check."""
        self.failure_count += 1
        self.last_check = datetime.utcnow()
        
        # Mark unavailable after 3 consecutive failures
        if self.failure_count >= 3:
            self.status = ProxyStatus.UNAVAILABLE
        
        self.touch()
    
    def mark_banned(self) -> None:
        """Mark proxy as banned by Telegram."""
        self.status = ProxyStatus.BANNED
        self.touch()
    
    def assign_to_account(self, account_id: UUID) -> None:
        """Assign proxy to an account."""
        self.assigned_account_id = account_id
        self.touch()
    
    def unassign(self) -> None:
        """Unassign proxy from account."""
        self.assigned_account_id = None
        self.touch()
    
    def is_available(self) -> bool:
        """Check if proxy is available for use."""
        return (
            self.status in (ProxyStatus.ACTIVE, ProxyStatus.SLOW, ProxyStatus.UNKNOWN)
            and self.assigned_account_id is None
        )
    
    def is_healthy(self) -> bool:
        """Check if proxy is healthy."""
        return self.status in (ProxyStatus.ACTIVE, ProxyStatus.SLOW)
    
    def record_request(self) -> None:
        """Record a request through this proxy."""
        self.total_requests += 1
