"""Common handlers for comment bot."""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command

from src.commentbot.presentation.admin_bot.keyboards import main_menu_keyboard

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    """Handle /start command."""
    await message.answer(
        f"👋 <b>Привет, {message.from_user.first_name}!</b>\n\n"
        f"Это бот для управления комментариями.\n\n"
        f"Используй меню ниже для навигации:",
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Handle /help command."""
    await message.answer(
        "📖 <b>Справка</b>\n\n"
        "<b>📱 Аккаунты</b> — управление Telegram аккаунтами\n"
        "• Добавить по номеру телефона\n"
        "• Добавить через tdata\n"
        "• Просмотр и удаление\n\n"
        "<b>💬 Комментарии</b> — постинг комментариев\n"
        "• Выбор канала и поста\n"
        "• Написание и отправка комментария\n\n"
        "<b>📊 Статистика</b> — статистика по аккаунтам\n\n"
        "<b>⚙️ Настройки</b> — настройки бота",
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:main")
async def back_to_main(callback: CallbackQuery):
    """Go back to main menu."""
    await callback.message.edit_text(
        "🏠 <b>Главное меню</b>\n\n"
        "Выберите раздел:",
        parse_mode="HTML",
    )
    await callback.message.answer(
        "Используй кнопки ниже:",
        reply_markup=main_menu_keyboard(),
    )
    await callback.answer()


@router.message(F.text == "📊 Статистика")
async def stats_menu(message: Message):
    """Show stats."""
    await message.answer(
        "📊 <b>Статистика</b>\n\n"
        "🚧 <i>В разработке...</i>",
        parse_mode="HTML",
    )


@router.message(F.text == "⚙️ Настройки")
async def settings_menu(message: Message):
    """Show settings."""
    await message.answer(
        "⚙️ <b>Настройки</b>\n\n"
        "🚧 <i>В разработке...</i>",
        parse_mode="HTML",
    )


