"""
Proxy infrastructure module.

Provides proxy checking and management functionality.
"""

from .checker import ProxyChecker, get_proxy_checker

__all__ = ["ProxyChecker", "get_proxy_checker"]
