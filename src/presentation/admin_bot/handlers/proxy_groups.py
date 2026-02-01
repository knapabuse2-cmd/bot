"""
Proxy groups management handlers.
"""

from uuid import UUID

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.repositories import ProxyGroupRepository, PostgresProxyRepository
from src.domain.entities import ProxyGroup

from ..keyboards import (
    get_proxy_groups_menu_kb,
    get_proxy_group_actions_kb,
    get_cancel_kb,
    get_main_menu_kb,
    get_back_kb,
    get_confirm_kb,
    get_proxies_menu_kb,
)
from ..states import ProxyGroupStates

router = Router(name="proxy_groups")


# =============================================================================
# List Groups
# =============================================================================

@router.callback_query(F.data == "proxy_groups:list")
async def proxy_groups_list(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show list of proxy groups."""
    repo = ProxyGroupRepository(session)
    groups = await repo.get_all()

    if not groups:
        await callback.message.edit_text(
            "📁 <b>Группы прокси</b>\n\n"
            "Список пуст. Создайте первую группу.",
            reply_markup=get_proxy_groups_menu_kb(),
        )
        await callback.answer()
        return

    text = f"📁 <b>Группы прокси</b> ({len(groups)})\n\n"

    kb = InlineKeyboardBuilder()

    for group in groups:
        # Get proxy counts for this group
        total = await repo.count_proxies_in_group(group.id)
        available = await repo.count_available_proxies_in_group(group.id)

        country = f" [{group.country_code}]" if group.country_code else ""
        kb.row(InlineKeyboardButton(
            text=f"📁 {group.name}{country} ({available}/{total})",
            callback_data=f"proxy_group:view:{group.id}",
        ))

    kb.row(InlineKeyboardButton(
        text="➕ Создать группу",
        callback_data="proxy_groups:create",
    ))
    kb.row(InlineKeyboardButton(
        text="◀️ К прокси",
        callback_data="proxies:menu",
    ))

    await callback.message.edit_text(
        text + "<i>Формат: (свободно/всего)</i>",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


# =============================================================================
# View Group
# =============================================================================

@router.callback_query(F.data.startswith("proxy_group:view:"))
async def view_proxy_group(callback: CallbackQuery, session: AsyncSession) -> None:
    """View proxy group details."""
    group_id = UUID(callback.data.split(":")[2])

    repo = ProxyGroupRepository(session)
    group = await repo.get_by_id(group_id)

    if not group:
        await callback.answer("Группа не найдена", show_alert=True)
        return

    total = await repo.count_proxies_in_group(group_id)
    available = await repo.count_available_proxies_in_group(group_id)

    text = (
        f"📁 <b>{group.name}</b>\n\n"
        f"<b>ID:</b> <code>{group.id}</code>\n"
    )

    if group.country_code:
        text += f"<b>Страна:</b> {group.country_code}\n"

    if group.description:
        text += f"<b>Описание:</b> {group.description}\n"

    text += (
        f"\n<b>Прокси:</b>\n"
        f"  • Всего: {total}\n"
        f"  • Свободно: {available}\n"
        f"  • Занято: {total - available}\n"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_proxy_group_actions_kb(group_id),
    )
    await callback.answer()


# =============================================================================
# Create Group
# =============================================================================

@router.callback_query(F.data == "proxy_groups:create")
async def create_group_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start creating a new proxy group."""
    await state.set_state(ProxyGroupStates.waiting_name)

    await callback.message.edit_text(
        "➕ <b>Создание группы прокси</b>\n\n"
        "Шаг 1/4: Введите название группы\n\n"
        "<i>Например: DE Proxies, Premium, US Mobile</i>",
    )
    await callback.message.answer(
        "Ожидаю название группы...",
        reply_markup=get_cancel_kb(),
    )
    await callback.answer()


@router.message(ProxyGroupStates.waiting_name)
async def create_group_name(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Receive group name."""
    name = message.text.strip()

    if len(name) < 2:
        await message.answer("❌ Название слишком короткое (минимум 2 символа)")
        return

    if len(name) > 100:
        await message.answer("❌ Название слишком длинное (максимум 100 символов)")
        return

    # Check if name already exists
    repo = ProxyGroupRepository(session)
    existing = await repo.get_by_name(name)
    if existing:
        await message.answer("❌ Группа с таким названием уже существует")
        return

    await state.update_data(name=name)
    await state.set_state(ProxyGroupStates.waiting_country_code)

    await message.answer(
        f"✅ Название: <b>{name}</b>\n\n"
        "Шаг 2/4: Введите код страны (необязательно)\n\n"
        "<i>Например: DE, US, RU, UA</i>\n"
        "Или отправьте <code>-</code> чтобы пропустить",
        reply_markup=get_cancel_kb(),
    )


@router.message(ProxyGroupStates.waiting_country_code)
async def create_group_country(message: Message, state: FSMContext) -> None:
    """Receive country code."""
    country = message.text.strip().upper()

    if country == "-":
        country = None
    elif len(country) > 5:
        await message.answer("❌ Код страны слишком длинный (максимум 5 символов)")
        return

    await state.update_data(country_code=country)
    await state.set_state(ProxyGroupStates.waiting_description)

    await message.answer(
        "Шаг 3/4: Введите описание (необязательно)\n\n"
        "Или отправьте <code>-</code> чтобы пропустить",
        reply_markup=get_cancel_kb(),
    )


@router.message(ProxyGroupStates.waiting_description)
async def create_group_description(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Receive description, create group and ask for proxies."""
    description = message.text.strip()

    if description == "-":
        description = None

    data = await state.get_data()

    # Create group
    repo = ProxyGroupRepository(session)
    group = ProxyGroup(
        name=data["name"],
        country_code=data.get("country_code"),
        description=description,
    )

    saved = await repo.save(group)

    # Save group ID to state for proxy upload
    await state.update_data(new_group_id=str(saved.id), new_group_name=saved.name)
    await state.set_state(ProxyGroupStates.waiting_proxy_list)

    text = (
        f"✅ <b>Группа создана!</b>\n\n"
        f"<b>Название:</b> {saved.name}\n"
    )
    if saved.country_code:
        text += f"<b>Страна:</b> {saved.country_code}\n"
    if saved.description:
        text += f"<b>Описание:</b> {saved.description}\n"

    text += (
        "\n<b>Шаг 4/4: Добавьте прокси</b>\n\n"
        "Отправьте список прокси (каждый на новой строке).\n\n"
        "<b>Формат:</b>\n"
        "<code>type://host:port</code>\n"
        "<code>type://user:pass@host:port</code>\n\n"
        "<b>Поддерживаемые типы:</b> socks5, socks4, http, https\n\n"
        "<i>Или отправьте</i> <code>-</code> <i>чтобы пропустить</i>"
    )

    await message.answer(
        text,
        reply_markup=get_cancel_kb(),
    )


@router.message(ProxyGroupStates.waiting_proxy_list)
async def create_group_with_proxies(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Receive proxy list and add to newly created group."""
    from src.domain.entities import Proxy, ProxyType, ProxyStatus
    import re

    text = message.text.strip()

    data = await state.get_data()
    group_id = UUID(data["new_group_id"])
    group_name = data["new_group_name"]

    await state.clear()

    # If user skips
    if text == "-":
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(
            text="📋 Открыть группу",
            callback_data=f"proxy_group:view:{group_id}",
        ))
        kb.row(InlineKeyboardButton(
            text="◀️ К группам",
            callback_data="proxy_groups:list",
        ))

        await message.answer(
            f"✅ Группа <b>{group_name}</b> создана без прокси.\n\n"
            "Вы можете добавить прокси позже.",
            reply_markup=get_main_menu_kb(),
        )
        await message.answer(
            "Что дальше?",
            reply_markup=kb.as_markup(),
        )
        return

    # Parse proxy list
    lines = text.split("\n")
    proxies = []
    errors = []

    pattern = r'^(socks5|socks4|http|https)://(?:([^:]+):([^@]+)@)?([^:]+):(\d+)$'

    type_map = {
        "socks5": ProxyType.SOCKS5,
        "socks4": ProxyType.SOCKS4,
        "http": ProxyType.HTTP,
        "https": ProxyType.HTTPS,
    }

    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue

        match = re.match(pattern, line.lower())
        if not match:
            errors.append(f"Строка {i}: неверный формат")
            continue

        proxy_type_str, username, password, host, port = match.groups()

        proxy = Proxy(
            host=host,
            port=int(port),
            proxy_type=type_map[proxy_type_str],
            username=username,
            password=password,
            status=ProxyStatus.UNKNOWN,
        )
        proxies.append(proxy)

    if not proxies:
        await message.answer(
            "❌ Не удалось распознать ни одного прокси.\n\n"
            f"Ошибки:\n" + "\n".join(errors[:5]),
            reply_markup=get_main_menu_kb(),
        )
        return

    # Save proxies to database and add to group
    proxy_repo = PostgresProxyRepository(session)
    group_repo = ProxyGroupRepository(session)

    added = 0
    skipped = 0
    added_to_group = 0

    for proxy in proxies:
        # Check if proxy already exists
        existing = await proxy_repo.get_by_address(proxy.host, proxy.port)

        if existing:
            # Proxy exists, just add to group
            success = await group_repo.add_proxy(group_id, existing.id)
            if success:
                added_to_group += 1
            else:
                skipped += 1
        else:
            # Create new proxy
            saved_proxy = await proxy_repo.save(proxy)
            added += 1

            # Add to group
            await group_repo.add_proxy(group_id, saved_proxy.id)
            added_to_group += 1

    result_text = (
        f"✅ <b>Группа {group_name} готова!</b>\n\n"
        f"<b>Результат:</b>\n"
        f"  • Новых прокси создано: {added}\n"
        f"  • Добавлено в группу: {added_to_group}\n"
    )

    if skipped:
        result_text += f"  • Пропущено (дубли): {skipped}\n"

    if errors:
        result_text += f"\n<b>Ошибки ({len(errors)}):</b>\n"
        result_text += "\n".join(errors[:3])
        if len(errors) > 3:
            result_text += f"\n... и ещё {len(errors) - 3}"

    await message.answer(result_text, reply_markup=get_main_menu_kb())

    # Show group actions
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="📋 Открыть группу",
        callback_data=f"proxy_group:view:{group_id}",
    ))
    kb.row(InlineKeyboardButton(
        text="◀️ К группам",
        callback_data="proxy_groups:list",
    ))

    await message.answer(
        "Что дальше?",
        reply_markup=kb.as_markup(),
    )


# =============================================================================
# Add Proxies to Group
# =============================================================================

@router.callback_query(F.data.startswith("proxy_group:add_proxies:"))
async def add_proxies_to_group_start(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Start adding proxies to a group."""
    group_id = UUID(callback.data.split(":")[2])

    repo = ProxyGroupRepository(session)
    group = await repo.get_by_id(group_id)

    if not group:
        await callback.answer("Группа не найдена", show_alert=True)
        return

    # Get proxies not in any group
    proxy_repo = PostgresProxyRepository(session)
    all_proxies = await proxy_repo.list_all(limit=200)

    # Get proxies already in this group
    existing_ids = set(await repo.get_proxy_ids(group_id))

    # Filter to proxies not in this group
    available = [p for p in all_proxies if p.id not in existing_ids]

    if not available:
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"proxy_group:view:{group_id}",
        ))
        await callback.message.edit_text(
            f"📁 <b>{group.name}</b> - Добавление прокси\n\n"
            "⚠️ Все прокси уже добавлены в эту группу.\n"
            "Или нет доступных прокси.",
            reply_markup=kb.as_markup(),
        )
        await callback.answer()
        return

    await state.update_data(group_id=str(group_id), group_name=group.name)
    await state.set_state(ProxyGroupStates.waiting_proxy_list)

    # Build keyboard with available proxies
    kb = InlineKeyboardBuilder()

    # Option to add all
    kb.row(InlineKeyboardButton(
        text=f"✅ Добавить все ({len(available)})",
        callback_data=f"proxy_group:add_all:{group_id}",
    ))

    # Show first 15 proxies for individual selection
    for proxy in available[:15]:
        status_emoji = {
            "active": "🟢",
            "slow": "🟡",
            "unavailable": "🔴",
            "banned": "⛔",
            "unknown": "⚪",
        }.get(proxy.status.value, "❓")

        kb.row(InlineKeyboardButton(
            text=f"{status_emoji} {proxy.host}:{proxy.port}",
            callback_data=f"proxy_group:add_one:{group_id}:{proxy.id}",
        ))

    kb.row(InlineKeyboardButton(
        text="◀️ Назад",
        callback_data=f"proxy_group:view:{group_id}",
    ))

    text = (
        f"📁 <b>{group.name}</b> - Добавление прокси\n\n"
        f"Доступно прокси: {len(available)}\n\n"
        "Выберите прокси для добавления:"
    )

    if len(available) > 15:
        text += f"\n\n<i>Показано первые 15 из {len(available)}</i>"

    await callback.message.edit_text(
        text,
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("proxy_group:add_one:"))
async def add_one_proxy_to_group(callback: CallbackQuery, session: AsyncSession) -> None:
    """Add a single proxy to a group."""
    parts = callback.data.split(":")
    group_id = UUID(parts[2])
    proxy_id = UUID(parts[3])

    repo = ProxyGroupRepository(session)

    success = await repo.add_proxy(group_id, proxy_id)

    if success:
        await callback.answer("✅ Прокси добавлен в группу")
        # Refresh the list
        callback.data = f"proxy_group:add_proxies:{group_id}"
        await add_proxies_to_group_start(callback, session, FSMContext)
    else:
        await callback.answer("❌ Не удалось добавить прокси", show_alert=True)


@router.callback_query(F.data.startswith("proxy_group:add_all:"))
async def add_all_proxies_to_group(callback: CallbackQuery, session: AsyncSession) -> None:
    """Add all available proxies to a group."""
    group_id = UUID(callback.data.split(":")[2])

    repo = ProxyGroupRepository(session)
    group = await repo.get_by_id(group_id)

    if not group:
        await callback.answer("Группа не найдена", show_alert=True)
        return

    # Get proxies not in any group
    proxy_repo = PostgresProxyRepository(session)
    all_proxies = await proxy_repo.list_all(limit=500)

    # Get proxies already in this group
    existing_ids = set(await repo.get_proxy_ids(group_id))

    # Filter to proxies not in this group
    proxy_ids_to_add = [p.id for p in all_proxies if p.id not in existing_ids]

    if not proxy_ids_to_add:
        await callback.answer("Нет прокси для добавления", show_alert=True)
        return

    added = await repo.bulk_add_proxies(group_id, proxy_ids_to_add)

    await callback.answer(f"✅ Добавлено {added} прокси")

    # Show updated group view
    callback.data = f"proxy_group:view:{group_id}"
    await view_proxy_group(callback, session)


# =============================================================================
# View Proxies in Group
# =============================================================================

@router.callback_query(F.data.startswith("proxy_group:proxies:"))
async def view_proxies_in_group(callback: CallbackQuery, session: AsyncSession) -> None:
    """View proxies in a group."""
    group_id = UUID(callback.data.split(":")[2])

    repo = ProxyGroupRepository(session)
    group = await repo.get_by_id(group_id)

    if not group:
        await callback.answer("Группа не найдена", show_alert=True)
        return

    proxies = await repo.get_proxies_in_group(group_id)

    if not proxies:
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(
            text="➕ Добавить прокси",
            callback_data=f"proxy_group:add_proxies:{group_id}",
        ))
        kb.row(InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"proxy_group:view:{group_id}",
        ))
        await callback.message.edit_text(
            f"📁 <b>{group.name}</b> - Прокси\n\n"
            "В группе нет прокси.",
            reply_markup=kb.as_markup(),
        )
        await callback.answer()
        return

    text = f"📁 <b>{group.name}</b> - Прокси ({len(proxies)})\n\n"

    status_emoji = {
        "active": "🟢",
        "slow": "🟡",
        "unavailable": "🔴",
        "banned": "⛔",
        "unknown": "⚪",
    }

    # Check which proxies are assigned
    proxy_repo = PostgresProxyRepository(session)

    for proxy in proxies[:20]:
        emoji = status_emoji.get(proxy.status.value, "❓")
        is_assigned = await proxy_repo.is_assigned(proxy.id)
        assigned_mark = " 📱" if is_assigned else " ✅"
        latency = f" ({proxy.last_check_latency_ms}ms)" if proxy.last_check_latency_ms else ""
        text += f"{emoji} {proxy.host}:{proxy.port}{latency}{assigned_mark}\n"

    text += "\n<i>📱 = занят, ✅ = свободен</i>"

    if len(proxies) > 20:
        text += f"\n\n... и ещё {len(proxies) - 20}"

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="➕ Добавить прокси",
        callback_data=f"proxy_group:add_proxies:{group_id}",
    ))
    kb.row(InlineKeyboardButton(
        text="◀️ Назад",
        callback_data=f"proxy_group:view:{group_id}",
    ))

    await callback.message.edit_text(text, reply_markup=kb.as_markup())
    await callback.answer()


# =============================================================================
# Delete Group
# =============================================================================

@router.callback_query(F.data.startswith("proxy_group:delete:"))
async def delete_group_confirm(callback: CallbackQuery) -> None:
    """Confirm group deletion."""
    group_id = callback.data.split(":")[2]

    await callback.message.edit_text(
        "⚠️ <b>Удаление группы</b>\n\n"
        "Вы уверены, что хотите удалить эту группу?\n"
        "Прокси останутся, удалится только группа.",
        reply_markup=get_confirm_kb(
            confirm_callback=f"proxy_group:delete:confirm:{group_id}",
            cancel_callback=f"proxy_group:view:{group_id}",
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("proxy_group:delete:confirm:"))
async def delete_group(callback: CallbackQuery, session: AsyncSession) -> None:
    """Delete a proxy group."""
    group_id = UUID(callback.data.split(":")[3])

    repo = ProxyGroupRepository(session)
    deleted = await repo.delete(group_id)

    if deleted:
        await callback.answer("✅ Группа удалена")
        await callback.message.edit_text(
            "✅ Группа удалена.",
            reply_markup=get_proxy_groups_menu_kb(),
        )
    else:
        await callback.answer("❌ Не удалось удалить группу", show_alert=True)


# =============================================================================
# Edit Group
# =============================================================================

@router.callback_query(F.data.startswith("proxy_group:edit:"))
async def edit_group_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show edit menu for a group."""
    group_id = UUID(callback.data.split(":")[2])

    repo = ProxyGroupRepository(session)
    group = await repo.get_by_id(group_id)

    if not group:
        await callback.answer("Группа не найдена", show_alert=True)
        return

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="✏️ Название",
        callback_data=f"proxy_group:edit_name:{group_id}",
    ))
    kb.row(InlineKeyboardButton(
        text="📝 Описание",
        callback_data=f"proxy_group:edit_desc:{group_id}",
    ))
    kb.row(InlineKeyboardButton(
        text="◀️ Назад",
        callback_data=f"proxy_group:view:{group_id}",
    ))

    await callback.message.edit_text(
        f"✏️ <b>Редактирование: {group.name}</b>\n\n"
        "Что изменить?",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("proxy_group:edit_name:"))
async def edit_group_name_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing group name."""
    group_id = callback.data.split(":")[2]
    await state.update_data(edit_group_id=group_id)
    await state.set_state(ProxyGroupStates.waiting_edit_name)

    await callback.message.edit_text(
        "✏️ <b>Редактирование названия</b>\n\n"
        "Введите новое название группы:",
    )
    await callback.message.answer(
        "Ожидаю новое название...",
        reply_markup=get_cancel_kb(),
    )
    await callback.answer()


@router.message(ProxyGroupStates.waiting_edit_name)
async def edit_group_name_save(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Save new group name."""
    name = message.text.strip()

    if len(name) < 2 or len(name) > 100:
        await message.answer("❌ Название должно быть от 2 до 100 символов")
        return

    data = await state.get_data()
    group_id = UUID(data["edit_group_id"])
    await state.clear()

    repo = ProxyGroupRepository(session)
    group = await repo.get_by_id(group_id)

    if not group:
        await message.answer("❌ Группа не найдена", reply_markup=get_main_menu_kb())
        return

    # Check name uniqueness
    existing = await repo.get_by_name(name)
    if existing and existing.id != group_id:
        await message.answer("❌ Группа с таким названием уже существует")
        return

    group.name = name
    await repo.save(group)

    await message.answer(
        f"✅ Название изменено на: <b>{name}</b>",
        reply_markup=get_main_menu_kb(),
    )


@router.callback_query(F.data.startswith("proxy_group:edit_desc:"))
async def edit_group_desc_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing group description."""
    group_id = callback.data.split(":")[2]
    await state.update_data(edit_group_id=group_id)
    await state.set_state(ProxyGroupStates.waiting_edit_description)

    await callback.message.edit_text(
        "✏️ <b>Редактирование описания</b>\n\n"
        "Введите новое описание группы\n"
        "или <code>-</code> чтобы удалить:",
    )
    await callback.message.answer(
        "Ожидаю новое описание...",
        reply_markup=get_cancel_kb(),
    )
    await callback.answer()


@router.message(ProxyGroupStates.waiting_edit_description)
async def edit_group_desc_save(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Save new group description."""
    description = message.text.strip()

    if description == "-":
        description = None

    data = await state.get_data()
    group_id = UUID(data["edit_group_id"])
    await state.clear()

    repo = ProxyGroupRepository(session)
    group = await repo.get_by_id(group_id)

    if not group:
        await message.answer("❌ Группа не найдена", reply_markup=get_main_menu_kb())
        return

    group.description = description
    await repo.save(group)

    await message.answer(
        "✅ Описание обновлено",
        reply_markup=get_main_menu_kb(),
    )


# =============================================================================
# Check Proxies in Group
# =============================================================================

@router.callback_query(F.data.startswith("proxy_group:check:"))
async def check_proxies_in_group(callback: CallbackQuery, session: AsyncSession) -> None:
    """Check all proxies in a group."""
    import asyncio
    import aiohttp
    import python_socks
    from aiohttp_socks import ProxyConnector
    from src.domain.entities import ProxyStatus

    group_id = UUID(callback.data.split(":")[2])

    repo = ProxyGroupRepository(session)
    group = await repo.get_by_id(group_id)

    if not group:
        await callback.answer("Группа не найдена", show_alert=True)
        return

    proxies = await repo.get_proxies_in_group(group_id)

    if not proxies:
        await callback.answer("В группе нет прокси", show_alert=True)
        return

    await callback.answer()

    status_msg = await callback.message.edit_text(
        f"🔄 <b>Проверка прокси в группе {group.name}</b>\n\n"
        f"Проверяется: 0/{len(proxies)}..."
    )

    proxy_repo = PostgresProxyRepository(session)
    results = {"active": 0, "slow": 0, "unavailable": 0}

    async def check_single_proxy(proxy):
        """Check a single proxy."""
        import time

        proxy_type_map = {
            "socks5": python_socks.ProxyType.SOCKS5,
            "socks4": python_socks.ProxyType.SOCKS4,
            "http": python_socks.ProxyType.HTTP,
            "https": python_socks.ProxyType.HTTP,
        }

        try:
            connector = ProxyConnector(
                proxy_type=proxy_type_map.get(proxy.proxy_type.value, python_socks.ProxyType.SOCKS5),
                host=proxy.host,
                port=proxy.port,
                username=proxy.username,
                password=proxy.password,
                rdns=True,
            )

            start_time = time.time()

            async with aiohttp.ClientSession(connector=connector) as http_session:
                async with http_session.get(
                    "https://api.telegram.org",
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as response:
                    latency = int((time.time() - start_time) * 1000)

                    if response.status == 200:
                        proxy.last_check_latency_ms = latency
                        if latency < 3000:
                            proxy.status = ProxyStatus.ACTIVE
                            return "active"
                        else:
                            proxy.status = ProxyStatus.SLOW
                            return "slow"
                    else:
                        proxy.status = ProxyStatus.UNAVAILABLE
                        return "unavailable"

        except Exception:
            proxy.status = ProxyStatus.UNAVAILABLE
            proxy.last_check_latency_ms = None
            return "unavailable"

    checked = 0
    batch_size = 10

    for i in range(0, len(proxies), batch_size):
        batch = proxies[i:i + batch_size]
        tasks = [check_single_proxy(p) for p in batch]
        batch_results = await asyncio.gather(*tasks)

        for result in batch_results:
            results[result] += 1
            checked += 1

        # Update status message every batch
        try:
            await status_msg.edit_text(
                f"🔄 <b>Проверка прокси в группе {group.name}</b>\n\n"
                f"Проверено: {checked}/{len(proxies)}\n\n"
                f"🟢 Активных: {results['active']}\n"
                f"🟡 Медленных: {results['slow']}\n"
                f"🔴 Недоступных: {results['unavailable']}"
            )
        except Exception:
            pass

        # Save batch
        for p in batch:
            await proxy_repo.save(p)

    # Final message
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="📋 Прокси в группе",
        callback_data=f"proxy_group:proxies:{group_id}",
    ))
    kb.row(InlineKeyboardButton(
        text="◀️ К группе",
        callback_data=f"proxy_group:view:{group_id}",
    ))

    await status_msg.edit_text(
        f"✅ <b>Проверка завершена: {group.name}</b>\n\n"
        f"Всего проверено: {len(proxies)}\n\n"
        f"🟢 Активных: {results['active']}\n"
        f"🟡 Медленных: {results['slow']}\n"
        f"🔴 Недоступных: {results['unavailable']}",
        reply_markup=kb.as_markup(),
    )
