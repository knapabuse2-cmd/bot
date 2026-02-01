"""
Common handlers.

Handles basic commands and navigation:
- /start
- /help
- Main menu
- Cancel actions
"""

from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.repositories import (
    PostgresAccountRepository,
    PostgresCampaignRepository,
    PostgresProxyRepository,
)
from src.domain.entities import AccountStatus, CampaignStatus

from ..keyboards import get_main_menu_kb, get_back_kb

router = Router(name="common")


async def _build_dashboard(session: AsyncSession) -> tuple[str, InlineKeyboardMarkup]:
    """Build dashboard message with stats and quick actions."""
    account_repo = PostgresAccountRepository(session)
    campaign_repo = PostgresCampaignRepository(session)
    proxy_repo = PostgresProxyRepository(session)

    # Get account counts
    account_counts = await account_repo.count_all_by_status()
    active_accounts = account_counts.get("active", 0)
    error_accounts = account_counts.get("error", 0)
    banned_accounts = account_counts.get("banned", 0)
    total_accounts = sum(account_counts.values())

    # Get campaigns
    active_campaigns = await campaign_repo.list_by_status(CampaignStatus.ACTIVE)
    all_campaigns = await campaign_repo.list_all(limit=100)

    # Get proxies
    available_proxies = await proxy_repo.count_available()

    # Calculate totals from active campaigns
    total_contacted = 0
    total_goals = 0
    for c in active_campaigns:
        total_contacted += c.stats.contacted
        total_goals += c.stats.goals_reached

    # Build dashboard text
    text = "📊 <b>Dashboard</b>\n\n"

    # Alerts section
    alerts = []
    if error_accounts > 0:
        alerts.append(f"🔴 {error_accounts} акк. с ошибками")
    if banned_accounts > 0:
        alerts.append(f"⛔ {banned_accounts} акк. забанено")
    if available_proxies == 0:
        alerts.append("⚠️ Нет свободных прокси")

    if alerts:
        text += "⚠️ <b>Требует внимания:</b>\n"
        for alert in alerts:
            text += f"  • {alert}\n"
        text += "\n"

    # Status overview
    text += "<b>📱 Аккаунты:</b> "
    text += f"🟢 {active_accounts} активных"
    if total_accounts > active_accounts:
        text += f" / {total_accounts} всего"
    text += "\n"

    text += f"<b>📢 Кампании:</b> {len(active_campaigns)} активных"
    if len(all_campaigns) > len(active_campaigns):
        text += f" / {len(all_campaigns)} всего"
    text += "\n"

    text += f"<b>🌐 Прокси:</b> {available_proxies} свободных\n"

    # Active campaigns stats
    if active_campaigns:
        text += "\n<b>📈 Сегодня:</b>\n"
        text += f"  • Контактов: {total_contacted}\n"
        text += f"  • Целей достигнуто: {total_goals}\n"
        if total_contacted > 0:
            cr = (total_goals / total_contacted) * 100
            text += f"  • Конверсия: {cr:.1f}%\n"

    # Quick actions keyboard
    buttons = [
        [
            InlineKeyboardButton(text="📱 Аккаунты", callback_data="accounts:menu"),
            InlineKeyboardButton(text="📢 Кампании", callback_data="campaigns:menu"),
        ],
        [
            InlineKeyboardButton(text="🌐 Прокси", callback_data="proxies:menu"),
            InlineKeyboardButton(text="📊 Подробнее", callback_data="stats:detailed"),
        ],
    ]

    # Add quick action for problems
    if error_accounts > 0:
        buttons.append([
            InlineKeyboardButton(text=f"🔴 Показать ошибки ({error_accounts})", callback_data="accounts:errors"),
        ])

    if active_campaigns:
        buttons.append([
            InlineKeyboardButton(text="💬 Активные диалоги", callback_data="dialogs:active"),
        ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    return text, keyboard


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Handle /start command - show dashboard."""
    await state.clear()

    text, keyboard = await _build_dashboard(session)

    await message.answer(text, reply_markup=keyboard)
    await message.answer(
        "Используйте меню ниже для навигации:",
        reply_markup=get_main_menu_kb(),
    )


@router.callback_query(F.data == "dashboard")
async def show_dashboard(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show dashboard."""
    text, keyboard = await _build_dashboard(session)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.message(Command("help"))
@router.message(F.text == "❓ Помощь")
async def cmd_help(message: Message) -> None:
    """Handle /help command."""
    await message.answer(
        "📚 <b>Справка по системе</b>\n\n"
        "<b>📱 Аккаунты</b>\n"
        "Управление Telegram аккаунтами для рассылки. "
        "Каждый аккаунт работает через отдельный прокси.\n\n"
        "<b>📢 Кампании</b>\n"
        "Создание и управление кампаниями рассылки. "
        "Настройка целей, промптов AI, загрузка таргетов.\n\n"
        "<b>🌐 Прокси</b>\n"
        "Управление списком прокси-серверов. "
        "Каждому аккаунту назначается уникальный прокси.\n\n"
        "<b>📊 Статистика</b>\n"
        "Просмотр метрик: конверсии, отклики, активность.\n\n"
        "<b>Команды:</b>\n"
        "/start - Главное меню\n"
        "/help - Эта справка\n"
        "/stats - Быстрая статистика\n"
        "/accounts - Список аккаунтов\n"
        "/campaigns - Список кампаний",
    )


@router.message(F.text == "❌ Отмена")
async def cancel_action(message: Message, state: FSMContext) -> None:
    """Handle cancel button."""
    current_state = await state.get_state()
    
    if current_state is None:
        await message.answer(
            "Нет активного действия для отмены.",
            reply_markup=get_main_menu_kb(),
        )
        return
    
    await state.clear()
    await message.answer(
        "❌ Действие отменено.",
        reply_markup=get_main_menu_kb(),
    )


@router.callback_query(F.data == "cancel")
async def cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle cancel callback."""
    await state.clear()
    await callback.message.edit_text("❌ Действие отменено.")
    await callback.answer()


@router.callback_query(F.data == "main_menu")
async def main_menu_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle main menu callback."""
    await state.clear()
    await callback.message.edit_text(
        "📋 <b>Главное меню</b>\n\n"
        "Выберите раздел:",
    )
    await callback.message.answer(
        "Используйте кнопки ниже:",
        reply_markup=get_main_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "noop")
async def noop_callback(callback: CallbackQuery) -> None:
    """Handle noop callback (pagination counter, etc.)."""
    await callback.answer()


@router.message(F.text == "⚙️ Настройки")
async def settings_menu(message: Message) -> None:
    """Handle settings menu."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🤖 Настройки AI",
            callback_data="settings:ai",
        )],
        [InlineKeyboardButton(
            text="⏱ Глобальные лимиты",
            callback_data="settings:limits",
        )],
        [InlineKeyboardButton(
            text="🔔 Уведомления",
            callback_data="settings:notifications",
        )],
        [InlineKeyboardButton(
            text="📤 Экспорт данных",
            callback_data="settings:export",
        )],
        [InlineKeyboardButton(
            text="🔧 Система",
            callback_data="settings:system",
        )],
    ])
    
    await message.answer(
        "⚙️ <b>Настройки системы</b>\n\n"
        "Выберите раздел:",
        reply_markup=keyboard,
    )


@router.callback_query(F.data == "settings:ai")
async def settings_ai(callback: CallbackQuery) -> None:
    """Show AI settings."""
    from src.config import get_settings
    
    settings = get_settings()
    
    text = (
        "🤖 <b>Настройки AI</b>\n\n"
        f"<b>Модель:</b> {settings.openai.default_model}\n"
        f"<b>Temperature:</b> {settings.openai.default_temperature}\n"
        f"<b>Max Tokens:</b> {settings.openai.default_max_tokens}\n"
        f"<b>Requests/min:</b> {settings.openai.requests_per_minute}\n"
        f"<b>Timeout:</b> {settings.openai.timeout}s\n\n"
        "<i>Для изменения отредактируйте .env файл</i>"
    )
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="settings:menu")],
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "settings:limits")
async def settings_limits(callback: CallbackQuery) -> None:
    """Show global limits settings."""
    from src.config import get_settings
    
    settings = get_settings()
    
    text = (
        "⏱ <b>Глобальные лимиты</b>\n\n"
        f"<b>Макс. активных аккаунтов:</b> {settings.worker.max_concurrent_accounts}\n"
        f"<b>Диалогов на аккаунт:</b> {settings.worker.max_concurrent_dialogues_per_account}\n"
        f"<b>Интервал проверки сообщений:</b> {settings.worker.message_check_interval}s\n"
        f"<b>Интервал health check:</b> {settings.worker.health_check_interval}s\n"
        f"<b>Размер batch очереди:</b> {settings.worker.queue_batch_size}\n\n"
        "<i>Для изменения отредактируйте .env файл</i>"
    )
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="settings:menu")],
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "settings:notifications")
async def settings_notifications(callback: CallbackQuery) -> None:
    """Show notification settings."""
    text = (
        "🔔 <b>Уведомления</b>\n\n"
        "Настройка уведомлений:\n\n"
        "• 🟢 Запуск/остановка кампаний\n"
        "• 🔴 Ошибки аккаунтов\n"
        "• 🎯 Достижение целей\n"
        "• ⚠️ Превышение лимитов\n\n"
        "<i>Функция в разработке</i>"
    )
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="settings:menu")],
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "settings:export")
async def settings_export(callback: CallbackQuery) -> None:
    """Export data options."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📱 Экспорт аккаунтов (CSV)",
            callback_data="export:accounts",
        )],
        [InlineKeyboardButton(
            text="📢 Экспорт кампаний (CSV)",
            callback_data="export:campaigns",
        )],
        [InlineKeyboardButton(
            text="💬 Экспорт диалогов (JSON)",
            callback_data="export:dialogues",
        )],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="settings:menu")],
    ])
    
    await callback.message.edit_text(
        "📤 <b>Экспорт данных</b>\n\n"
        "Выберите что экспортировать:",
        reply_markup=keyboard,
    )
    await callback.answer()


@router.callback_query(F.data == "export:accounts")
async def export_accounts(callback: CallbackQuery, session: AsyncSession) -> None:
    """Export accounts to CSV."""
    from src.infrastructure.database.repositories import PostgresAccountRepository
    import csv
    import io
    from aiogram.types import BufferedInputFile
    
    repo = PostgresAccountRepository(session)
    accounts = await repo.list_all(limit=1000)
    
    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "phone", "username", "status", "proxy_id",
        "hourly_count", "daily_count", "total_messages", "created_at"
    ])
    
    for acc in accounts:
        writer.writerow([
            str(acc.id),
            acc.phone,
            acc.username or "",
            acc.status.value,
            str(acc.proxy_id) if acc.proxy_id else "",
            acc.hourly_messages_count,
            acc.daily_conversations_count,
            acc.total_messages_sent,
            acc.created_at.isoformat() if acc.created_at else "",
        ])
    
    csv_bytes = output.getvalue().encode("utf-8")
    file = BufferedInputFile(csv_bytes, filename="accounts_export.csv")
    
    await callback.message.answer_document(file, caption="📱 Экспорт аккаунтов")
    await callback.answer("✅ Экспорт готов!")


@router.callback_query(F.data == "export:campaigns")
async def export_campaigns(callback: CallbackQuery, session: AsyncSession) -> None:
    """Export campaigns to CSV."""
    from src.infrastructure.database.repositories import PostgresCampaignRepository
    import csv
    import io
    from aiogram.types import BufferedInputFile
    
    repo = PostgresCampaignRepository(session)
    campaigns = await repo.list_all(limit=100)
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "name", "status", "total_targets", "contacted",
        "responded", "goals_reached", "created_at"
    ])
    
    for c in campaigns:
        writer.writerow([
            str(c.id),
            c.name,
            c.status.value,
            c.stats.total_targets,
            c.stats.contacted,
            c.stats.responded,
            c.stats.goals_reached,
            c.created_at.isoformat() if c.created_at else "",
        ])
    
    csv_bytes = output.getvalue().encode("utf-8")
    file = BufferedInputFile(csv_bytes, filename="campaigns_export.csv")
    
    await callback.message.answer_document(file, caption="📢 Экспорт кампаний")
    await callback.answer("✅ Экспорт готов!")


@router.callback_query(F.data == "export:dialogues")
async def export_dialogues(callback: CallbackQuery, session: AsyncSession) -> None:
    """Export dialogues to JSON."""
    from src.infrastructure.database.repositories import PostgresDialogueRepository
    import json
    import io
    from aiogram.types import BufferedInputFile
    
    repo = PostgresDialogueRepository(session)
    dialogues = await repo.list_all(limit=500)
    
    data = []
    for d in dialogues:
        data.append({
            "id": str(d.id),
            "account_id": str(d.account_id),
            "campaign_id": str(d.campaign_id),
            "telegram_user_id": d.telegram_user_id,
            "telegram_username": d.telegram_username,
            "status": d.status.value,
            "goal_reached": d.goal_message_sent,
            "messages_count": len(d.messages),
            "messages": [
                {
                    "role": m.role.value,
                    "content": m.content,
                    "timestamp": m.timestamp.isoformat(),
                    "ai_generated": m.ai_generated,
                }
                for m in d.messages
            ],
            "created_at": d.created_at.isoformat() if d.created_at else None,
        })
    
    json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    file = BufferedInputFile(json_bytes, filename="dialogues_export.json")
    
    await callback.message.answer_document(file, caption="💬 Экспорт диалогов")
    await callback.answer("✅ Экспорт готов!")


@router.callback_query(F.data == "settings:system")
async def settings_system(callback: CallbackQuery) -> None:
    """Show system information."""
    import sys
    import platform
    from src.config import get_settings
    
    settings = get_settings()
    
    text = (
        "🔧 <b>Системная информация</b>\n\n"
        f"<b>Python:</b> {sys.version.split()[0]}\n"
        f"<b>Платформа:</b> {platform.system()} {platform.release()}\n"
        f"<b>Окружение:</b> {settings.environment}\n"
        f"<b>Debug:</b> {'Да' if settings.debug else 'Нет'}\n\n"
        f"<b>База данных:</b>\n"
        f"  Host: {settings.database.host}:{settings.database.port}\n"
        f"  Database: {settings.database.database}\n"
        f"  Pool size: {settings.database.pool_size}\n\n"
        f"<b>Redis:</b>\n"
        f"  Host: {settings.redis.host}:{settings.redis.port}\n"
        f"  DB: {settings.redis.db}"
    )
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="settings:menu")],
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "settings:menu")
async def settings_menu_callback(callback: CallbackQuery) -> None:
    """Return to settings menu."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Настройки AI", callback_data="settings:ai")],
        [InlineKeyboardButton(text="⏱ Глобальные лимиты", callback_data="settings:limits")],
        [InlineKeyboardButton(text="🔔 Уведомления", callback_data="settings:notifications")],
        [InlineKeyboardButton(text="📤 Экспорт данных", callback_data="settings:export")],
        [InlineKeyboardButton(text="🔧 Система", callback_data="settings:system")],
    ])
    
    await callback.message.edit_text(
        "⚙️ <b>Настройки системы</b>\n\n"
        "Выберите раздел:",
        reply_markup=keyboard,
    )
    await callback.answer()
