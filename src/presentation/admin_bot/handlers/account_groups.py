"""
Account group management handlers.

Allows grouping accounts for batch operations and campaign assignment.
"""

from uuid import UUID, uuid4

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities import AccountGroup, AccountSource, AccountStatus
from src.infrastructure.database.repositories import (
    PostgresAccountRepository,
    AccountGroupRepository,
    PostgresProxyRepository,
)

router = Router(name="account_groups")


class GroupStates(StatesGroup):
    """FSM states for group management."""

    waiting_group_name = State()
    waiting_group_description = State()
    selecting_accounts = State()
    confirming_delete = State()

    # Mass customization
    waiting_names_file = State()
    waiting_bios_file = State()
    waiting_avatars_zip = State()


# =============================================================================
# Group List
# =============================================================================


@router.callback_query(F.data == "groups:list")
async def groups_list(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show list of all account groups."""
    repo = AccountGroupRepository(session)
    groups = await repo.get_all()

    builder = InlineKeyboardBuilder()

    if groups:
        for group in groups:
            builder.row(
                InlineKeyboardButton(
                    text=f"📁 {group.name} ({group.account_count})",
                    callback_data=f"group:view:{group.id}",
                )
            )

    builder.row(
        InlineKeyboardButton(text="➕ Создать группу", callback_data="group:create")
    )
    builder.row(
        InlineKeyboardButton(text="« Назад", callback_data="accounts:menu")
    )

    await callback.message.edit_text(
        "📁 <b>Группы аккаунтов</b>\n\n"
        f"Всего групп: {len(groups)}\n\n"
        "Группы позволяют объединять аккаунты и добавлять их в кампании одним действием.",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


# =============================================================================
# Create Group
# =============================================================================


@router.callback_query(F.data == "group:create")
async def group_create_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start group creation."""
    await state.set_state(GroupStates.waiting_group_name)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="groups:list"))

    await callback.message.edit_text(
        "📁 <b>Создание группы</b>\n\n"
        "Введите название группы:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.message(GroupStates.waiting_group_name)
async def group_create_name(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Process group name input."""
    name = message.text.strip()

    if len(name) < 2:
        await message.answer("Название должно быть не менее 2 символов. Попробуйте снова:")
        return

    if len(name) > 100:
        await message.answer("Название слишком длинное (макс. 100 символов). Попробуйте снова:")
        return

    # Check if name already exists
    repo = AccountGroupRepository(session)
    existing = await repo.get_by_name(name)
    if existing:
        await message.answer(f"Группа с названием '{name}' уже существует. Введите другое название:")
        return

    await state.update_data(group_name=name)
    await state.set_state(GroupStates.waiting_group_description)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⏩ Пропустить", callback_data="group:skip_description"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="groups:list"))

    await message.answer(
        f"📁 <b>Создание группы: {name}</b>\n\n"
        "Введите описание группы (опционально):",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == "group:skip_description")
async def group_skip_description(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Skip description and create group."""
    await _create_group(callback, state, session, description=None)


@router.message(GroupStates.waiting_group_description)
async def group_create_description(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Process group description and create group."""
    description = message.text.strip() if message.text else None
    await _create_group_from_message(message, state, session, description)


async def _create_group(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    description: str | None,
) -> None:
    """Create group helper for callback."""
    data = await state.get_data()
    name = data.get("group_name")

    if not name:
        await callback.answer("Ошибка: название не найдено", show_alert=True)
        return

    repo = AccountGroupRepository(session)

    group = AccountGroup(
        id=uuid4(),
        name=name,
        description=description,
    )
    saved = await repo.save(group)
    await session.commit()

    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Добавить аккаунты", callback_data=f"group:add_accounts:{saved.id}")
    )
    builder.row(
        InlineKeyboardButton(text="« К списку групп", callback_data="groups:list")
    )

    await callback.message.edit_text(
        f"✅ <b>Группа создана</b>\n\n"
        f"📁 {saved.name}\n"
        f"📝 {saved.description or 'Без описания'}\n\n"
        "Теперь добавьте аккаунты в группу.",
        reply_markup=builder.as_markup(),
    )
    await callback.answer("Группа создана!")


async def _create_group_from_message(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    description: str | None,
) -> None:
    """Create group helper for message."""
    data = await state.get_data()
    name = data.get("group_name")

    if not name:
        await message.answer("Ошибка: название не найдено")
        return

    repo = AccountGroupRepository(session)

    group = AccountGroup(
        id=uuid4(),
        name=name,
        description=description,
    )
    saved = await repo.save(group)
    await session.commit()

    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Добавить аккаунты", callback_data=f"group:add_accounts:{saved.id}")
    )
    builder.row(
        InlineKeyboardButton(text="« К списку групп", callback_data="groups:list")
    )

    await message.answer(
        f"✅ <b>Группа создана</b>\n\n"
        f"📁 {saved.name}\n"
        f"📝 {saved.description or 'Без описания'}\n\n"
        "Теперь добавьте аккаунты в группу.",
        reply_markup=builder.as_markup(),
    )


# =============================================================================
# View Group
# =============================================================================


@router.callback_query(F.data.startswith("group:view:"))
async def group_view(callback: CallbackQuery, session: AsyncSession) -> None:
    """View group details."""
    group_id = UUID(callback.data.split(":")[2])

    repo = AccountGroupRepository(session)
    group = await repo.get_by_id(group_id)

    if not group:
        await callback.answer("Группа не найдена", show_alert=True)
        return

    # Get account details
    account_repo = PostgresAccountRepository(session)
    accounts_text = ""

    if group.account_ids:
        accounts = []
        for acc_id in group.account_ids[:10]:  # Show first 10
            acc = await account_repo.get_by_id(acc_id)
            if acc:
                status_emoji = {
                    "active": "🟢",
                    "paused": "⏸️",
                    "error": "🔴",
                    "banned": "⛔",
                    "ready": "🟡",
                    "inactive": "⚪",
                }.get(acc.status.value, "❓")
                accounts.append(f"  {status_emoji} {acc.phone} (@{acc.username or 'N/A'})")

        accounts_text = "\n".join(accounts)
        if len(group.account_ids) > 10:
            accounts_text += f"\n  ... и ещё {len(group.account_ids) - 10}"
    else:
        accounts_text = "  <i>Нет аккаунтов</i>"

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Добавить аккаунты", callback_data=f"group:add_accounts:{group_id}")
    )
    if group.account_ids:
        builder.row(
            InlineKeyboardButton(text="➖ Удалить аккаунты", callback_data=f"group:remove_accounts:{group_id}")
        )
        builder.row(
            InlineKeyboardButton(text="🔄 Массовая переавторизация", callback_data=f"group:reauth:{group_id}")
        )
        builder.row(
            InlineKeyboardButton(text="✏️ Массовая кастомизация", callback_data=f"group:customize:{group_id}")
        )
    builder.row(
        InlineKeyboardButton(text="🗑 Удалить группу", callback_data=f"group:delete:{group_id}")
    )
    builder.row(
        InlineKeyboardButton(text="« Назад", callback_data="groups:list")
    )

    await callback.message.edit_text(
        f"📁 <b>Группа: {group.name}</b>\n\n"
        f"📝 {group.description or 'Без описания'}\n\n"
        f"👥 <b>Аккаунты ({group.account_count}):</b>\n"
        f"{accounts_text}",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


# =============================================================================
# Add Accounts to Group
# =============================================================================


@router.callback_query(F.data.startswith("group:add_accounts:"))
async def group_add_accounts_menu(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Show accounts available to add to group."""
    group_id = UUID(callback.data.split(":")[2])

    repo = AccountGroupRepository(session)
    group = await repo.get_by_id(group_id)

    if not group:
        await callback.answer("Группа не найдена", show_alert=True)
        return

    # Get accounts without a group
    available = await repo.get_accounts_without_group()

    await state.update_data(group_id=str(group_id))

    builder = InlineKeyboardBuilder()

    if available:
        for acc_id, phone, username in available[:20]:  # Limit to 20
            display = f"{phone}" + (f" (@{username})" if username else "")
            builder.row(
                InlineKeyboardButton(
                    text=f"➕ {display}",
                    callback_data=f"group:add_one:{acc_id}",
                )
            )

        if len(available) > 20:
            builder.row(
                InlineKeyboardButton(
                    text=f"📋 Добавить все ({len(available)})",
                    callback_data=f"group:add_all:{group_id}",
                )
            )
    else:
        await callback.message.edit_text(
            f"📁 <b>Группа: {group.name}</b>\n\n"
            "Все аккаунты уже распределены по группам.",
            reply_markup=InlineKeyboardBuilder().row(
                InlineKeyboardButton(text="« Назад", callback_data=f"group:view:{group_id}")
            ).as_markup(),
        )
        await callback.answer()
        return

    builder.row(
        InlineKeyboardButton(text="« Назад", callback_data=f"group:view:{group_id}")
    )

    await callback.message.edit_text(
        f"📁 <b>Добавить в группу: {group.name}</b>\n\n"
        f"Доступно аккаунтов: {len(available)}\n\n"
        "Выберите аккаунты для добавления:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("group:add_one:"))
async def group_add_one_account(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Add single account to group."""
    account_id = UUID(callback.data.split(":")[2])
    data = await state.get_data()
    group_id = UUID(data.get("group_id"))

    repo = AccountGroupRepository(session)
    success = await repo.add_account(group_id, account_id)
    await session.commit()

    if success:
        await callback.answer("✅ Аккаунт добавлен")
    else:
        await callback.answer("❌ Ошибка добавления", show_alert=True)

    # Refresh the add menu
    await group_add_accounts_menu(callback, state, session)


@router.callback_query(F.data.startswith("group:add_all:"))
async def group_add_all_accounts(callback: CallbackQuery, session: AsyncSession) -> None:
    """Add all available accounts to group."""
    group_id = UUID(callback.data.split(":")[2])

    repo = AccountGroupRepository(session)
    available = await repo.get_accounts_without_group()

    count = 0
    for acc_id, _, _ in available:
        if await repo.add_account(group_id, acc_id):
            count += 1

    await session.commit()

    await callback.answer(f"✅ Добавлено {count} аккаунтов")

    # Go back to group view
    callback.data = f"group:view:{group_id}"
    await group_view(callback, session)


# =============================================================================
# Remove Accounts from Group
# =============================================================================


@router.callback_query(F.data.startswith("group:remove_accounts:"))
async def group_remove_accounts_menu(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Show accounts to remove from group."""
    group_id = UUID(callback.data.split(":")[2])

    repo = AccountGroupRepository(session)
    group = await repo.get_by_id(group_id)

    if not group:
        await callback.answer("Группа не найдена", show_alert=True)
        return

    await state.update_data(group_id=str(group_id))

    account_repo = PostgresAccountRepository(session)
    builder = InlineKeyboardBuilder()

    for acc_id in group.account_ids[:20]:
        acc = await account_repo.get_by_id(acc_id)
        if acc:
            display = f"{acc.phone}" + (f" (@{acc.username})" if acc.username else "")
            builder.row(
                InlineKeyboardButton(
                    text=f"➖ {display}",
                    callback_data=f"group:remove_one:{acc_id}",
                )
            )

    builder.row(
        InlineKeyboardButton(text="« Назад", callback_data=f"group:view:{group_id}")
    )

    await callback.message.edit_text(
        f"📁 <b>Удалить из группы: {group.name}</b>\n\n"
        "Выберите аккаунты для удаления:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("group:remove_one:"))
async def group_remove_one_account(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Remove single account from group."""
    account_id = UUID(callback.data.split(":")[2])
    data = await state.get_data()
    group_id = UUID(data.get("group_id"))

    repo = AccountGroupRepository(session)
    success = await repo.remove_account(group_id, account_id)
    await session.commit()

    if success:
        await callback.answer("✅ Аккаунт удалён из группы")
    else:
        await callback.answer("❌ Ошибка удаления", show_alert=True)

    # Refresh the remove menu
    await group_remove_accounts_menu(callback, state, session)


# =============================================================================
# Delete Group
# =============================================================================


@router.callback_query(F.data.startswith("group:delete:"))
async def group_delete_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    """Confirm group deletion."""
    group_id = UUID(callback.data.split(":")[2])

    repo = AccountGroupRepository(session)
    group = await repo.get_by_id(group_id)

    if not group:
        await callback.answer("Группа не найдена", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"group:delete_confirm:{group_id}")
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"group:view:{group_id}")
    )

    await callback.message.edit_text(
        f"🗑 <b>Удаление группы</b>\n\n"
        f"Вы уверены, что хотите удалить группу <b>{group.name}</b>?\n\n"
        f"Аккаунтов в группе: {group.account_count}\n\n"
        "⚠️ Аккаунты НЕ будут удалены, только группа.",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("group:delete_confirm:"))
async def group_delete_execute(callback: CallbackQuery, session: AsyncSession) -> None:
    """Execute group deletion."""
    group_id = UUID(callback.data.split(":")[2])

    repo = AccountGroupRepository(session)
    success = await repo.delete(group_id)
    await session.commit()

    if success:
        await callback.answer("✅ Группа удалена")
        # Go back to groups list
        callback.data = "groups:list"
        await groups_list(callback, session)
    else:
        await callback.answer("❌ Ошибка удаления", show_alert=True)


# =============================================================================
# Mass Re-authorization
# =============================================================================


@router.callback_query(F.data.regexp(r"^group:reauth:[0-9a-f-]+$"))
async def group_reauth_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Start mass re-authorization for group accounts."""
    from src.domain.entities import AccountSource
    from src.infrastructure.database.repositories import PostgresProxyRepository

    group_id = UUID(callback.data.split(":")[2])

    repo = AccountGroupRepository(session)
    group = await repo.get_by_id(group_id)

    if not group or not group.account_ids:
        await callback.answer("Группа пуста", show_alert=True)
        return

    # Get accounts that need re-authorization (json_session or tdata)
    account_repo = PostgresAccountRepository(session)
    proxy_repo = PostgresProxyRepository(session)

    accounts_to_reauth = []
    accounts_without_proxy = []

    for acc_id in group.account_ids:
        acc = await account_repo.get_by_id(acc_id)
        if acc and acc.source in (AccountSource.JSON_SESSION, AccountSource.TDATA):
            if acc.proxy_id:
                proxy = await proxy_repo.get_by_id(acc.proxy_id)
                if proxy:
                    accounts_to_reauth.append((acc, proxy))
                else:
                    accounts_without_proxy.append(acc)
            else:
                accounts_without_proxy.append(acc)

    if not accounts_to_reauth:
        msg = "ℹ️ <b>Нет аккаунтов для переавторизации</b>\n\n"
        if accounts_without_proxy:
            msg += f"⚠️ {len(accounts_without_proxy)} аккаунтов без прокси\n"
        msg += "\nПереавторизация доступна только для аккаунтов:\n• Загруженных через JSON+Session\n• Загруженных через TData\n• С назначенным прокси"

        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="« Назад", callback_data=f"group:view:{group_id}"))

        await callback.message.edit_text(msg, reply_markup=builder.as_markup())
        await callback.answer()
        return

    # Save to state for processing
    await state.update_data(
        group_reauth_id=str(group_id),
        group_reauth_accounts=[(str(acc.id), str(proxy.id)) for acc, proxy in accounts_to_reauth],
        group_reauth_index=0,
        group_reauth_success=0,
        group_reauth_failed=0,
    )
    await state.set_state(GroupStates.waiting_group_name)  # Reuse state for 2FA input

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="🚀 Начать (без 2FA)",
        callback_data=f"group:reauth:start:{group_id}:no2fa",
    ))
    builder.row(InlineKeyboardButton(
        text="❌ Отмена",
        callback_data=f"group:view:{group_id}",
    ))

    warning = ""
    if accounts_without_proxy:
        warning = f"\n⚠️ {len(accounts_without_proxy)} аккаунтов пропущено (нет прокси)"

    await callback.message.edit_text(
        f"🔄 <b>Массовая переавторизация</b>\n\n"
        f"📁 Группа: {group.name}\n"
        f"👥 Аккаунтов для переавторизации: {len(accounts_to_reauth)}"
        f"{warning}\n\n"
        f"<b>Процесс:</b>\n"
        f"1️⃣ Бот подключится к каждому аккаунту\n"
        f"2️⃣ Запросит новый код авторизации\n"
        f"3️⃣ Перехватит код из старой сессии\n"
        f"4️⃣ Создаст новую нативную сессию\n\n"
        f"⚠️ Если у аккаунтов есть 2FA, введите пароль:\n"
        f"<i>(или нажмите 'Начать без 2FA')</i>",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^group:reauth:start:[0-9a-f-]+:no2fa$"))
async def group_reauth_execute_no2fa(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Start mass re-authorization without 2FA."""
    group_id = UUID(callback.data.split(":")[3])
    await _execute_group_reauth(callback, state, session, group_id, None)


@router.message(GroupStates.waiting_group_name)
async def group_reauth_with_2fa(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Receive 2FA password for mass re-authorization."""
    data = await state.get_data()

    # Check if this is actually for reauth
    if "group_reauth_id" not in data:
        # This is regular group name input, call original handler
        from src.presentation.admin_bot.handlers.account_groups import group_create_name
        # Skip - handled by priority
        return

    group_id = UUID(data.get("group_reauth_id"))
    twofa_password = message.text.strip()

    # Delete password message
    try:
        await message.delete()
    except Exception:
        pass

    await _execute_group_reauth(message, state, session, group_id, twofa_password)


async def _execute_group_reauth(
    event,
    state: FSMContext,
    session: AsyncSession,
    group_id: UUID,
    twofa_password: str | None,
) -> None:
    """Execute mass re-authorization for group."""
    import asyncio
    from src.application.services.account_auth import get_auth_service
    from src.domain.entities import AccountSource, AccountStatus
    from src.infrastructure.database.repositories import PostgresProxyRepository

    # Get message object
    if hasattr(event, 'message'):
        msg = event.message
    else:
        msg = event

    data = await state.get_data()
    accounts_data = data.get("group_reauth_accounts", [])

    if not accounts_data:
        await msg.answer("❌ Нет аккаунтов для переавторизации")
        await state.clear()
        return

    account_repo = PostgresAccountRepository(session)
    proxy_repo = PostgresProxyRepository(session)
    auth_service = get_auth_service()

    # Create status message
    status_msg = await msg.answer(
        f"🔄 <b>Массовая переавторизация</b>\n\n"
        f"⏳ Начинаю... (0/{len(accounts_data)})",
    )

    success_count = 0
    failed_count = 0
    results = []

    for i, (acc_id_str, proxy_id_str) in enumerate(accounts_data):
        acc_id = UUID(acc_id_str)
        proxy_id = UUID(proxy_id_str)

        account = await account_repo.get_by_id(acc_id)
        proxy = await proxy_repo.get_by_id(proxy_id)

        if not account or not proxy:
            failed_count += 1
            results.append(f"❌ {acc_id_str[:8]}...: не найден")
            continue

        # Update status
        try:
            await status_msg.edit_text(
                f"🔄 <b>Массовая переавторизация</b>\n\n"
                f"📱 Текущий: {account.phone}\n"
                f"📊 Прогресс: {i + 1}/{len(accounts_data)}\n"
                f"✅ Успешно: {success_count} | ❌ Ошибок: {failed_count}",
            )
        except Exception:
            pass

        try:
            # Perform re-authorization
            new_session_data, user_info = await auth_service.auto_reauthorize(
                old_session_data=account.session_data,
                phone=account.phone,
                proxy=proxy,
                twofa_password=twofa_password,
                timeout_seconds=90,  # Shorter timeout for batch
            )

            # Update account
            account.session_data = new_session_data
            account.source = AccountSource.PHONE
            account.telegram_id = user_info.get("telegram_id")
            account.username = user_info.get("username")
            account.first_name = user_info.get("first_name", "")
            account.last_name = user_info.get("last_name", "")
            account.is_premium = user_info.get("is_premium", False)
            account.status = AccountStatus.READY
            account.error_message = None

            await account_repo.save(account)

            success_count += 1
            results.append(f"✅ {account.phone}: OK")

        except TimeoutError:
            failed_count += 1
            results.append(f"⏰ {account.phone}: таймаут")

        except ValueError as e:
            failed_count += 1
            error_msg = str(e)[:30]
            results.append(f"❌ {account.phone}: {error_msg}")

        except Exception as e:
            failed_count += 1
            error_msg = str(e)[:30]
            results.append(f"❌ {account.phone}: {error_msg}")

        # Small delay between accounts
        await asyncio.sleep(2)

    await state.clear()

    # Build final results
    results_text = "\n".join(results[-15:])  # Show last 15
    if len(results) > 15:
        results_text = f"... и ещё {len(results) - 15}\n" + results_text

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="« К группе", callback_data=f"group:view:{group_id}"))

    await status_msg.edit_text(
        f"✅ <b>Переавторизация завершена</b>\n\n"
        f"📊 <b>Результаты:</b>\n"
        f"✅ Успешно: {success_count}\n"
        f"❌ Ошибок: {failed_count}\n\n"
        f"<b>Детали:</b>\n{results_text}",
        reply_markup=builder.as_markup(),
    )


# =============================================================================
# Mass Customization
# =============================================================================


@router.callback_query(F.data.regexp(r"^group:customize:[0-9a-f-]+$"))
async def group_customize_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show mass customization options for group."""
    group_id = UUID(callback.data.split(":")[2])

    repo = AccountGroupRepository(session)
    group = await repo.get_by_id(group_id)

    if not group or not group.account_ids:
        await callback.answer("Группа пуста", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="👤 Загрузить имена (TXT)",
        callback_data=f"group:customize:names:{group_id}",
    ))
    builder.row(InlineKeyboardButton(
        text="📝 Загрузить био (TXT)",
        callback_data=f"group:customize:bios:{group_id}",
    ))
    builder.row(InlineKeyboardButton(
        text="🖼 Загрузить аватары (ZIP)",
        callback_data=f"group:customize:avatars:{group_id}",
    ))
    builder.row(InlineKeyboardButton(
        text="« Назад",
        callback_data=f"group:view:{group_id}",
    ))

    await callback.message.edit_text(
        f"✏️ <b>Массовая кастомизация</b>\n\n"
        f"📁 Группа: {group.name}\n"
        f"👥 Аккаунтов: {group.account_count}\n\n"
        f"<b>Форматы файлов:</b>\n\n"
        f"<b>Имена (TXT):</b>\n"
        f"<code>Имя Фамилия</code> - одно на строку\n\n"
        f"<b>Био (TXT):</b>\n"
        f"<code>Описание профиля</code> - одно на строку\n\n"
        f"<b>Аватары (ZIP):</b>\n"
        f"<code>photo1.jpg, photo2.jpg, ...</code>\n\n"
        f"⚡ Данные распределяются пропорционально по аккаунтам",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^group:customize:names:[0-9a-f-]+$"))
async def group_customize_names_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Start mass name customization - prompt for file."""
    group_id = UUID(callback.data.split(":")[3])

    repo = AccountGroupRepository(session)
    group = await repo.get_by_id(group_id)

    if not group:
        await callback.answer("Группа не найдена", show_alert=True)
        return

    await state.update_data(customize_group_id=str(group_id))
    await state.set_state(GroupStates.waiting_names_file)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="❌ Отмена",
        callback_data=f"group:customize:{group_id}",
    ))

    await callback.message.edit_text(
        f"👤 <b>Загрузка имён</b>\n\n"
        f"Группа: {group.name}\n"
        f"Аккаунтов: {group.account_count}\n\n"
        f"Отправьте TXT файл с именами:\n"
        f"<code>Имя Фамилия</code>\n"
        f"<code>Имя2 Фамилия2</code>\n"
        f"<code>...</code>\n\n"
        f"⚡ Если имён меньше чем аккаунтов - они будут циклически повторяться",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.message(GroupStates.waiting_names_file, F.document)
async def group_customize_names_receive(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Receive and process names file."""
    import asyncio
    from src.application.services.account_profile import get_profile_service

    data = await state.get_data()
    group_id = UUID(data.get("customize_group_id"))

    doc = message.document
    if not doc.file_name.endswith('.txt'):
        await message.answer("❌ Отправьте файл .txt")
        return

    repo = AccountGroupRepository(session)
    group = await repo.get_by_id(group_id)

    if not group:
        await message.answer("❌ Группа не найдена")
        await state.clear()
        return

    # Download and parse file
    file = await message.bot.download(doc)
    content = file.read().decode('utf-8', errors='ignore')
    lines = [l.strip() for l in content.split('\n') if l.strip()]

    if not lines:
        await message.answer("❌ Файл пуст")
        return

    # Parse names
    names = []
    for line in lines:
        parts = line.split(None, 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else ""
        names.append((first_name, last_name))

    status_msg = await message.answer(
        f"⏳ <b>Обновляю имена</b>\n\n"
        f"Имён в файле: {len(names)}\n"
        f"Аккаунтов: {group.account_count}\n\n"
        f"Начинаю..."
    )

    account_repo = PostgresAccountRepository(session)
    proxy_repo = PostgresProxyRepository(session)
    profile_service = get_profile_service()

    success_count = 0
    failed_count = 0
    results = []

    for i, acc_id in enumerate(group.account_ids):
        account = await account_repo.get_by_id(acc_id)
        if not account or not account.proxy_id:
            failed_count += 1
            continue

        proxy = await proxy_repo.get_by_id(account.proxy_id)
        if not proxy:
            failed_count += 1
            continue

        # Get name (cycle if needed)
        first_name, last_name = names[i % len(names)]

        try:
            # Update progress
            await status_msg.edit_text(
                f"⏳ <b>Обновляю имена</b>\n\n"
                f"Прогресс: {i + 1}/{group.account_count}\n"
                f"Текущий: {account.phone}\n"
                f"Новое имя: {first_name} {last_name}"
            )

            await profile_service.update_profile(
                session_data=account.session_data,
                proxy=proxy,
                first_name=first_name,
                last_name=last_name,
            )

            # Update DB
            account.first_name = first_name
            account.last_name = last_name
            await account_repo.save(account)

            success_count += 1
            results.append(f"✅ {account.phone}: {first_name} {last_name}")

        except Exception as e:
            failed_count += 1
            results.append(f"❌ {account.phone}: {str(e)[:30]}")

        await asyncio.sleep(1)  # Rate limit

    await state.clear()

    results_text = "\n".join(results[-10:])
    if len(results) > 10:
        results_text = f"... и ещё {len(results) - 10}\n" + results_text

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="« К группе", callback_data=f"group:view:{group_id}"))

    await status_msg.edit_text(
        f"✅ <b>Имена обновлены</b>\n\n"
        f"✅ Успешно: {success_count}\n"
        f"❌ Ошибок: {failed_count}\n\n"
        f"<b>Детали:</b>\n{results_text}",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.regexp(r"^group:customize:bios:[0-9a-f-]+$"))
async def group_customize_bios_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Start mass bio customization - prompt for file."""
    group_id = UUID(callback.data.split(":")[3])

    repo = AccountGroupRepository(session)
    group = await repo.get_by_id(group_id)

    if not group:
        await callback.answer("Группа не найдена", show_alert=True)
        return

    await state.update_data(customize_group_id=str(group_id))
    await state.set_state(GroupStates.waiting_bios_file)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="❌ Отмена",
        callback_data=f"group:customize:{group_id}",
    ))

    await callback.message.edit_text(
        f"📝 <b>Загрузка био</b>\n\n"
        f"Группа: {group.name}\n"
        f"Аккаунтов: {group.account_count}\n\n"
        f"Отправьте TXT файл с описаниями:\n"
        f"<code>Описание профиля 1</code>\n"
        f"<code>Описание профиля 2</code>\n"
        f"<code>...</code>\n\n"
        f"⚠️ Макс 70 символов на описание",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.message(GroupStates.waiting_bios_file, F.document)
async def group_customize_bios_receive(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Receive and process bios file."""
    import asyncio
    from src.application.services.account_profile import get_profile_service

    data = await state.get_data()
    group_id = UUID(data.get("customize_group_id"))

    doc = message.document
    if not doc.file_name.endswith('.txt'):
        await message.answer("❌ Отправьте файл .txt")
        return

    repo = AccountGroupRepository(session)
    group = await repo.get_by_id(group_id)

    if not group:
        await message.answer("❌ Группа не найдена")
        await state.clear()
        return

    # Download and parse file
    file = await message.bot.download(doc)
    content = file.read().decode('utf-8', errors='ignore')
    bios = [l.strip()[:70] for l in content.split('\n') if l.strip()]  # Max 70 chars

    if not bios:
        await message.answer("❌ Файл пуст")
        return

    status_msg = await message.answer(
        f"⏳ <b>Обновляю био</b>\n\n"
        f"Описаний в файле: {len(bios)}\n"
        f"Аккаунтов: {group.account_count}\n\n"
        f"Начинаю..."
    )

    account_repo = PostgresAccountRepository(session)
    proxy_repo = PostgresProxyRepository(session)
    profile_service = get_profile_service()

    success_count = 0
    failed_count = 0

    for i, acc_id in enumerate(group.account_ids):
        account = await account_repo.get_by_id(acc_id)
        if not account or not account.proxy_id:
            failed_count += 1
            continue

        proxy = await proxy_repo.get_by_id(account.proxy_id)
        if not proxy:
            failed_count += 1
            continue

        bio = bios[i % len(bios)]

        try:
            await status_msg.edit_text(
                f"⏳ <b>Обновляю био</b>\n\n"
                f"Прогресс: {i + 1}/{group.account_count}\n"
                f"Текущий: {account.phone}"
            )

            await profile_service.update_profile(
                session_data=account.session_data,
                proxy=proxy,
                bio=bio,
            )

            success_count += 1

        except Exception as e:
            logger.error("Failed to update bio", account_id=str(acc_id), error=str(e))
            failed_count += 1

        await asyncio.sleep(1)

    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="« К группе", callback_data=f"group:view:{group_id}"))

    await status_msg.edit_text(
        f"✅ <b>Био обновлены</b>\n\n"
        f"✅ Успешно: {success_count}\n"
        f"❌ Ошибок: {failed_count}",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.regexp(r"^group:customize:avatars:[0-9a-f-]+$"))
async def group_customize_avatars_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Start mass avatar customization - prompt for ZIP."""
    group_id = UUID(callback.data.split(":")[3])

    repo = AccountGroupRepository(session)
    group = await repo.get_by_id(group_id)

    if not group:
        await callback.answer("Группа не найдена", show_alert=True)
        return

    await state.update_data(customize_group_id=str(group_id))
    await state.set_state(GroupStates.waiting_avatars_zip)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="❌ Отмена",
        callback_data=f"group:customize:{group_id}",
    ))

    await callback.message.edit_text(
        f"🖼 <b>Загрузка аватаров</b>\n\n"
        f"Группа: {group.name}\n"
        f"Аккаунтов: {group.account_count}\n\n"
        f"Отправьте ZIP архив с фотографиями:\n"
        f"<code>photos.zip/</code>\n"
        f"  ├── photo1.jpg\n"
        f"  ├── photo2.png\n"
        f"  └── ...\n\n"
        f"⚡ Фото распределяются пропорционально по аккаунтам",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.message(GroupStates.waiting_avatars_zip, F.document)
async def group_customize_avatars_receive(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Receive and process avatars ZIP."""
    import asyncio
    import io
    import zipfile
    from src.application.services.account_profile import get_profile_service

    data = await state.get_data()
    group_id = UUID(data.get("customize_group_id"))

    doc = message.document
    if not doc.file_name.endswith('.zip'):
        await message.answer("❌ Отправьте файл .zip")
        return

    repo = AccountGroupRepository(session)
    group = await repo.get_by_id(group_id)

    if not group:
        await message.answer("❌ Группа не найдена")
        await state.clear()
        return

    status_msg = await message.answer("⏳ Распаковываю архив...")

    # Download and extract ZIP
    file = await message.bot.download(doc)
    zip_bytes = file.read()

    photos = []
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zf:
            for name in zf.namelist():
                name_lower = name.lower()
                if name_lower.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                    photo_bytes = zf.read(name)
                    photos.append(photo_bytes)
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка распаковки: {str(e)[:100]}")
        await state.clear()
        return

    if not photos:
        await status_msg.edit_text("❌ В архиве нет изображений (jpg/png/webp)")
        await state.clear()
        return

    await status_msg.edit_text(
        f"⏳ <b>Обновляю аватары</b>\n\n"
        f"Фото в архиве: {len(photos)}\n"
        f"Аккаунтов: {group.account_count}\n\n"
        f"Начинаю..."
    )

    account_repo = PostgresAccountRepository(session)
    proxy_repo = PostgresProxyRepository(session)
    profile_service = get_profile_service()

    success_count = 0
    failed_count = 0

    for i, acc_id in enumerate(group.account_ids):
        account = await account_repo.get_by_id(acc_id)
        if not account or not account.proxy_id:
            failed_count += 1
            continue

        proxy = await proxy_repo.get_by_id(account.proxy_id)
        if not proxy:
            failed_count += 1
            continue

        photo_bytes = photos[i % len(photos)]

        try:
            await status_msg.edit_text(
                f"⏳ <b>Обновляю аватары</b>\n\n"
                f"Прогресс: {i + 1}/{group.account_count}\n"
                f"Текущий: {account.phone}"
            )

            await profile_service.update_photo(
                session_data=account.session_data,
                photo_bytes=photo_bytes,
                proxy=proxy,
            )

            success_count += 1

        except Exception:
            failed_count += 1

        await asyncio.sleep(2)  # Longer delay for photos

    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="« К группе", callback_data=f"group:view:{group_id}"))

    await status_msg.edit_text(
        f"✅ <b>Аватары обновлены</b>\n\n"
        f"✅ Успешно: {success_count}\n"
        f"❌ Ошибок: {failed_count}",
        reply_markup=builder.as_markup(),
    )
