"""Keyboards for comment bot admin."""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Main menu keyboard."""
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="📱 Аккаунты"),
        KeyboardButton(text="💬 Комментарии"),
    )
    builder.row(
        KeyboardButton(text="📊 Статистика"),
        KeyboardButton(text="⚙️ Настройки"),
    )
    return builder.as_markup(resize_keyboard=True)


def accounts_menu_keyboard() -> InlineKeyboardMarkup:
    """Accounts menu keyboard."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Добавить (номер)", callback_data="acc:add_phone"),
        InlineKeyboardButton(text="📁 Добавить (tdata)", callback_data="acc:add_tdata"),
    )
    builder.row(
        InlineKeyboardButton(text="📋 Список аккаунтов", callback_data="acc:list"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main"),
    )
    return builder.as_markup()


def account_actions_keyboard(account_id: str, is_active: bool) -> InlineKeyboardMarkup:
    """Actions for specific account."""
    builder = InlineKeyboardBuilder()

    if is_active:
        builder.row(
            InlineKeyboardButton(text="⏸ Пауза", callback_data=f"acc:pause:{account_id}"),
        )
    else:
        builder.row(
            InlineKeyboardButton(text="▶️ Возобновить", callback_data=f"acc:resume:{account_id}"),
        )

    builder.row(
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"acc:delete:{account_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ К списку", callback_data="acc:list"),
    )
    return builder.as_markup()


def cancel_keyboard() -> InlineKeyboardMarkup:
    """Cancel action keyboard."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"),
    )
    return builder.as_markup()


def confirm_delete_keyboard(account_id: str) -> InlineKeyboardMarkup:
    """Confirm account deletion."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"acc:confirm_delete:{account_id}"),
        InlineKeyboardButton(text="❌ Нет", callback_data=f"acc:view:{account_id}"),
    )
    return builder.as_markup()


def back_to_accounts_keyboard() -> InlineKeyboardMarkup:
    """Back to accounts list."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="◀️ К аккаунтам", callback_data="acc:menu"),
    )
    return builder.as_markup()
