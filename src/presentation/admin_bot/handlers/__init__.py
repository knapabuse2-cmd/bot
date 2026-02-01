"""
Bot handlers module.

Registers all routers with the dispatcher.
"""

from aiogram import Dispatcher

from .common import router as common_router
from .accounts import router as accounts_router
from .campaigns import router as campaigns_router
from .stats import router as stats_router
from .proxies import router as proxies_router
from .proxy_groups import router as proxy_groups_router
from .scraper import router as scraper_router
from .warmup import router as warmup_router
from .account_groups import router as account_groups_router
from .telegram_apps import router as telegram_apps_router


def register_all_handlers(dp: Dispatcher) -> None:
    """
    Register all handlers with the dispatcher.

    Order matters - first registered has higher priority.
    """
    dp.include_router(common_router)
    dp.include_router(accounts_router)
    dp.include_router(account_groups_router)
    dp.include_router(campaigns_router)
    dp.include_router(stats_router)
    dp.include_router(proxies_router)
    dp.include_router(proxy_groups_router)
    dp.include_router(scraper_router)
    dp.include_router(warmup_router)
    dp.include_router(telegram_apps_router)


__all__ = [
    "register_all_handlers",
]
