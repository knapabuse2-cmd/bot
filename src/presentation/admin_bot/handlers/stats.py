"""
Statistics handlers.
"""

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services import AccountService, CampaignService
from src.infrastructure.database.repositories import (
    PostgresAccountRepository,
    PostgresCampaignRepository,
    PostgresProxyRepository,
    PostgresUserTargetRepository,
)
from src.domain.entities import AccountStatus

from ..keyboards import get_main_menu_kb, get_back_kb

router = Router(name="stats")


@router.message(F.text == "📊 Статистика")
@router.message(Command("stats"))
async def show_stats(message: Message, session: AsyncSession) -> None:
    """Show general statistics."""
    # Get account stats
    account_repo = PostgresAccountRepository(session)
    proxy_repo = PostgresProxyRepository(session)
    
    account_service = AccountService(account_repo, proxy_repo)
    account_stats = await account_service.get_account_stats()
    
    # Get campaign stats
    campaign_repo = PostgresCampaignRepository(session)
    target_repo = PostgresUserTargetRepository(session)
    
    campaign_service = CampaignService(campaign_repo, account_repo, target_repo)
    active_campaigns = await campaign_service.list_active_campaigns()
    
    # Get proxy stats
    available_proxies = await proxy_repo.count_available()
    all_proxies = await proxy_repo.count_all()
    
    # Build stats message
    text = (
        "📊 <b>Статистика системы</b>\n\n"
        
        "<b>📱 Аккаунты:</b>\n"
        f"  • Всего: {account_stats['total']}\n"
        f"  • 🟢 Активных: {account_stats['active']}\n"
        f"  • 🔵 Готовых: {account_stats['ready']}\n"
        f"  • 🟡 На паузе: {account_stats['paused']}\n"
        f"  • 🔴 С ошибками: {account_stats['error']}\n"
        f"  • ⛔ Забанено: {account_stats['banned']}\n\n"
        
        "<b>📢 Кампании:</b>\n"
        f"  • Активных: {len(active_campaigns)}\n"
    )
    
    # Add campaign details
    if active_campaigns:
        total_targets = 0
        total_contacted = 0
        total_converted = 0
        
        for c in active_campaigns:
            total_targets += c.stats.total_targets
            total_contacted += c.stats.contacted
            total_converted += c.stats.goals_reached
        
        text += (
            f"  • Всего таргетов: {total_targets}\n"
            f"  • Контактов: {total_contacted}\n"
            f"  • Конверсий: {total_converted}\n"
        )
        
        if total_contacted > 0:
            conv_rate = (total_converted / total_contacted) * 100
            text += f"  • Общий CR: {conv_rate:.1f}%\n"
    
    text += (
        f"\n<b>🌐 Прокси:</b>\n"
        f"  • Всего: {all_proxies}\n"
        f"  • Доступно: {available_proxies}\n"
    )
    
    await message.answer(text)


@router.callback_query(F.data == "stats:accounts")
async def stats_accounts(callback: CallbackQuery, session: AsyncSession) -> None:
    """Detailed account statistics."""
    account_repo = PostgresAccountRepository(session)
    
    # Get accounts grouped by campaign
    all_accounts = await account_repo.list_all(limit=200)
    
    campaigns_accounts = {}
    for acc in all_accounts:
        cid = str(acc.campaign_id) if acc.campaign_id else "none"
        if cid not in campaigns_accounts:
            campaigns_accounts[cid] = []
        campaigns_accounts[cid].append(acc)
    
    text = "📱 <b>Статистика аккаунтов</b>\n\n"
    
    # Messages sent today
    total_messages = sum(acc.hourly_messages_count for acc in all_accounts)
    total_convos = sum(acc.daily_conversations_count for acc in all_accounts)
    
    text += (
        f"<b>За последний час:</b>\n"
        f"  • Сообщений: {total_messages}\n"
        f"  • Новых диалогов: {total_convos}\n\n"
    )
    
    # By status
    by_status = {}
    for acc in all_accounts:
        status = acc.status.value
        by_status[status] = by_status.get(status, 0) + 1
    
    text += "<b>По статусам:</b>\n"
    for status, count in sorted(by_status.items()):
        emoji = {
            "active": "🟢",
            "ready": "🔵",
            "paused": "🟡",
            "error": "🔴",
            "banned": "⛔",
            "inactive": "⚪",
        }.get(status, "❓")
        text += f"  • {emoji} {status}: {count}\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_kb("main_menu"),
    )
    await callback.answer()


@router.callback_query(F.data == "stats:campaigns")
async def stats_campaigns(callback: CallbackQuery, session: AsyncSession) -> None:
    """Detailed campaign statistics."""
    campaign_repo = PostgresCampaignRepository(session)
    campaigns = await campaign_repo.list_all(limit=50)
    
    text = "📢 <b>Статистика кампаний</b>\n\n"
    
    for c in campaigns:
        status_emoji = {
            "draft": "📝",
            "ready": "🔵",
            "active": "🟢",
            "paused": "🟡",
            "completed": "✅",
            "cancelled": "❌",
        }.get(c.status.value, "❓")
        
        text += f"{status_emoji} <b>{c.name}</b>\n"
        text += f"  Таргетов: {c.stats.total_targets} | "
        text += f"Контактов: {c.stats.contacted} | "
        text += f"Конверсий: {c.stats.goals_reached}\n"
        
        if c.stats.contacted > 0:
            resp_rate = c.stats.response_rate
            conv_rate = c.stats.conversion_rate
            text += f"  RR: {resp_rate:.1f}% | CR: {conv_rate:.1f}%\n"
        
        text += "\n"
    
    if not campaigns:
        text += "Нет кампаний."
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_kb("main_menu"),
    )
    await callback.answer()
