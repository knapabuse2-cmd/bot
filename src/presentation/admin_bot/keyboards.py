"""
Keyboard builders for admin bot.

Provides inline and reply keyboards for navigation.
"""

from typing import Optional
from uuid import UUID

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder


# =============================================================================
# Reply Keyboards
# =============================================================================

def get_main_menu_kb() -> ReplyKeyboardMarkup:
    """Main menu reply keyboard."""
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="📱 Аккаунты"),
        KeyboardButton(text="📢 Кампании"),
    )
    builder.row(
        KeyboardButton(text="🔍 Парсер"),
        KeyboardButton(text="📊 Статистика"),
    )
    builder.row(
        KeyboardButton(text="🌐 Прокси"),
        KeyboardButton(text="🔥 Прогрев"),
    )
    builder.row(
        KeyboardButton(text="📱 API Apps"),
        KeyboardButton(text="❓ Помощь"),
    )
    return builder.as_markup(resize_keyboard=True)


def get_cancel_kb() -> ReplyKeyboardMarkup:
    """Cancel action keyboard."""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="❌ Отмена"))
    return builder.as_markup(resize_keyboard=True)


def remove_kb() -> ReplyKeyboardRemove:
    """Remove reply keyboard."""
    return ReplyKeyboardRemove()


# =============================================================================
# Inline Keyboards - Main Navigation
# =============================================================================

def get_back_kb(callback_data: str = "main_menu") -> InlineKeyboardMarkup:
    """Simple back button."""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="◀️ Назад",
        callback_data=callback_data,
    ))
    return builder.as_markup()


# =============================================================================
# Inline Keyboards - Accounts
# =============================================================================

def get_accounts_menu_kb(
    active_count: int = 0,
    error_count: int = 0,
    paused_count: int = 0,
    banned_count: int = 0,
) -> InlineKeyboardMarkup:
    """Accounts management menu with counts."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📋 Все аккаунты", callback_data="accounts:list"),
        InlineKeyboardButton(text="➕ Добавить", callback_data="accounts:add"),
    )
    builder.row(
        InlineKeyboardButton(text="🔍 Поиск", callback_data="accounts:search"),
        InlineKeyboardButton(text="📁 Группы", callback_data="groups:list"),
    )

    # Status filters with counts
    status_row = []
    if active_count > 0:
        status_row.append(InlineKeyboardButton(
            text=f"🟢 {active_count}",
            callback_data="accounts:active"
        ))
    if paused_count > 0:
        status_row.append(InlineKeyboardButton(
            text=f"🟡 {paused_count}",
            callback_data="accounts:paused"
        ))
    if error_count > 0:
        status_row.append(InlineKeyboardButton(
            text=f"🔴 {error_count}",
            callback_data="accounts:errors"
        ))
    if banned_count > 0:
        status_row.append(InlineKeyboardButton(
            text=f"⛔ {banned_count}",
            callback_data="accounts:banned"
        ))

    if status_row:
        builder.row(*status_row)

    builder.row(
        InlineKeyboardButton(
            text="🔍 Проверить все",
            callback_data="accounts:check_all",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="🏠 Dashboard", callback_data="dashboard"),
    )
    return builder.as_markup()


def get_account_actions_kb(
    account_id: UUID,
    status: str,
    is_session_dead: bool = False,
    source: str = "phone",
) -> InlineKeyboardMarkup:
    """Actions for a specific account."""
    builder = InlineKeyboardBuilder()

    # If session is dead (AuthKeyDuplicated), only show delete button
    if is_session_dead:
        builder.row(
            InlineKeyboardButton(
                text="🗑 Удалить (сессия мертва)",
                callback_data=f"account:delete:{account_id}",
            ),
        )
        builder.row(
            InlineKeyboardButton(text="◀️ К аккаунтам", callback_data="accounts:list"),
        )
        return builder.as_markup()

    if status == "active":
        builder.row(
            InlineKeyboardButton(
                text="⏸ Пауза",
                callback_data=f"account:pause:{account_id}",
            ),
        )
    elif status == "error":
        # Show reconnect button for accounts with errors
        builder.row(
            InlineKeyboardButton(
                text="🔄 Переподключиться",
                callback_data=f"account:reconnect:{account_id}",
            ),
        )
        builder.row(
            InlineKeyboardButton(
                text="▶️ Активировать",
                callback_data=f"account:activate:{account_id}",
            ),
        )
    elif status in ("ready", "paused"):
        builder.row(
            InlineKeyboardButton(
                text="▶️ Активировать",
                callback_data=f"account:activate:{account_id}",
            ),
        )

    builder.row(
        InlineKeyboardButton(
            text="📊 Статистика",
            callback_data=f"account:stats:{account_id}",
        ),
        InlineKeyboardButton(
            text="💬 Диалоги",
            callback_data=f"account:dialogues:{account_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🌐 Сменить прокси",
            callback_data=f"account:proxy:{account_id}",
        ),
        InlineKeyboardButton(
            text="⚙️ Настройки",
            callback_data=f"account:settings:{account_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="📲 Получить код",
            callback_data=f"account:getcode:{account_id}",
        ),
        InlineKeyboardButton(
            text="⭐ Купить Premium",
            callback_data=f"account:premium:{account_id}",
        ),
    )
    # Show re-auth button only for imported accounts (json_session/tdata)
    if source in ("json_session", "tdata"):
        builder.row(
            InlineKeyboardButton(
                text="🔄 Переавторизовать",
                callback_data=f"account:reauth:{account_id}",
            ),
            InlineKeyboardButton(
                text="✏️ Кастомизация",
                callback_data=f"account:customize:{account_id}",
            ),
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text="✏️ Кастомизация",
                callback_data=f"account:customize:{account_id}",
            ),
        )
    builder.row(
        InlineKeyboardButton(
            text="🗑 Удалить",
            callback_data=f"account:delete:{account_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ К аккаунтам", callback_data="accounts:list"),
    )
    return builder.as_markup()


def get_account_add_method_kb() -> InlineKeyboardMarkup:
    """Account addition method selection."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📦 Загрузить ZIP-архив",
            callback_data="accounts:add:zip",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="📚 Массовый импорт (ZIP)",
            callback_data="accounts:add:bulk",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="📁 Загрузить session-файл",
            callback_data="accounts:add:session",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="📂 Несколько архивов (папки)",
            callback_data="accounts:add:multi_archive",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="📱 Авторизация по номеру",
            callback_data="accounts:add:phone",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="accounts:menu"),
    )
    return builder.as_markup()


def get_accounts_list_kb(
    accounts: list,
    page: int = 0,
    per_page: int = 5,
) -> InlineKeyboardMarkup:
    """Paginated list of accounts."""
    builder = InlineKeyboardBuilder()
    
    start = page * per_page
    end = start + per_page
    page_accounts = accounts[start:end]
    
    for acc in page_accounts:
        status_emoji = {
            "active": "🟢",
            "ready": "🔵",
            "paused": "🟡",
            "error": "🔴",
            "banned": "⛔",
            "inactive": "⚪",
        }.get(acc.status.value, "❓")
        
        phone_display = acc.phone[-4:] if len(acc.phone) > 4 else acc.phone
        name = acc.username or acc.first_name or f"...{phone_display}"
        
        builder.row(
            InlineKeyboardButton(
                text=f"{status_emoji} {name}",
                callback_data=f"account:view:{acc.id}",
            ),
        )
    
    # Pagination
    nav_buttons = []
    total_pages = (len(accounts) + per_page - 1) // per_page
    
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(text="◀️", callback_data=f"accounts:page:{page-1}")
        )
    
    nav_buttons.append(
        InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop")
    )
    
    if end < len(accounts):
        nav_buttons.append(
            InlineKeyboardButton(text="▶️", callback_data=f"accounts:page:{page+1}")
        )
    
    if nav_buttons:
        builder.row(*nav_buttons)
    
    builder.row(
        InlineKeyboardButton(text="◀️ Меню аккаунтов", callback_data="accounts:menu"),
    )
    
    return builder.as_markup()


# =============================================================================
# Inline Keyboards - Campaigns
# =============================================================================

def get_campaigns_menu_kb(
    active_count: int = 0,
    paused_count: int = 0,
    draft_count: int = 0,
) -> InlineKeyboardMarkup:
    """Campaigns management menu with counts."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📋 Все кампании", callback_data="campaigns:list"),
        InlineKeyboardButton(text="➕ Создать", callback_data="campaigns:create"),
    )

    # Status filters with counts
    status_row = []
    if active_count > 0:
        status_row.append(InlineKeyboardButton(
            text=f"🟢 Активные ({active_count})",
            callback_data="campaigns:active"
        ))
    if paused_count > 0:
        status_row.append(InlineKeyboardButton(
            text=f"🟡 Пауза ({paused_count})",
            callback_data="campaigns:paused"
        ))
    if draft_count > 0:
        status_row.append(InlineKeyboardButton(
            text=f"📝 Черновики ({draft_count})",
            callback_data="campaigns:drafts"
        ))

    if status_row:
        for btn in status_row:
            builder.row(btn)

    builder.row(
        InlineKeyboardButton(text="🏠 Dashboard", callback_data="dashboard"),
    )
    return builder.as_markup()


def get_campaign_actions_kb(campaign_id: UUID, status: str) -> InlineKeyboardMarkup:
    """Actions for a specific campaign."""
    builder = InlineKeyboardBuilder()

    if status in ("draft", "paused"):
        builder.row(
            InlineKeyboardButton(
                text="✏️ Настроить",
                callback_data=f"campaign:configure:{campaign_id}",
            ),
        )
    
    if status == "active":
        builder.row(
            InlineKeyboardButton(
                text="⏸ Пауза",
                callback_data=f"campaign:pause:{campaign_id}",
            ),
        )
    elif status in ("draft", "ready", "paused"):
        builder.row(
            InlineKeyboardButton(
                text="▶️ Запустить",
                callback_data=f"campaign:start:{campaign_id}",
            ),
        )
    
    builder.row(
        InlineKeyboardButton(
            text="👥 Таргеты",
            callback_data=f"campaign:targets:{campaign_id}",
        ),
        InlineKeyboardButton(
            text="📱 Аккаунты",
            callback_data=f"campaign:accounts:{campaign_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="📊 Статистика",
            callback_data=f"campaign:stats:{campaign_id}",
        ),
        InlineKeyboardButton(
            text="💬 Диалоги",
            callback_data=f"campaign:dialogues:{campaign_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🔄 Рестарт (тест)",
            callback_data=f"campaign:restart:{campaign_id}",
        ),
        InlineKeyboardButton(
            text="🗑 Удалить",
            callback_data=f"campaign:delete:{campaign_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ К кампаниям", callback_data="campaigns:list"),
    )
    return builder.as_markup()


def get_campaign_configure_kb(campaign_id: UUID) -> InlineKeyboardMarkup:
    """Campaign configuration menu."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🎯 Цель",
            callback_data=f"campaign:cfg:goal:{campaign_id}",
        ),
        InlineKeyboardButton(
            text="📝 Промпт",
            callback_data=f"campaign:cfg:prompt:{campaign_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🤖 AI настройки",
            callback_data=f"campaign:cfg:ai:{campaign_id}",
        ),
        InlineKeyboardButton(
            text="⏱ Рассылка",
            callback_data=f"campaign:cfg:sending:{campaign_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="👥 Загрузить таргеты",
            callback_data=f"campaign:cfg:targets:{campaign_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="📱 Назначить аккаунты",
            callback_data=f"campaign:cfg:accounts:{campaign_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="📊 Лимиты аккаунтов",
            callback_data=f"campaign:cfg:limits:{campaign_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="◀️ К кампании",
            callback_data=f"campaign:view:{campaign_id}",
        ),
    )
    return builder.as_markup()


# =============================================================================
# Inline Keyboards - Proxies
# =============================================================================

def get_proxies_menu_kb() -> InlineKeyboardMarkup:
    """Proxies management menu."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📋 Список", callback_data="proxies:list"),
        InlineKeyboardButton(text="➕ Добавить", callback_data="proxies:add"),
    )
    builder.row(
        InlineKeyboardButton(text="📁 Группы прокси", callback_data="proxy_groups:list"),
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Проверить все", callback_data="proxies:check"),
    )
    builder.row(
        InlineKeyboardButton(text="🗑 Удалить все прокси", callback_data="proxies:delete_all"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu"),
    )
    return builder.as_markup()


def get_proxy_groups_menu_kb() -> InlineKeyboardMarkup:
    """Proxy groups management menu."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📋 Все группы", callback_data="proxy_groups:list"),
        InlineKeyboardButton(text="➕ Создать", callback_data="proxy_groups:create"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ К прокси", callback_data="proxies:menu"),
    )
    return builder.as_markup()


def get_proxy_group_actions_kb(group_id: UUID) -> InlineKeyboardMarkup:
    """Actions for a single proxy group."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📋 Прокси в группе",
            callback_data=f"proxy_group:proxies:{group_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="➕ Добавить прокси",
            callback_data=f"proxy_group:add_proxies:{group_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🔄 Проверить прокси",
            callback_data=f"proxy_group:check:{group_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="✏️ Редактировать",
            callback_data=f"proxy_group:edit:{group_id}",
        ),
        InlineKeyboardButton(
            text="🗑 Удалить",
            callback_data=f"proxy_group:delete:{group_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="◀️ К группам",
            callback_data="proxy_groups:list",
        ),
    )
    return builder.as_markup()


# =============================================================================
# Inline Keyboards - Confirmation
# =============================================================================

def get_confirm_kb(
    confirm_callback: str,
    cancel_callback: str = "cancel",
) -> InlineKeyboardMarkup:
    """Confirmation dialog."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да", callback_data=confirm_callback),
        InlineKeyboardButton(text="❌ Нет", callback_data=cancel_callback),
    )
    return builder.as_markup()


# =============================================================================
# Inline Keyboards - Scraper
# =============================================================================

def get_scraper_menu_kb() -> InlineKeyboardMarkup:
    """Scraper main menu."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🔍 Обычный парсинг (1 аккаунт)",
            callback_data="scraper:start",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="⚡ Параллельный парсинг (много аккаунтов)",
            callback_data="scraper:start_parallel",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu"),
    )
    return builder.as_markup()


def get_scraper_accounts_kb(accounts: list) -> InlineKeyboardMarkup:
    """Account selection for scraping."""
    builder = InlineKeyboardBuilder()

    for acc in accounts:
        status_emoji = {
            "active": "🟢",
            "ready": "🔵",
            "paused": "🟡",
            "error": "🔴",
        }.get(acc.status.value, "⚪")

        phone_display = acc.phone[-4:] if len(acc.phone) > 4 else acc.phone
        name = acc.username or acc.first_name or f"...{phone_display}"

        builder.row(
            InlineKeyboardButton(
                text=f"{status_emoji} {name}",
                callback_data=f"scraper:account:{acc.id}",
            ),
        )

    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="scraper:cancel"),
    )
    return builder.as_markup()


def get_scraper_accounts_multi_kb(accounts: list, selected_ids: set) -> InlineKeyboardMarkup:
    """Account multi-selection for parallel scraping."""
    builder = InlineKeyboardBuilder()

    for acc in accounts:
        status_emoji = {
            "active": "🟢",
            "ready": "🔵",
            "paused": "🟡",
            "error": "🔴",
        }.get(acc.status.value, "⚪")

        phone_display = acc.phone[-4:] if len(acc.phone) > 4 else acc.phone
        name = acc.username or acc.first_name or f"...{phone_display}"

        # Show checkmark if selected
        is_selected = str(acc.id) in selected_ids
        prefix = "✅ " if is_selected else ""

        builder.row(
            InlineKeyboardButton(
                text=f"{prefix}{status_emoji} {name}",
                callback_data=f"scraper:toggle:{acc.id}",
            ),
        )

    # Control buttons
    if selected_ids:
        builder.row(
            InlineKeyboardButton(
                text=f"▶️ Продолжить ({len(selected_ids)} акк.)",
                callback_data="scraper:parallel:continue",
            ),
        )

    builder.row(
        InlineKeyboardButton(
            text="📋 Выбрать все",
            callback_data="scraper:select_all",
        ),
        InlineKeyboardButton(
            text="🔄 Сбросить",
            callback_data="scraper:select_none",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="scraper:cancel"),
    )
    return builder.as_markup()


def get_scraper_campaign_select_kb(campaigns: list) -> InlineKeyboardMarkup:
    """Campaign selection for adding scraped targets."""
    builder = InlineKeyboardBuilder()

    # Option to not add to campaign (just collect usernames)
    builder.row(
        InlineKeyboardButton(
            text="📋 Только собрать (без кампании)",
            callback_data="scraper:campaign:none",
        ),
    )

    for campaign in campaigns:
        builder.row(
            InlineKeyboardButton(
                text=f"📢 {campaign.name}",
                callback_data=f"scraper:campaign:{campaign.id}",
            ),
        )

    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="scraper:cancel"),
    )
    return builder.as_markup()


def get_scraper_progress_kb(task_id: str = "") -> InlineKeyboardMarkup:
    """Scraping progress view."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="⏹ Остановить",
            callback_data=f"scraper:stop:{task_id}",
        ),
    )
    return builder.as_markup()


def get_scraper_result_kb(campaign_id: Optional[UUID] = None) -> InlineKeyboardMarkup:
    """Scraping result view."""
    builder = InlineKeyboardBuilder()

    if campaign_id:
        builder.row(
            InlineKeyboardButton(
                text="📢 К кампании",
                callback_data=f"campaign:view:{campaign_id}",
            ),
        )

    builder.row(
        InlineKeyboardButton(
            text="🔍 Новый сбор",
            callback_data="scraper:start",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu"),
    )
    return builder.as_markup()


# =============================================================================
# Inline Keyboards - Telegram Apps
# =============================================================================

def get_telegram_apps_menu_kb() -> InlineKeyboardMarkup:
    """Telegram Apps management menu."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📋 Список приложений", callback_data="apps:list"),
        InlineKeyboardButton(text="➕ Добавить", callback_data="apps:add"),
    )
    builder.row(
        InlineKeyboardButton(text="📊 Статистика", callback_data="apps:stats"),
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Пересчитать", callback_data="apps:recalculate"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu"),
    )
    return builder.as_markup()


def get_telegram_app_actions_kb(app_id: UUID, is_active: bool) -> InlineKeyboardMarkup:
    """Actions for a specific Telegram App."""
    builder = InlineKeyboardBuilder()

    if is_active:
        builder.row(
            InlineKeyboardButton(
                text="⏸ Деактивировать",
                callback_data=f"app:deactivate:{app_id}",
            ),
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text="▶️ Активировать",
                callback_data=f"app:activate:{app_id}",
            ),
        )

    builder.row(
        InlineKeyboardButton(
            text="✏️ Изменить название",
            callback_data=f"app:edit_name:{app_id}",
        ),
        InlineKeyboardButton(
            text="📊 Изменить лимит",
            callback_data=f"app:edit_limit:{app_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🔄 Пересчитать аккаунты",
            callback_data=f"app:recalculate:{app_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🗑 Удалить",
            callback_data=f"app:delete:{app_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ К списку", callback_data="apps:list"),
    )
    return builder.as_markup()


def get_telegram_apps_list_kb(apps: list) -> InlineKeyboardMarkup:
    """List of Telegram Apps."""
    builder = InlineKeyboardBuilder()

    for app in apps:
        status_emoji = "🟢" if app.is_active else "🔴"
        usage = f"{app.current_account_count}/{app.max_accounts}"
        builder.row(
            InlineKeyboardButton(
                text=f"{status_emoji} {app.name} ({usage})",
                callback_data=f"app:view:{app.id}",
            ),
        )

    builder.row(
        InlineKeyboardButton(text="➕ Добавить", callback_data="apps:add"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Меню приложений", callback_data="apps:menu"),
    )
    return builder.as_markup()
