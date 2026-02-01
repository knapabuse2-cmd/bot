"""
Warmup management handlers for admin bot.

Provides commands for:
- Managing warmup profiles
- Starting/stopping warmup for accounts
- Adding warmup channels and groups
- Viewing warmup statistics
"""

import logging
from typing import Optional
from uuid import UUID, uuid4

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.domain.entities import WarmupStatus, ActivityPattern
from src.services.warmup_service import WarmupService
from src.infrastructure.database.connection import get_session
from src.infrastructure.database.repositories import (
    WarmupChannelRepository,
    WarmupGroupRepository,
    AccountGroupRepository,
    WarmupProfileRepository,
    AccountWarmupRepository,
    InterestCategoryRepository,
)

from ..keyboards import get_main_menu_kb, get_cancel_kb, get_back_kb


logger = logging.getLogger(__name__)
router = Router(name="warmup")


class WarmupStates(StatesGroup):
    """States for warmup management."""

    # Adding channels
    waiting_channel_list = State()

    # Adding groups
    waiting_group_list = State()

    # Creating account group
    waiting_group_name = State()

    # Adding accounts to group
    selecting_accounts_for_group = State()


# =============================================================================
# Keyboards
# =============================================================================

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_warmup_menu_kb() -> InlineKeyboardMarkup:
    """Warmup main menu."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📊 Статистика", callback_data="warmup:stats"),
    )
    builder.row(
        InlineKeyboardButton(text="📺 Каналы", callback_data="warmup:channels"),
        InlineKeyboardButton(text="👥 Группы", callback_data="warmup:groups"),
    )
    builder.row(
        InlineKeyboardButton(text="🔥 Запустить прогрев", callback_data="warmup:start"),
    )
    builder.row(
        InlineKeyboardButton(text="📁 Группы аккаунтов", callback_data="warmup:account_groups"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu"),
    )
    return builder.as_markup()


def get_warmup_channels_kb(count: int = 0) -> InlineKeyboardMarkup:
    """Warmup channels menu."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=f"📋 Список ({count})", callback_data="warmup:channels:list"),
    )
    builder.row(
        InlineKeyboardButton(text="➕ Добавить каналы", callback_data="warmup:channels:add"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="warmup:menu"),
    )
    return builder.as_markup()


def get_warmup_groups_kb(count: int = 0) -> InlineKeyboardMarkup:
    """Warmup groups menu."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=f"📋 Список ({count})", callback_data="warmup:groups:list"),
    )
    builder.row(
        InlineKeyboardButton(text="➕ Добавить группы", callback_data="warmup:groups:add"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="warmup:menu"),
    )
    return builder.as_markup()


def get_account_groups_kb(groups: list) -> InlineKeyboardMarkup:
    """Account groups list."""
    builder = InlineKeyboardBuilder()

    for group in groups:
        builder.row(
            InlineKeyboardButton(
                text=f"📁 {group.name}",
                callback_data=f"warmup:ag:{group.id}",
            ),
        )

    builder.row(
        InlineKeyboardButton(text="➕ Создать группу", callback_data="warmup:ag:create"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="warmup:menu"),
    )
    return builder.as_markup()


def get_account_group_actions_kb(group_id: UUID) -> InlineKeyboardMarkup:
    """Actions for account group."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🔥 Запустить прогрев группы",
            callback_data=f"warmup:ag:start:{group_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="➕ Добавить аккаунты",
            callback_data=f"warmup:ag:add_accounts:{group_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="📋 Список аккаунтов",
            callback_data=f"warmup:ag:list_accounts:{group_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🗑 Удалить группу",
            callback_data=f"warmup:ag:delete:{group_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="warmup:account_groups"),
    )
    return builder.as_markup()


# =============================================================================
# Main Menu
# =============================================================================

@router.message(F.text == "🔥 Прогрев")
async def warmup_menu_handler(message: Message):
    """Show warmup menu."""
    await message.answer(
        "🔥 <b>Система прогрева</b>\n\n"
        "Здесь вы можете управлять прогревом аккаунтов:\n"
        "• Добавлять каналы и группы для прогрева\n"
        "• Создавать группы аккаунтов\n"
        "• Запускать прогрев для групп аккаунтов",
        parse_mode="HTML",
        reply_markup=get_warmup_menu_kb(),
    )


@router.callback_query(F.data == "warmup:menu")
async def warmup_menu_callback(callback: CallbackQuery):
    """Show warmup menu via callback."""
    await callback.message.edit_text(
        "🔥 <b>Система прогрева</b>\n\n"
        "Здесь вы можете управлять прогревом аккаунтов:\n"
        "• Добавлять каналы и группы для прогрева\n"
        "• Создавать группы аккаунтов\n"
        "• Запускать прогрев для групп аккаунтов",
        parse_mode="HTML",
        reply_markup=get_warmup_menu_kb(),
    )
    await callback.answer()


# =============================================================================
# Statistics
# =============================================================================

@router.callback_query(F.data == "warmup:stats")
async def warmup_stats_handler(callback: CallbackQuery):
    """Show warmup statistics."""
    async with get_session() as session:
        service = WarmupService(session)
        stats = await service.get_warmup_stats()

    text = (
        "📊 <b>Статистика прогрева</b>\n\n"
        f"🔥 Активных прогревов: {stats['active_warmups']}\n"
        f"⏳ Ожидающих: {stats['pending_warmups']}\n"
        f"✅ Завершённых: {stats['completed_warmups']}\n"
        f"⏸ На паузе: {stats['paused_warmups']}\n\n"
        f"📺 Каналов для прогрева: {stats['total_channels']}\n"
        f"👥 Групп для прогрева: {stats['total_groups']}"
    )

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=get_back_kb("warmup:menu"),
    )
    await callback.answer()


# =============================================================================
# Channels Management
# =============================================================================

@router.callback_query(F.data == "warmup:channels")
async def warmup_channels_menu(callback: CallbackQuery):
    """Show channels menu."""
    async with get_session() as session:
        repo = WarmupChannelRepository(session)
        count = await repo.count()

    await callback.message.edit_text(
        f"📺 <b>Каналы для прогрева</b>\n\n"
        f"Всего каналов: {count}\n\n"
        f"Добавьте каналы, на которые аккаунты будут подписываться во время прогрева.",
        parse_mode="HTML",
        reply_markup=get_warmup_channels_kb(count),
    )
    await callback.answer()


@router.callback_query(F.data == "warmup:channels:add")
async def warmup_add_channels_start(callback: CallbackQuery, state: FSMContext):
    """Start adding channels."""
    await callback.message.edit_text(
        "📺 <b>Добавление каналов</b>\n\n"
        "Отправьте список каналов (по одному на строку).\n"
        "Можно указывать @username или ссылку.\n\n"
        "Пример:\n"
        "<code>@channel1\n"
        "@channel2\n"
        "https://t.me/channel3</code>",
        parse_mode="HTML",
    )
    await callback.message.answer(
        "Ожидаю список каналов...",
        reply_markup=get_cancel_kb(),
    )
    await state.set_state(WarmupStates.waiting_channel_list)
    await callback.answer()


@router.message(WarmupStates.waiting_channel_list)
async def warmup_add_channels_process(message: Message, state: FSMContext):
    """Process channel list."""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer(
            "Добавление отменено.",
            reply_markup=get_main_menu_kb(),
        )
        return

    lines = message.text.strip().split("\n")
    added = 0
    errors = []

    async with get_session() as session:
        repo = WarmupChannelRepository(session)

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Extract username
            username = line.replace("https://t.me/", "").replace("@", "").strip()
            if not username:
                continue

            # Check if already exists
            existing = await repo.get_by_username(username)
            if existing:
                errors.append(f"@{username} уже существует")
                continue

            # Create channel
            from src.domain.entities import WarmupChannel
            channel = WarmupChannel(
                id=uuid4(),
                username=username,
                is_active=True,
            )
            await repo.save(channel)
            added += 1

        await session.commit()

    await state.clear()

    text = f"✅ Добавлено каналов: {added}"
    if errors:
        text += f"\n\n⚠️ Ошибки:\n" + "\n".join(errors[:10])

    await message.answer(text, reply_markup=get_main_menu_kb())


@router.callback_query(F.data == "warmup:channels:list")
async def warmup_channels_list(callback: CallbackQuery):
    """List warmup channels."""
    async with get_session() as session:
        repo = WarmupChannelRepository(session)
        channels = await repo.get_active(limit=50)

    if not channels:
        await callback.message.edit_text(
            "📺 Каналы не добавлены.\n\n"
            "Добавьте каналы для прогрева.",
            reply_markup=get_warmup_channels_kb(0),
        )
    else:
        text = "📺 <b>Каналы для прогрева:</b>\n\n"
        for ch in channels[:30]:
            text += f"• @{ch.username}\n"
        if len(channels) > 30:
            text += f"\n... и ещё {len(channels) - 30}"

        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=get_warmup_channels_kb(len(channels)),
        )
    await callback.answer()


# =============================================================================
# Groups Management
# =============================================================================

@router.callback_query(F.data == "warmup:groups")
async def warmup_groups_menu(callback: CallbackQuery):
    """Show groups menu."""
    async with get_session() as session:
        repo = WarmupGroupRepository(session)
        count = await repo.count()

    await callback.message.edit_text(
        f"👥 <b>Группы для прогрева</b>\n\n"
        f"Всего групп: {count}\n\n"
        f"Добавьте группы, в которых аккаунты будут участвовать во время прогрева.",
        parse_mode="HTML",
        reply_markup=get_warmup_groups_kb(count),
    )
    await callback.answer()


@router.callback_query(F.data == "warmup:groups:add")
async def warmup_add_groups_start(callback: CallbackQuery, state: FSMContext):
    """Start adding groups."""
    await callback.message.edit_text(
        "👥 <b>Добавление групп</b>\n\n"
        "Отправьте список групп (по одной на строку).\n"
        "Можно указывать @username или ссылку.\n\n"
        "Пример:\n"
        "<code>@group1\n"
        "@group2\n"
        "https://t.me/group3</code>",
        parse_mode="HTML",
    )
    await callback.message.answer(
        "Ожидаю список групп...",
        reply_markup=get_cancel_kb(),
    )
    await state.set_state(WarmupStates.waiting_group_list)
    await callback.answer()


@router.message(WarmupStates.waiting_group_list)
async def warmup_add_groups_process(message: Message, state: FSMContext):
    """Process group list."""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer(
            "Добавление отменено.",
            reply_markup=get_main_menu_kb(),
        )
        return

    lines = message.text.strip().split("\n")
    added = 0
    errors = []

    async with get_session() as session:
        repo = WarmupGroupRepository(session)

        for line in lines:
            line = line.strip()
            if not line:
                continue

            username = line.replace("https://t.me/", "").replace("@", "").strip()
            if not username:
                continue

            existing = await repo.get_by_username(username)
            if existing:
                errors.append(f"@{username} уже существует")
                continue

            from src.domain.entities import WarmupGroup
            group = WarmupGroup(
                id=uuid4(),
                username=username,
                can_write=True,
                is_active=True,
            )
            await repo.save(group)
            added += 1

        await session.commit()

    await state.clear()

    text = f"✅ Добавлено групп: {added}"
    if errors:
        text += f"\n\n⚠️ Ошибки:\n" + "\n".join(errors[:10])

    await message.answer(text, reply_markup=get_main_menu_kb())


@router.callback_query(F.data == "warmup:groups:list")
async def warmup_groups_list(callback: CallbackQuery):
    """List warmup groups."""
    async with get_session() as session:
        repo = WarmupGroupRepository(session)
        groups = await repo.get_active(limit=50)

    if not groups:
        await callback.message.edit_text(
            "👥 Группы не добавлены.\n\n"
            "Добавьте группы для прогрева.",
            reply_markup=get_warmup_groups_kb(0),
        )
    else:
        text = "👥 <b>Группы для прогрева:</b>\n\n"
        for g in groups[:30]:
            text += f"• @{g.username}\n"
        if len(groups) > 30:
            text += f"\n... и ещё {len(groups) - 30}"

        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=get_warmup_groups_kb(len(groups)),
        )
    await callback.answer()


# =============================================================================
# Account Groups Management
# =============================================================================

@router.callback_query(F.data == "warmup:account_groups")
async def warmup_account_groups_menu(callback: CallbackQuery):
    """Show account groups menu."""
    async with get_session() as session:
        repo = AccountGroupRepository(session)
        groups = await repo.get_all()

    if not groups:
        text = (
            "📁 <b>Группы аккаунтов</b>\n\n"
            "Группы аккаунтов позволяют запускать прогрев сразу для нескольких аккаунтов.\n\n"
            "Создайте первую группу."
        )
    else:
        text = (
            "📁 <b>Группы аккаунтов</b>\n\n"
            f"Всего групп: {len(groups)}\n\n"
            "Выберите группу или создайте новую."
        )

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=get_account_groups_kb(groups),
    )
    await callback.answer()


@router.callback_query(F.data == "warmup:ag:create")
async def warmup_create_account_group_start(callback: CallbackQuery, state: FSMContext):
    """Start creating account group."""
    await callback.message.edit_text(
        "📁 <b>Создание группы аккаунтов</b>\n\n"
        "Введите название для новой группы:",
        parse_mode="HTML",
    )
    await callback.message.answer(
        "Ожидаю название группы...",
        reply_markup=get_cancel_kb(),
    )
    await state.set_state(WarmupStates.waiting_group_name)
    await callback.answer()


@router.message(WarmupStates.waiting_group_name)
async def warmup_create_account_group_process(message: Message, state: FSMContext):
    """Process account group creation."""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer(
            "Создание отменено.",
            reply_markup=get_main_menu_kb(),
        )
        return

    name = message.text.strip()

    async with get_session() as session:
        repo = AccountGroupRepository(session)

        existing = await repo.get_by_name(name)
        if existing:
            await message.answer(
                f"⚠️ Группа '{name}' уже существует.\n"
                "Введите другое название:",
            )
            return

        from src.domain.entities import AccountGroup
        group = AccountGroup(
            id=uuid4(),
            name=name,
        )
        await repo.save(group)
        await session.commit()

    await state.clear()
    await message.answer(
        f"✅ Группа '{name}' создана.\n\n"
        "Теперь добавьте в неё аккаунты.",
        reply_markup=get_main_menu_kb(),
    )


@router.callback_query(F.data.startswith("warmup:ag:") & ~F.data.contains(":start:") & ~F.data.contains(":delete:") & ~F.data.contains(":add_accounts:") & ~F.data.contains(":list_accounts:"))
async def warmup_view_account_group(callback: CallbackQuery):
    """View account group."""
    group_id_str = callback.data.split(":")[-1]
    try:
        group_id = UUID(group_id_str)
    except ValueError:
        await callback.answer("Неверный ID группы")
        return

    async with get_session() as session:
        repo = AccountGroupRepository(session)
        group = await repo.get_by_id(group_id)
        if not group:
            await callback.answer("Группа не найдена")
            return

        account_ids = await repo.get_account_ids(group_id)

    await callback.message.edit_text(
        f"📁 <b>{group.name}</b>\n\n"
        f"Аккаунтов в группе: {len(account_ids)}\n\n"
        f"Выберите действие:",
        parse_mode="HTML",
        reply_markup=get_account_group_actions_kb(group_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("warmup:ag:start:"))
async def warmup_start_for_group(callback: CallbackQuery):
    """Start warmup for account group."""
    group_id_str = callback.data.split(":")[-1]
    try:
        group_id = UUID(group_id_str)
    except ValueError:
        await callback.answer("Неверный ID группы")
        return

    async with get_session() as session:
        repo = AccountGroupRepository(session)
        group = await repo.get_by_id(group_id)
        group_name = group.name if group else "Неизвестная группа"

        service = WarmupService(session)
        count = await service.start_warmup_for_group(group_id)
        await session.commit()

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📊 Статистика прогрева", callback_data="warmup:stats"),
    )
    builder.row(
        InlineKeyboardButton(text="📁 Ещё группу", callback_data="warmup:start:select_group"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Меню прогрева", callback_data="warmup:menu"),
    )

    await callback.message.edit_text(
        f"🔥 <b>Прогрев запущен!</b>\n\n"
        f"📁 Группа: {group_name}\n"
        f"👥 Аккаунтов: {count}",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )
    await callback.answer("Прогрев запущен!")


@router.callback_query(F.data.startswith("warmup:ag:delete:"))
async def warmup_delete_account_group(callback: CallbackQuery):
    """Delete account group."""
    group_id_str = callback.data.split(":")[-1]
    try:
        group_id = UUID(group_id_str)
    except ValueError:
        await callback.answer("Неверный ID группы")
        return

    async with get_session() as session:
        repo = AccountGroupRepository(session)
        deleted = await repo.delete(group_id)
        await session.commit()

    if deleted:
        await callback.message.edit_text(
            "✅ Группа удалена.",
            reply_markup=get_back_kb("warmup:account_groups"),
        )
    else:
        await callback.answer("Не удалось удалить группу")


# =============================================================================
# Start Warmup
# =============================================================================

@router.callback_query(F.data == "warmup:start")
async def warmup_start_menu(callback: CallbackQuery):
    """Show warmup start options."""
    async with get_session() as session:
        repo = AccountGroupRepository(session)
        groups = await repo.get_all()

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🔥 Запустить для всех активных",
            callback_data="warmup:start:all_active",
        ),
    )

    # Show available groups with accounts
    groups_with_accounts = [g for g in groups if g.account_count > 0]
    if groups_with_accounts:
        builder.row(
            InlineKeyboardButton(
                text=f"📁 Группы аккаунтов ({len(groups_with_accounts)})",
                callback_data="warmup:start:select_group",
            ),
        )

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="warmup:menu"),
    )

    await callback.message.edit_text(
        "🔥 <b>Запуск прогрева</b>\n\n"
        "Выберите способ запуска прогрева:",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "warmup:start:select_group")
async def warmup_start_select_group(callback: CallbackQuery):
    """Show groups to select for warmup."""
    async with get_session() as session:
        repo = AccountGroupRepository(session)
        groups = await repo.get_all()

    groups_with_accounts = [g for g in groups if g.account_count > 0]

    builder = InlineKeyboardBuilder()
    for group in groups_with_accounts:
        builder.row(
            InlineKeyboardButton(
                text=f"📁 {group.name} ({group.account_count} акк.)",
                callback_data=f"warmup:ag:start:{group.id}",
            ),
        )

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="warmup:start"),
    )

    await callback.message.edit_text(
        "📁 <b>Выберите группу для запуска прогрева</b>\n\n"
        "Все аккаунты из выбранной группы будут добавлены в прогрев.",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "warmup:start:all_active")
async def warmup_start_all_active(callback: CallbackQuery):
    """Start warmup for all active accounts."""
    from src.infrastructure.database.repositories import PostgresAccountRepository
    from src.domain.entities import AccountStatus

    async with get_session() as session:
        account_repo = PostgresAccountRepository(session)
        accounts = await account_repo.get_by_status(AccountStatus.ACTIVE)

        service = WarmupService(session)
        count = 0
        for account in accounts:
            await service.start_warmup(account.id)
            count += 1

        await session.commit()

    await callback.message.edit_text(
        f"🔥 Прогрев запущен для {count} активных аккаунтов!",
        reply_markup=get_back_kb("warmup:menu"),
    )
    await callback.answer("Прогрев запущен!")
