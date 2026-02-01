"""
Telegram Apps management handlers.

Allows managing multiple API credentials (api_id/api_hash pairs)
for distributing accounts across different Telegram applications.
"""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from src.infrastructure.database.repositories import PostgresTelegramAppRepository
from src.domain.entities import TelegramApp

from ..keyboards import (
    get_telegram_apps_menu_kb,
    get_telegram_apps_list_kb,
    get_telegram_app_actions_kb,
    get_cancel_kb,
    get_main_menu_kb,
    get_back_kb,
    get_confirm_kb,
)
from ..states import TelegramAppStates

router = Router(name="telegram_apps")


@router.message(F.text == "📱 API Apps")
async def apps_menu(message: Message) -> None:
    """Show Telegram Apps menu."""
    await message.answer(
        "📱 <b>Telegram API Applications</b>\n\n"
        "Управление API credentials для аккаунтов.\n"
        "Рекомендация: 20-30 аккаунтов на 1 API ID.",
        reply_markup=get_telegram_apps_menu_kb(),
    )


@router.callback_query(F.data == "apps:menu")
async def apps_menu_callback(callback: CallbackQuery) -> None:
    """Show Telegram Apps menu via callback."""
    await callback.message.edit_text(
        "📱 <b>Telegram API Applications</b>\n\n"
        "Управление API credentials для аккаунтов.\n"
        "Рекомендация: 20-30 аккаунтов на 1 API ID.",
        reply_markup=get_telegram_apps_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "apps:list")
async def apps_list(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show list of Telegram Apps."""
    repo = PostgresTelegramAppRepository(session)
    apps = await repo.list_all(limit=50)

    if not apps:
        await callback.message.edit_text(
            "📱 <b>API Applications</b>\n\n"
            "Список пуст. Добавьте приложение.\n\n"
            "<i>Создайте приложение на my.telegram.org/apps</i>",
            reply_markup=get_telegram_apps_menu_kb(),
        )
        await callback.answer()
        return

    total_capacity = sum(app.max_accounts for app in apps)
    total_used = sum(app.current_account_count for app in apps)
    active_count = sum(1 for app in apps if app.is_active)

    text = (
        f"📱 <b>API Applications</b> ({len(apps)})\n\n"
        f"<b>Активных:</b> {active_count}\n"
        f"<b>Вместимость:</b> {total_used}/{total_capacity}\n"
        f"<b>Свободно слотов:</b> {total_capacity - total_used}\n\n"
        f"Выберите приложение:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_telegram_apps_list_kb(apps),
    )
    await callback.answer()


@router.callback_query(F.data == "apps:stats")
async def apps_stats(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show Telegram Apps statistics."""
    repo = PostgresTelegramAppRepository(session)
    apps = await repo.list_all(limit=100)

    if not apps:
        await callback.answer("Нет приложений", show_alert=True)
        return

    total_capacity = await repo.get_total_capacity()
    total_used = await repo.get_total_used()
    available = await repo.get_available_capacity()

    text = (
        "📊 <b>Статистика API Applications</b>\n\n"
        f"<b>Всего приложений:</b> {len(apps)}\n"
        f"<b>Активных:</b> {sum(1 for a in apps if a.is_active)}\n\n"
        f"<b>Общая вместимость:</b> {total_capacity}\n"
        f"<b>Занято:</b> {total_used}\n"
        f"<b>Свободно:</b> {available}\n"
        f"<b>Загрузка:</b> {(total_used / total_capacity * 100) if total_capacity > 0 else 0:.1f}%\n\n"
        "<b>По приложениям:</b>\n"
    )

    for app in apps:
        status = "🟢" if app.is_active else "🔴"
        usage_pct = (app.current_account_count / app.max_accounts * 100) if app.max_accounts > 0 else 0
        text += f"{status} {app.name}: {app.current_account_count}/{app.max_accounts} ({usage_pct:.0f}%)\n"

    await callback.message.edit_text(
        text,
        reply_markup=get_telegram_apps_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "apps:add")
async def add_app_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start adding new Telegram App."""
    await state.set_state(TelegramAppStates.waiting_api_id)

    await callback.message.edit_text(
        "➕ <b>Добавление API Application</b>\n\n"
        "Создайте приложение на <a href='https://my.telegram.org/apps'>my.telegram.org/apps</a>\n\n"
        "Введите <b>API ID</b> (число):",
    )
    await callback.message.answer(
        "Ожидаю API ID...",
        reply_markup=get_cancel_kb(),
    )
    await callback.answer()


@router.message(TelegramAppStates.waiting_api_id)
async def receive_api_id(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Receive API ID."""
    try:
        api_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ API ID должен быть числом. Попробуйте снова:")
        return

    # Check if already exists
    repo = PostgresTelegramAppRepository(session)
    existing = await repo.get_by_api_id(api_id)
    if existing:
        await message.answer(
            f"❌ Приложение с API ID {api_id} уже существует: {existing.name}",
        )
        return

    await state.update_data(api_id=api_id)
    await state.set_state(TelegramAppStates.waiting_api_hash)

    await message.answer(
        f"✅ API ID: <code>{api_id}</code>\n\n"
        "Теперь введите <b>API Hash</b>:",
    )


@router.message(TelegramAppStates.waiting_api_hash)
async def receive_api_hash(message: Message, state: FSMContext) -> None:
    """Receive API Hash."""
    api_hash = message.text.strip()

    if len(api_hash) < 20:
        await message.answer("❌ API Hash слишком короткий. Попробуйте снова:")
        return

    await state.update_data(api_hash=api_hash)
    await state.set_state(TelegramAppStates.waiting_name)

    await message.answer(
        "✅ API Hash сохранён.\n\n"
        "Введите <b>название</b> для этого приложения\n"
        "(например: App1, MainApp, Reserved):",
    )


@router.message(TelegramAppStates.waiting_name)
async def receive_name(message: Message, state: FSMContext) -> None:
    """Receive app name."""
    name = message.text.strip()

    if len(name) < 2:
        await message.answer("❌ Название слишком короткое. Попробуйте снова:")
        return

    await state.update_data(name=name)
    await state.set_state(TelegramAppStates.waiting_max_accounts)

    await message.answer(
        f"✅ Название: {name}\n\n"
        "Введите <b>максимальное количество аккаунтов</b>\n"
        "(рекомендуется 20-30):",
    )


@router.message(TelegramAppStates.waiting_max_accounts)
async def receive_max_accounts(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Receive max accounts and save app."""
    try:
        max_accounts = int(message.text.strip())
        if max_accounts < 1 or max_accounts > 100:
            raise ValueError("Out of range")
    except ValueError:
        await message.answer("❌ Введите число от 1 до 100:")
        return

    data = await state.get_data()
    await state.clear()

    # Create and save
    app = TelegramApp(
        api_id=data["api_id"],
        api_hash=data["api_hash"],
        name=data["name"],
        max_accounts=max_accounts,
    )

    repo = PostgresTelegramAppRepository(session)
    await repo.save(app)

    await message.answer(
        f"✅ <b>API Application создано!</b>\n\n"
        f"<b>Название:</b> {app.name}\n"
        f"<b>API ID:</b> <code>{app.api_id}</code>\n"
        f"<b>Лимит:</b> {app.max_accounts} аккаунтов\n\n"
        f"Приложение готово к использованию.",
        reply_markup=get_main_menu_kb(),
    )


@router.callback_query(F.data.startswith("app:view:"))
async def view_app(callback: CallbackQuery, session: AsyncSession) -> None:
    """View Telegram App details."""
    app_id = UUID(callback.data.split(":")[2])

    repo = PostgresTelegramAppRepository(session)
    app = await repo.get_by_id(app_id)

    if not app:
        await callback.answer("Приложение не найдено", show_alert=True)
        return

    status = "🟢 Активно" if app.is_active else "🔴 Неактивно"
    usage_pct = (app.current_account_count / app.max_accounts * 100) if app.max_accounts > 0 else 0

    text = (
        f"📱 <b>{app.name}</b>\n\n"
        f"<b>Статус:</b> {status}\n"
        f"<b>API ID:</b> <code>{app.api_id}</code>\n"
        f"<b>API Hash:</b> <code>{app.api_hash[:8]}...{app.api_hash[-4:]}</code>\n\n"
        f"<b>Аккаунтов:</b> {app.current_account_count}/{app.max_accounts} ({usage_pct:.0f}%)\n"
        f"<b>Свободно:</b> {app.available_slots}\n\n"
        f"<b>Создано:</b> {app.created_at.strftime('%d.%m.%Y %H:%M')}\n"
    )

    if app.notes:
        text += f"\n<b>Заметки:</b> {app.notes}"

    await callback.message.edit_text(
        text,
        reply_markup=get_telegram_app_actions_kb(app.id, app.is_active),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("app:activate:"))
async def activate_app(callback: CallbackQuery, session: AsyncSession) -> None:
    """Activate Telegram App."""
    app_id = UUID(callback.data.split(":")[2])

    repo = PostgresTelegramAppRepository(session)
    app = await repo.get_by_id(app_id)

    if not app:
        await callback.answer("Приложение не найдено", show_alert=True)
        return

    app.activate()
    await repo.save(app)

    await callback.answer("✅ Приложение активировано")

    # Refresh view
    await view_app(callback, session)


@router.callback_query(F.data.startswith("app:deactivate:"))
async def deactivate_app(callback: CallbackQuery, session: AsyncSession) -> None:
    """Deactivate Telegram App."""
    app_id = UUID(callback.data.split(":")[2])

    repo = PostgresTelegramAppRepository(session)
    app = await repo.get_by_id(app_id)

    if not app:
        await callback.answer("Приложение не найдено", show_alert=True)
        return

    app.deactivate()
    await repo.save(app)

    await callback.answer("⏸ Приложение деактивировано")

    # Refresh view
    await view_app(callback, session)


@router.callback_query(F.data.startswith("app:recalculate:"))
async def recalculate_app(callback: CallbackQuery, session: AsyncSession) -> None:
    """Recalculate account count for app."""
    app_id = UUID(callback.data.split(":")[2])

    repo = PostgresTelegramAppRepository(session)
    actual_count = await repo.recalculate_account_count(app_id)

    await callback.answer(f"✅ Пересчитано: {actual_count} аккаунтов")

    # Refresh view
    await view_app(callback, session)


@router.callback_query(F.data == "apps:recalculate")
async def recalculate_all_apps(callback: CallbackQuery, session: AsyncSession) -> None:
    """Recalculate account counts for all apps."""
    repo = PostgresTelegramAppRepository(session)
    counts = await repo.recalculate_all_counts()

    total = sum(counts.values())
    await callback.answer(f"✅ Пересчитано: {total} аккаунтов в {len(counts)} приложениях")

    # Refresh list
    await apps_list(callback, session)


@router.callback_query(F.data.startswith("app:edit_name:"))
async def edit_app_name_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing app name."""
    app_id = callback.data.split(":")[2]
    await state.update_data(editing_app_id=app_id)
    await state.set_state(TelegramAppStates.waiting_edit_name)

    await callback.message.edit_text(
        "✏️ Введите новое название для приложения:",
    )
    await callback.message.answer(
        "Ожидаю название...",
        reply_markup=get_cancel_kb(),
    )
    await callback.answer()


@router.message(TelegramAppStates.waiting_edit_name)
async def receive_edit_name(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Receive new app name."""
    name = message.text.strip()

    if len(name) < 2:
        await message.answer("❌ Название слишком короткое. Попробуйте снова:")
        return

    data = await state.get_data()
    app_id = UUID(data["editing_app_id"])
    await state.clear()

    repo = PostgresTelegramAppRepository(session)
    app = await repo.get_by_id(app_id)

    if not app:
        await message.answer("❌ Приложение не найдено", reply_markup=get_main_menu_kb())
        return

    app.name = name
    app.touch()
    await repo.save(app)

    await message.answer(
        f"✅ Название изменено на: {name}",
        reply_markup=get_main_menu_kb(),
    )


@router.callback_query(F.data.startswith("app:edit_limit:"))
async def edit_app_limit_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing app max accounts limit."""
    app_id = callback.data.split(":")[2]
    await state.update_data(editing_app_id=app_id)
    await state.set_state(TelegramAppStates.waiting_edit_max_accounts)

    await callback.message.edit_text(
        "📊 Введите новый лимит аккаунтов (1-100):",
    )
    await callback.message.answer(
        "Ожидаю число...",
        reply_markup=get_cancel_kb(),
    )
    await callback.answer()


@router.message(TelegramAppStates.waiting_edit_max_accounts)
async def receive_edit_max_accounts(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Receive new max accounts limit."""
    try:
        max_accounts = int(message.text.strip())
        if max_accounts < 1 or max_accounts > 100:
            raise ValueError("Out of range")
    except ValueError:
        await message.answer("❌ Введите число от 1 до 100:")
        return

    data = await state.get_data()
    app_id = UUID(data["editing_app_id"])
    await state.clear()

    repo = PostgresTelegramAppRepository(session)
    app = await repo.get_by_id(app_id)

    if not app:
        await message.answer("❌ Приложение не найдено", reply_markup=get_main_menu_kb())
        return

    app.max_accounts = max_accounts
    app.touch()
    await repo.save(app)

    await message.answer(
        f"✅ Лимит изменён на: {max_accounts}",
        reply_markup=get_main_menu_kb(),
    )


@router.callback_query(F.data.startswith("app:delete:"))
async def delete_app_confirm(callback: CallbackQuery) -> None:
    """Confirm app deletion."""
    app_id = callback.data.split(":")[2]

    await callback.message.edit_text(
        "⚠️ <b>Удаление приложения</b>\n\n"
        "Вы уверены? Аккаунты, привязанные к этому приложению, "
        "будут отвязаны (telegram_app_id станет NULL).",
        reply_markup=get_confirm_kb(
            confirm_callback=f"app:delete_confirmed:{app_id}",
            cancel_callback="apps:list",
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("app:delete_confirmed:"))
async def delete_app(callback: CallbackQuery, session: AsyncSession) -> None:
    """Delete Telegram App."""
    app_id = UUID(callback.data.split(":")[2])

    repo = PostgresTelegramAppRepository(session)
    app = await repo.get_by_id(app_id)

    if not app:
        await callback.answer("Приложение не найдено", show_alert=True)
        return

    await repo.delete(app_id)

    await callback.answer("✅ Приложение удалено")
    await apps_list(callback, session)
