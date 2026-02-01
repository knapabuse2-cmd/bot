"""
Account management handlers.
"""
import logging

from uuid import UUID

logger = logging.getLogger(__name__)

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services import AccountService
from src.infrastructure.database.repositories import (
    PostgresAccountRepository,
    PostgresProxyRepository,
    PostgresTelegramAppRepository,
)
from src.domain.entities import AccountSource, AccountStatus, TelegramApp
from src.infrastructure.database.models import AccountModel
from src.infrastructure.telegram.device_fingerprint import generate_random_fingerprint

from ..keyboards import (
    get_accounts_menu_kb,
    get_accounts_list_kb,
    get_account_actions_kb,
    get_account_add_method_kb,
    get_cancel_kb,
    get_main_menu_kb,
    get_confirm_kb,
    get_back_kb,
)
from ..states import AccountStates

router = Router(name="accounts")


def get_account_service(session: AsyncSession) -> AccountService:
    """Create account service with repositories."""
    return AccountService(
        account_repo=PostgresAccountRepository(session),
        proxy_repo=PostgresProxyRepository(session),
    )


# =============================================================================
# Menu and List
# =============================================================================

async def _get_account_counts(session: AsyncSession) -> tuple[dict, int]:
    """Get account counts by status and total."""
    repo = PostgresAccountRepository(session)
    all_counts = await repo.count_all_by_status()
    counts = {
        "active_count": all_counts.get("active", 0),
        "error_count": all_counts.get("error", 0),
        "paused_count": all_counts.get("paused", 0),
        "banned_count": all_counts.get("banned", 0),
    }
    total = sum(all_counts.values())
    return counts, total


@router.message(F.text == "📱 Аккаунты")
async def accounts_menu(message: Message, session: AsyncSession) -> None:
    """Show accounts menu."""
    counts, total = await _get_account_counts(session)

    await message.answer(
        f"📱 <b>Аккаунты</b> ({total})\n\n"
        "Выберите действие:",
        reply_markup=get_accounts_menu_kb(**counts),
    )


@router.callback_query(F.data == "accounts:menu")
async def accounts_menu_callback(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show accounts menu via callback."""
    counts, total = await _get_account_counts(session)

    await callback.message.edit_text(
        f"📱 <b>Аккаунты</b> ({total})\n\n"
        "Выберите действие:",
        reply_markup=get_accounts_menu_kb(**counts),
    )
    await callback.answer()


@router.callback_query(F.data == "accounts:list")
async def accounts_list(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show list of all accounts."""
    repo = PostgresAccountRepository(session)
    accounts = await repo.list_all(limit=100)
    
    if not accounts:
        await callback.message.edit_text(
            "📱 <b>Аккаунты</b>\n\n"
            "Список пуст. Добавьте первый аккаунт.",
            reply_markup=get_accounts_menu_kb(),
        )
        await callback.answer()
        return
    
    await callback.message.edit_text(
        f"📱 <b>Аккаунты</b> ({len(accounts)})\n\n"
        "🟢 Активен | 🔵 Готов | 🟡 Пауза | 🔴 Ошибка | ⛔ Бан",
        reply_markup=get_accounts_list_kb(accounts, page=0),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("accounts:page:"))
async def accounts_page(callback: CallbackQuery, session: AsyncSession) -> None:
    """Handle accounts pagination."""
    page = int(callback.data.split(":")[-1])
    
    repo = PostgresAccountRepository(session)
    accounts = await repo.list_all(limit=100)
    
    await callback.message.edit_reply_markup(
        reply_markup=get_accounts_list_kb(accounts, page=page),
    )
    await callback.answer()


@router.callback_query(F.data == "accounts:search")
async def accounts_search_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start account search."""
    await state.set_state(AccountStates.waiting_search_query)
    await callback.message.edit_text(
        "🔍 <b>Поиск аккаунта</b>\n\n"
        "Введите номер телефона, username или имя для поиска:",
        reply_markup=get_back_kb("accounts:menu"),
    )
    await callback.answer()


@router.message(AccountStates.waiting_search_query)
async def accounts_search_query(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Process search query."""
    query = message.text.strip().lower()
    await state.clear()

    repo = PostgresAccountRepository(session)
    all_accounts = await repo.list_all(limit=200)

    # Filter accounts by query
    results = []
    for acc in all_accounts:
        if (query in (acc.phone or "").lower() or
            query in (acc.username or "").lower() or
            query in (acc.first_name or "").lower() or
            query in (acc.last_name or "").lower()):
            results.append(acc)

    if not results:
        await message.answer(
            f"🔍 По запросу <b>{message.text}</b> ничего не найдено.",
            reply_markup=get_back_kb("accounts:menu"),
        )
        return

    await message.answer(
        f"🔍 Найдено: <b>{len(results)}</b> аккаунтов",
        reply_markup=get_accounts_list_kb(results, page=0),
    )


@router.callback_query(F.data == "accounts:active")
async def accounts_active(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show active accounts."""
    repo = PostgresAccountRepository(session)
    accounts = await repo.list_by_status(AccountStatus.ACTIVE)
    
    if not accounts:
        await callback.answer("Нет активных аккаунтов", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"🟢 <b>Активные аккаунты</b> ({len(accounts)})",
        reply_markup=get_accounts_list_kb(accounts, page=0),
    )
    await callback.answer()


@router.callback_query(F.data == "accounts:paused")
async def accounts_paused(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show paused accounts."""
    repo = PostgresAccountRepository(session)
    accounts = await repo.list_by_status(AccountStatus.PAUSED)
    
    if not accounts:
        await callback.answer("Нет аккаунтов на паузе", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"🟡 <b>Аккаунты на паузе</b> ({len(accounts)})",
        reply_markup=get_accounts_list_kb(accounts, page=0),
    )
    await callback.answer()


@router.callback_query(F.data == "accounts:errors")
async def accounts_errors(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show accounts with errors."""
    repo = PostgresAccountRepository(session)
    accounts = await repo.list_by_status(AccountStatus.ERROR)

    if not accounts:
        await callback.answer("Нет аккаунтов с ошибками", show_alert=True)
        return

    # Get base keyboard and add delete all button
    kb = get_accounts_list_kb(accounts, page=0)
    buttons = list(kb.inline_keyboard)
    buttons.append([InlineKeyboardButton(
        text=f"🗑 Удалить все ({len(accounts)})",
        callback_data="accounts:delete_all_errors",
    )])
    new_kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(
        f"🔴 <b>Аккаунты с ошибками</b> ({len(accounts)})",
        reply_markup=new_kb,
    )
    await callback.answer()


@router.callback_query(F.data == "accounts:delete_all_errors")
async def delete_all_errors_confirm(callback: CallbackQuery) -> None:
    """Confirm deletion of all accounts with errors."""
    await callback.message.edit_text(
        "⚠️ <b>Удаление всех аккаунтов с ошибками</b>\n\n"
        "Вы уверены? Это действие необратимо.\n"
        "Все аккаунты с ошибками и их диалоги будут удалены.",
        reply_markup=get_confirm_kb(
            confirm_callback="accounts:delete_all_errors:confirm",
            cancel_callback="accounts:errors",
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "accounts:delete_all_errors:confirm")
async def delete_all_errors(callback: CallbackQuery, session: AsyncSession) -> None:
    """Delete all accounts with errors."""
    from sqlalchemy import delete as sql_delete

    # Get count first
    repo = PostgresAccountRepository(session)
    accounts = await repo.list_by_status(AccountStatus.ERROR)
    count = len(accounts)

    if count == 0:
        await callback.answer("Нет аккаунтов для удаления", show_alert=True)
        return

    # Delete all error accounts
    stmt = sql_delete(AccountModel).where(AccountModel.status == AccountStatus.ERROR)
    await session.execute(stmt)
    await session.commit()

    await callback.message.edit_text(
        f"✅ Удалено {count} аккаунтов с ошибками.",
        reply_markup=get_accounts_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "accounts:banned")
async def accounts_banned(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show banned accounts."""
    repo = PostgresAccountRepository(session)
    accounts = await repo.list_by_status(AccountStatus.BANNED)

    if not accounts:
        await callback.answer("Нет забаненных аккаунтов", show_alert=True)
        return

    await callback.message.edit_text(
        f"⛔ <b>Забаненные аккаунты</b> ({len(accounts)})",
        reply_markup=get_accounts_list_kb(accounts, page=0),
    )
    await callback.answer()


# =============================================================================
# Check All Accounts Status
# =============================================================================

@router.callback_query(F.data == "accounts:check_all")
async def check_all_accounts(callback: CallbackQuery, session: AsyncSession) -> None:
    """Check status of all accounts (frozen/banned detection)."""
    import asyncio
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import (
        AuthKeyDuplicatedError,
        UserDeactivatedBanError,
        UserDeactivatedError,
        SessionRevokedError,
        AuthKeyUnregisteredError,
    )
    from src.config import get_settings
    from src.infrastructure.database.repositories import PostgresProxyRepository
    from src.utils.crypto import get_session_encryption
    import python_socks

    repo = PostgresAccountRepository(session)
    accounts = await repo.list_all(limit=500)

    if not accounts:
        await callback.answer("Нет аккаунтов для проверки", show_alert=True)
        return

    await callback.answer()

    status_msg = await callback.message.edit_text(
        f"🔍 <b>Проверка статуса аккаунтов</b>\n\n"
        f"Всего аккаунтов: {len(accounts)}\n"
        f"Проверено: 0/{len(accounts)}..."
    )

    proxy_repo = PostgresProxyRepository(session)
    settings = get_settings()
    encryption = get_session_encryption()

    results = {
        "active": 0,
        "banned": 0,
        "frozen": 0,
        "session_dead": 0,
        "no_proxy": 0,
        "error": 0,
    }

    banned_accounts = []
    frozen_accounts = []
    dead_accounts = []

    async def check_single_account(account):
        """Check a single account status."""
        # Skip if no session
        if not account.session_data:
            return "error", "Нет сессии"

        # Skip if no proxy
        if not account.proxy_id:
            return "no_proxy", "Нет прокси"

        # Get proxy
        proxy = await proxy_repo.get_by_id(account.proxy_id)
        if not proxy:
            return "no_proxy", "Прокси не найден"

        client = None
        try:
            # Decrypt session
            decrypted = encryption.decrypt(account.session_data)
            try:
                session_string = decrypted.decode('utf-8')
            except UnicodeDecodeError:
                return "error", "Ошибка расшифровки"

            # Build proxy config
            proxy_dict = {
                'proxy_type': python_socks.ProxyType.SOCKS5,
                'addr': proxy.host,
                'port': proxy.port,
                'username': proxy.username,
                'password': proxy.password,
                'rdns': True,
            }

            # Generate fingerprint
            from src.infrastructure.telegram.device_fingerprint import generate_fingerprint_for_account
            fingerprint = generate_fingerprint_for_account(str(account.id), lang_code="ru")

            client = TelegramClient(
                StringSession(session_string),
                settings.telegram.api_id,
                settings.telegram.api_hash.get_secret_value(),
                proxy=proxy_dict,
                device_model=fingerprint.device_model,
                system_version=fingerprint.system_version,
                app_version=fingerprint.app_version,
                lang_code=fingerprint.lang_code,
                system_lang_code=fingerprint.system_lang_code,
            )

            # Connect with timeout
            await asyncio.wait_for(client.connect(), timeout=30)

            # Check authorization
            if not await client.is_user_authorized():
                return "session_dead", "Сессия невалидна"

            # Try to get user info
            me = await client.get_me()
            if me:
                return "active", None

            return "error", "Не удалось получить данные"

        except (UserDeactivatedBanError, UserDeactivatedError):
            return "banned", "Аккаунт заблокирован"

        except (SessionRevokedError, AuthKeyUnregisteredError):
            return "frozen", "Сессия отозвана/заморожена"

        except AuthKeyDuplicatedError:
            return "session_dead", "Сессия занята с другого IP"

        except asyncio.TimeoutError:
            return "error", "Таймаут подключения"

        except Exception as e:
            error_str = str(e).lower()
            if "banned" in error_str or "deactivated" in error_str:
                return "banned", str(e)[:100]
            elif "revoked" in error_str or "unregistered" in error_str:
                return "frozen", str(e)[:100]
            return "error", str(e)[:100]

        finally:
            if client:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    checked = 0
    batch_size = 5  # Check 5 accounts at a time

    for i in range(0, len(accounts), batch_size):
        batch = accounts[i:i + batch_size]
        tasks = [check_single_account(acc) for acc in batch]
        batch_results = await asyncio.gather(*tasks)

        for j, (status, error_msg) in enumerate(batch_results):
            acc = batch[j]
            results[status] += 1
            checked += 1

            # Update account status in DB
            if status == "banned":
                acc.status = AccountStatus.BANNED
                acc.error_message = error_msg
                banned_accounts.append(acc)
                await repo.save(acc)
            elif status == "frozen":
                acc.status = AccountStatus.BANNED
                acc.error_message = f"Заморожен: {error_msg}"
                frozen_accounts.append(acc)
                await repo.save(acc)
            elif status == "session_dead":
                acc.status = AccountStatus.ERROR
                acc.error_message = error_msg
                dead_accounts.append(acc)
                await repo.save(acc)
            elif status == "active" and acc.status == AccountStatus.ERROR:
                # Clear error if account is actually working
                acc.status = AccountStatus.READY
                acc.error_message = None
                await repo.save(acc)

        # Update progress message
        try:
            await status_msg.edit_text(
                f"🔍 <b>Проверка статуса аккаунтов</b>\n\n"
                f"Проверено: {checked}/{len(accounts)}\n\n"
                f"🟢 Активных: {results['active']}\n"
                f"⛔ Забаненных: {results['banned']}\n"
                f"🧊 Замороженных: {results['frozen']}\n"
                f"💀 Мёртвых сессий: {results['session_dead']}\n"
                f"🚫 Без прокси: {results['no_proxy']}\n"
                f"❌ Ошибок: {results['error']}"
            )
        except Exception:
            pass

    # Build final keyboard
    kb = InlineKeyboardBuilder()
    if banned_accounts or frozen_accounts:
        kb.row(InlineKeyboardButton(
            text=f"⛔ Забаненные ({len(banned_accounts) + len(frozen_accounts)})",
            callback_data="accounts:banned",
        ))
    if dead_accounts:
        kb.row(InlineKeyboardButton(
            text=f"💀 Мёртвые сессии ({len(dead_accounts)})",
            callback_data="accounts:errors",
        ))
    kb.row(InlineKeyboardButton(
        text="◀️ Меню аккаунтов",
        callback_data="accounts:menu",
    ))

    # Final message with details
    details = ""
    if banned_accounts:
        details += "\n\n<b>⛔ Забаненные:</b>\n"
        for acc in banned_accounts[:10]:
            details += f"• {acc.phone} (@{acc.username or '—'})\n"
        if len(banned_accounts) > 10:
            details += f"...и ещё {len(banned_accounts) - 10}\n"

    if frozen_accounts:
        details += "\n\n<b>🧊 Замороженные:</b>\n"
        for acc in frozen_accounts[:10]:
            details += f"• {acc.phone} (@{acc.username or '—'})\n"
        if len(frozen_accounts) > 10:
            details += f"...и ещё {len(frozen_accounts) - 10}\n"

    await status_msg.edit_text(
        f"✅ <b>Проверка завершена</b>\n\n"
        f"Всего проверено: {len(accounts)}\n\n"
        f"🟢 Активных: {results['active']}\n"
        f"⛔ Забаненных: {results['banned']}\n"
        f"🧊 Замороженных: {results['frozen']}\n"
        f"💀 Мёртвых сессий: {results['session_dead']}\n"
        f"🚫 Без прокси: {results['no_proxy']}\n"
        f"❌ Ошибок: {results['error']}"
        f"{details}",
        reply_markup=kb.as_markup(),
    )


# =============================================================================
# View Account
# =============================================================================

@router.callback_query(F.data.startswith("account:view:"))
async def view_account(callback: CallbackQuery, session: AsyncSession) -> None:
    """View account details."""
    account_id = UUID(callback.data.split(":")[-1])
    
    service = get_account_service(session)
    
    try:
        account = await service.get_account(account_id)
    except Exception:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return
    
    status_text = {
        AccountStatus.INACTIVE: "⚪ Неактивен",
        AccountStatus.READY: "🔵 Готов к работе",
        AccountStatus.ACTIVE: "🟢 Активен",
        AccountStatus.PAUSED: "🟡 На паузе",
        AccountStatus.ERROR: "🔴 Ошибка",
        AccountStatus.BANNED: "⛔ Забанен",
        AccountStatus.COOLDOWN: "⏳ Кулдаун",
    }.get(account.status, "❓ Неизвестно")

    source_text = {
        AccountSource.PHONE: "📱 Авторизован по номеру",
        AccountSource.JSON_SESSION: "📁 JSON+Session",
        AccountSource.TDATA: "💾 TData",
    }.get(account.source, "❓ Неизвестно")

    text = (
        f"📱 <b>Аккаунт</b>\n\n"
        f"<b>Телефон:</b> {account.phone}\n"
        f"<b>Username:</b> @{account.username or '—'}\n"
        f"<b>Имя:</b> {account.first_name} {account.last_name}\n"
        f"<b>Telegram ID:</b> {account.telegram_id or '—'}\n\n"
        f"<b>Источник:</b> {source_text}\n"
        f"<b>Статус:</b> {status_text}\n"
    )

    # Check for specific error types
    is_session_dead = False
    if account.error_message:
        error_lower = account.error_message.lower()
        if "authkeyduplicat" in error_lower or "two different ip" in error_lower:
            is_session_dead = True
            text += (
                f"\n⚠️ <b>СЕССИЯ НЕВАЛИДНА</b>\n"
                f"Сессия использовалась с двух IP и заблокирована Telegram.\n"
                f"<b>Решение:</b> Удалите аккаунт и добавьте заново по номеру.\n"
            )
        elif "banned" in error_lower or "deactivated" in error_lower:
            text += f"\n⛔ <b>Аккаунт заблокирован Telegram</b>\n"
        else:
            text += f"<b>Ошибка:</b> {account.error_message[:150]}\n"
    
    text += (
        f"\n<b>Лимиты:</b>\n"
        f"• Сообщений/час: {account.hourly_messages_count}/{account.limits.max_messages_per_hour}\n"
        f"• Диалогов/день: {account.daily_conversations_count}/{account.limits.max_new_conversations_per_day}\n"
    )

    if account.last_activity:
        text += f"\n<b>Последняя активность:</b> {account.last_activity.strftime('%d.%m.%Y %H:%M')}"

    await callback.message.edit_text(
        text,
        reply_markup=get_account_actions_kb(
            account.id,
            account.status.value,
            is_session_dead,
            source=account.source.value if hasattr(account.source, 'value') else str(account.source),
        ),
    )
    await callback.answer()


# =============================================================================
# Account Actions
# =============================================================================

@router.callback_query(F.data.startswith("account:activate:"))
async def activate_account(callback: CallbackQuery, session: AsyncSession) -> None:
    """Activate an account."""
    account_id = UUID(callback.data.split(":")[-1])
    service = get_account_service(session)

    # Answer immediately to avoid timeout
    await callback.answer("⏳ Активирую...", show_alert=False)

    try:
        account = await service.activate_account(account_id)

        # Refresh view
        await view_account(callback, session)

    except Exception as e:
        await callback.message.answer(f"❌ Ошибка активации: {e}")


@router.callback_query(F.data.startswith("account:pause:"))
async def pause_account(callback: CallbackQuery, session: AsyncSession) -> None:
    """Pause an account."""
    account_id = UUID(callback.data.split(":")[-1])
    service = get_account_service(session)

    try:
        account = await service.pause_account(account_id)
        await callback.answer("⏸ Аккаунт на паузе", show_alert=True)

        # Refresh view
        await view_account(callback, session)

    except Exception as e:
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)


@router.callback_query(F.data.startswith("account:reconnect:"))
async def reconnect_account(callback: CallbackQuery, session: AsyncSession) -> None:
    """Try to reconnect an account that has errors."""
    import asyncio
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import AuthKeyDuplicatedError
    from src.config import get_settings
    from src.infrastructure.database.repositories import PostgresProxyRepository
    from src.utils.crypto import get_session_encryption
    import python_socks

    account_id = UUID(callback.data.split(":")[-1])

    await callback.answer("⏳ Проверяю подключение...", show_alert=False)

    repo = PostgresAccountRepository(session)
    account = await repo.get_by_id(account_id)

    if not account:
        await callback.answer("❌ Аккаунт не найден", show_alert=True)
        return

    # Check if has proxy
    if not account.proxy_id:
        await callback.message.answer(
            "❌ У аккаунта не назначен прокси.\n"
            "Сначала назначьте прокси, затем попробуйте переподключиться."
        )
        return

    # Get proxy
    proxy_repo = PostgresProxyRepository(session)
    proxy = await proxy_repo.get_by_id(account.proxy_id)

    if not proxy:
        await callback.message.answer(
            "❌ Прокси не найден.\n"
            "Назначьте другой прокси и попробуйте снова."
        )
        return

    status_msg = await callback.message.answer("⏳ Останавливаю старый воркер...")

    # First, try to stop any running worker for this account
    try:
        from src.workers.manager import get_worker_manager
        manager = get_worker_manager()
        if manager:
            stopped = await manager.stop_worker(account_id)
            if stopped:
                # Wait a bit for Telegram to release the session
                await status_msg.edit_text("⏳ Ожидаю освобождения сессии...")
                await asyncio.sleep(3)
    except Exception as e:
        # Manager might not be running, that's okay
        pass

    await status_msg.edit_text("⏳ Подключаюсь к Telegram...")

    client = None
    try:
        # Decrypt session
        encryption = get_session_encryption()
        decrypted = encryption.decrypt(account.session_data)

        # Try to decode as string (StringSession)
        try:
            session_string = decrypted.decode('utf-8')
        except UnicodeDecodeError:
            await status_msg.edit_text(
                "❌ Не удалось расшифровать сессию.\n"
                "Возможно, сессия повреждена."
            )
            return

        settings = get_settings()

        # Build proxy config
        proxy_dict = {
            'proxy_type': python_socks.ProxyType.SOCKS5,
            'addr': proxy.host,
            'port': proxy.port,
            'username': proxy.username,
            'password': proxy.password,
            'rdns': True,
        }

        # Generate deterministic fingerprint for this account
        from src.infrastructure.telegram.device_fingerprint import generate_fingerprint_for_account
        fingerprint = generate_fingerprint_for_account(str(account.id), lang_code="ru")

        await status_msg.edit_text(
            f"⏳ Подключаюсь через {proxy.host}:{proxy.port}...\n"
            f"📱 Device: {fingerprint.device_model}"
        )

        client = TelegramClient(
            StringSession(session_string),
            settings.telegram.api_id,
            settings.telegram.api_hash.get_secret_value(),
            proxy=proxy_dict,
            device_model=fingerprint.device_model,
            system_version=fingerprint.system_version,
            app_version=fingerprint.app_version,
            lang_code=fingerprint.lang_code,
            system_lang_code=fingerprint.system_lang_code,
        )

        await client.connect()

        # Check authorization
        if not await client.is_user_authorized():
            await status_msg.edit_text(
                "❌ Сессия невалидна.\n"
                "Аккаунт требует повторной авторизации.\n\n"
                "Удалите аккаунт и добавьте заново."
            )
            return

        # Get user info to verify
        me = await client.get_me()

        # Success! Clear error and set to ready
        account.status = AccountStatus.READY
        account.error_message = None
        await repo.save(account)

        await status_msg.edit_text(
            f"✅ <b>Подключение успешно!</b>\n\n"
            f"👤 {me.first_name} {me.last_name or ''}\n"
            f"📱 {account.phone}\n"
            f"🆔 @{me.username or '—'}\n\n"
            f"Статус изменён на: 🔵 Готов к работе",
            parse_mode="HTML",
        )

        # Refresh account view
        await view_account(callback, session)

    except AuthKeyDuplicatedError:
        await status_msg.edit_text(
            "❌ <b>Сессия занята</b>\n\n"
            "Эта сессия уже используется другим соединением.\n\n"
            "Telegram не позволяет подключаться с двух IP одновременно.\n\n"
            "<b>Решение:</b>\n"
            "• Подождите 1-2 минуты и попробуйте снова\n"
            "• Убедитесь что бот/воркер остановлен\n"
            "• Если проблема сохраняется - сессия используется где-то ещё",
            parse_mode="HTML",
        )

    except Exception as e:
        error_msg = str(e)[:200]
        await status_msg.edit_text(
            f"❌ <b>Ошибка подключения</b>\n\n"
            f"<code>{error_msg}</code>\n\n"
            f"Попробуйте:\n"
            f"• Сменить прокси\n"
            f"• Подождать 1-2 минуты и повторить\n"
            f"• Удалить и добавить аккаунт заново",
            parse_mode="HTML",
        )

    finally:
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass


# =============================================================================
# Get Login Code (listen for incoming Telegram code)
# =============================================================================

@router.callback_query(F.data.regexp(r"^account:getcode:[0-9a-f-]+$"))
async def get_login_code_start(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Start listening for incoming login code.

    When user requests a login code for this phone number from another device,
    Telegram sends the code as a message. This function connects to the account
    and waits for incoming messages from Telegram with the code.
    """
    import asyncio
    import datetime
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import AuthKeyDuplicatedError
    from telethon.tl.types import User
    from src.config import get_settings
    from src.infrastructure.database.repositories import PostgresProxyRepository
    from src.utils.crypto import get_session_encryption
    import python_socks

    account_id = UUID(callback.data.split(":")[-1])

    await callback.answer("⏳ Подключаюсь к аккаунту...", show_alert=False)

    repo = PostgresAccountRepository(session)
    account = await repo.get_by_id(account_id)

    if not account:
        await callback.answer("❌ Аккаунт не найден", show_alert=True)
        return

    # Check if has proxy
    if not account.proxy_id:
        await callback.message.answer(
            "❌ У аккаунта не назначен прокси.\n"
            "Сначала назначьте прокси."
        )
        return

    # Get proxy
    proxy_repo = PostgresProxyRepository(session)
    proxy = await proxy_repo.get_by_id(account.proxy_id)

    if not proxy:
        await callback.message.answer(
            "❌ Прокси не найден."
        )
        return

    # Build cancel keyboard
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="❌ Отменить ожидание",
        callback_data=f"account:getcode:cancel:{account_id}",
    ))

    status_msg = await callback.message.answer(
        f"📲 <b>Получение кода авторизации</b>\n\n"
        f"📱 Аккаунт: {account.phone}\n"
        f"🌐 Прокси: {proxy.host}:{proxy.port}\n\n"
        f"⏳ Подключаюсь...",
        reply_markup=kb.as_markup(),
    )

    client = None
    try:
        # Decrypt session
        encryption = get_session_encryption()
        decrypted = encryption.decrypt(account.session_data)

        try:
            session_string = decrypted.decode('utf-8')
        except UnicodeDecodeError:
            await status_msg.edit_text(
                "❌ Не удалось расшифровать сессию.",
                reply_markup=get_back_kb(f"account:view:{account_id}"),
            )
            return

        settings = get_settings()

        # Build proxy config
        proxy_dict = {
            'proxy_type': python_socks.ProxyType.SOCKS5,
            'addr': proxy.host,
            'port': proxy.port,
            'username': proxy.username,
            'password': proxy.password,
            'rdns': True,
        }

        # Generate deterministic fingerprint for this account
        from src.infrastructure.telegram.device_fingerprint import generate_fingerprint_for_account
        fingerprint = generate_fingerprint_for_account(str(account.id), lang_code="ru")

        client = TelegramClient(
            StringSession(session_string),
            settings.telegram.api_id,
            settings.telegram.api_hash.get_secret_value(),
            proxy=proxy_dict,
            device_model=fingerprint.device_model,
            system_version=fingerprint.system_version,
            app_version=fingerprint.app_version,
            lang_code=fingerprint.lang_code,
            system_lang_code=fingerprint.system_lang_code,
        )

        await client.connect()

        # Check authorization
        if not await client.is_user_authorized():
            await status_msg.edit_text(
                "❌ Сессия невалидна.\n"
                "Аккаунт требует повторной авторизации.",
                reply_markup=get_back_kb(f"account:view:{account_id}"),
            )
            return

        await status_msg.edit_text(
            f"📲 <b>Ожидаю код авторизации</b>\n\n"
            f"📱 Аккаунт: {account.phone}\n\n"
            f"<b>Инструкция:</b>\n"
            f"1️⃣ На другом устройстве откройте Telegram\n"
            f"2️⃣ Войдите по номеру <code>{account.phone}</code>\n"
            f"3️⃣ Telegram отправит код в этот аккаунт\n"
            f"4️⃣ Бот автоматически перехватит и покажет код\n\n"
            f"⏳ <b>Жду входящие сообщения...</b>\n"
            f"(таймаут: 2 минуты)",
            reply_markup=kb.as_markup(),
        )

        # Wait for incoming messages with the code
        # Telegram sends login codes from user_id 777000
        TELEGRAM_SERVICE_ID = 777000
        TIMEOUT_SECONDS = 120

        code_found = None
        start_time = asyncio.get_event_loop().time()

        # Get dialogs to find Telegram service chat
        async for dialog in client.iter_dialogs(limit=20):
            entity = dialog.entity
            if isinstance(entity, User) and entity.id == TELEGRAM_SERVICE_ID:
                # Found Telegram service chat, get recent messages
                async for msg in client.iter_messages(entity, limit=5):
                    # Check if message is recent (within last 2 minutes)
                    if msg.date:
                        now = datetime.datetime.now(datetime.timezone.utc)
                        age = (now - msg.date).total_seconds()
                        if age < 120:  # Message is fresh
                            # Try to extract code from message
                            code = _extract_login_code_from_message(msg)
                            if code:
                                code_found = code
                                break
                break

        # If no recent code found, wait for new messages by polling
        if not code_found:
            last_update = 0
            telegram_entity = None

            # Try to get Telegram service entity
            try:
                telegram_entity = await client.get_entity(TELEGRAM_SERVICE_ID)
            except Exception:
                pass  # Entity might not exist yet

            # Poll for new messages every 2 seconds
            while not code_found:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > TIMEOUT_SECONDS:
                    break

                # Update status every 10 seconds
                remaining = int(TIMEOUT_SECONDS - elapsed)
                if remaining != last_update and remaining % 10 == 0:
                    last_update = remaining
                    try:
                        await status_msg.edit_text(
                            f"📲 <b>Ожидаю код авторизации</b>\n\n"
                            f"📱 Аккаунт: {account.phone}\n\n"
                            f"<b>Инструкция:</b>\n"
                            f"1️⃣ На другом устройстве откройте Telegram\n"
                            f"2️⃣ Войдите по номеру <code>{account.phone}</code>\n"
                            f"3️⃣ Telegram отправит код в этот аккаунт\n"
                            f"4️⃣ Бот автоматически перехватит и покажет код\n\n"
                            f"⏳ <b>Жду входящие сообщения...</b>\n"
                            f"(осталось: {remaining} сек)",
                            reply_markup=kb.as_markup(),
                        )
                    except Exception:
                        pass

                # Force fetch updates from Telegram
                try:
                    await client.catch_up()
                except Exception:
                    pass

                # Check for new messages - scan dialogs
                try:
                    async for dialog in client.iter_dialogs(limit=15):
                        entity = dialog.entity
                        if isinstance(entity, User) and entity.id == TELEGRAM_SERVICE_ID:
                            telegram_entity = entity
                            async for msg in client.iter_messages(entity, limit=5):
                                if msg.date:
                                    age = (datetime.datetime.now(datetime.timezone.utc) - msg.date).total_seconds()
                                    if age < 180:  # Check within 3 minutes
                                        code = _extract_login_code_from_message(msg)
                                        if code:
                                            code_found = code
                                            break
                            break
                except Exception:
                    pass

                # Also try direct by ID
                if not code_found:
                    try:
                        async for msg in client.iter_messages(TELEGRAM_SERVICE_ID, limit=5):
                            if msg.date:
                                age = (datetime.datetime.now(datetime.timezone.utc) - msg.date).total_seconds()
                                if age < 180:
                                    code = _extract_login_code_from_message(msg)
                                    if code:
                                        code_found = code
                                        break
                    except Exception:
                        pass

                if not code_found:
                    await asyncio.sleep(2)

        if code_found:
            await status_msg.edit_text(
                f"✅ <b>Код получен!</b>\n\n"
                f"📱 Аккаунт: {account.phone}\n\n"
                f"🔐 <b>Код:</b> <code>{code_found}</code>\n\n"
                f"⚠️ Код действителен ~5 минут",
                reply_markup=get_back_kb(f"account:view:{account_id}"),
            )
        else:
            await status_msg.edit_text(
                f"⏰ <b>Таймаут</b>\n\n"
                f"За 2 минуты код не пришёл.\n\n"
                f"Возможные причины:\n"
                f"• Код ещё не был запрошен\n"
                f"• Код пришёл по SMS\n"
                f"• Код уже был использован",
                reply_markup=get_back_kb(f"account:view:{account_id}"),
            )

    except AuthKeyDuplicatedError:
        await status_msg.edit_text(
            "❌ <b>Сессия занята</b>\n\n"
            "Эта сессия уже используется другим соединением.\n"
            "Попробуйте позже.",
            reply_markup=get_back_kb(f"account:view:{account_id}"),
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        await status_msg.edit_text(
            f"❌ <b>Ошибка</b>\n\n"
            f"<code>{str(e)[:200]}</code>",
            reply_markup=get_back_kb(f"account:view:{account_id}"),
        )

    finally:
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass


def _extract_login_code_from_message(msg) -> str | None:
    """Extract login code from Telegram message, including spoilers."""
    import re
    from telethon.tl.types import MessageEntitySpoiler

    if not msg:
        return None

    text = msg.text or msg.raw_text or ""

    # First, try to extract code from spoiler entities
    if msg.entities:
        for entity in msg.entities:
            if isinstance(entity, MessageEntitySpoiler):
                # Extract spoiler text
                spoiler_text = text[entity.offset:entity.offset + entity.length]
                # Check if it's a code (5-6 digits)
                clean = spoiler_text.replace('-', '').replace(' ', '').strip()
                if clean.isdigit() and 5 <= len(clean) <= 6:
                    return clean

    # Fallback: search in full text
    return _extract_login_code(text)


def _extract_login_code(text: str) -> str | None:
    """Extract login code from text string."""
    import re

    if not text:
        return None

    # Telegram sends codes in various formats:
    # "Login code: 12345"
    # "Your login code is 12345"
    # "Code: 12345"
    # Just a number like "12345" or "123-456"
    # "Web login code: 12345"

    # Try to find code patterns
    patterns = [
        r'(?:login\s*code|код входа|код|code)[:\s]+(\d{5,6})',  # "login code: 12345"
        r'(\d{5,6})\s*[-–—]\s*(?:это|is)',  # "12345 - это ваш код"
        r'(\d{3}[-\s]?\d{3})',  # "123-456" or "123 456" format
        r'(?:^|\s)(\d{5,6})(?:\s|$|\.)',  # Just the number
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            code = match.group(1).replace('-', '').replace(' ', '')
            if 5 <= len(code) <= 6:
                return code

    return None


@router.callback_query(F.data.startswith("account:getcode:cancel:"))
async def get_login_code_cancel(callback: CallbackQuery) -> None:
    """Cancel waiting for login code."""
    parts = callback.data.split(":")
    account_id = parts[3] if len(parts) > 3 else None

    back_cb = f"account:view:{account_id}" if account_id else "accounts:menu"

    await callback.message.edit_text(
        "❌ Ожидание кода отменено.",
        reply_markup=get_back_kb(back_cb),
    )
    await callback.answer()


# =============================================================================
# Premium Purchase (with card payment)
# =============================================================================

@router.callback_query(F.data.regexp(r"^account:premium:[0-9a-f-]+$"))
async def premium_purchase_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show premium purchase options."""
    account_id = UUID(callback.data.split(":")[2])

    repo = PostgresAccountRepository(session)
    account = await repo.get_by_id(account_id)

    if not account:
        await callback.answer("❌ Аккаунт не найден", show_alert=True)
        return

    # Check if already premium
    if account.is_premium:
        await callback.message.edit_text(
            f"⭐ <b>Telegram Premium</b>\n\n"
            f"📱 {account.phone}\n"
            f"👤 @{account.username or '—'}\n\n"
            f"✅ Аккаунт уже имеет Premium!",
            parse_mode="HTML",
            reply_markup=get_back_kb(f"account:view:{account_id}"),
        )
        await callback.answer()
        return

    # Build keyboard
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(
            text="💳 Купить Premium",
            callback_data=f"account:premium:buy:{account_id}",
        ),
    )
    kb.row(
        InlineKeyboardButton(
            text="🔄 Проверить статус",
            callback_data=f"account:premium:check:{account_id}",
        ),
    )
    kb.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data=f"account:view:{account_id}"),
    )

    await callback.message.edit_text(
        f"⭐ <b>Telegram Premium</b>\n\n"
        f"📱 {account.phone}\n"
        f"👤 @{account.username or '—'}\n\n"
        f"Нажмите «Купить Premium» чтобы оплатить подписку картой.\n\n"
        f"<b>Как это работает:</b>\n"
        f"1. Бот получит счёт от @PremiumBot\n"
        f"2. Вы введёте данные карты\n"
        f"3. Пройдёте 3DS подтверждение\n"
        f"4. Premium активируется автоматически",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^account:premium:buy:[0-9a-f-]+$"))
async def premium_get_invoice(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Get invoice from PremiumBot and get payment URL."""
    from src.services.premium_service import get_premium_invoice_for_account, get_payment_url_for_account
    from src.infrastructure.database.repositories import PostgresProxyRepository

    account_id = UUID(callback.data.split(":")[3])

    repo = PostgresAccountRepository(session)
    account = await repo.get_by_id(account_id)

    if not account:
        await callback.answer("❌ Аккаунт не найден", show_alert=True)
        return

    await callback.answer("⏳ Получаю счёт от PremiumBot...", show_alert=False)

    status_msg = await callback.message.edit_text(
        f"⏳ <b>Получение счёта...</b>\n\n"
        f"📱 {account.phone}\n\n"
        f"Подключаюсь к @PremiumBot...",
        parse_mode="HTML",
    )

    # Get proxy config
    proxy_config = None
    if account.proxy_id:
        proxy_repo = PostgresProxyRepository(session)
        proxy = await proxy_repo.get_by_id(account.proxy_id)
        if proxy:
            proxy_config = {
                "host": proxy.host,
                "port": proxy.port,
                "username": proxy.username,
                "password": proxy.password,
            }

    # Get invoice
    result = await get_premium_invoice_for_account(
        account_id=account_id,
        session=session,
        proxy_config=proxy_config,
    )

    if not result.get("success"):
        error = result.get("error", "Unknown error")
        await status_msg.edit_text(
            f"❌ <b>Ошибка получения счёта</b>\n\n"
            f"<code>{error}</code>\n\n"
            f"Попробуйте позже.",
            parse_mode="HTML",
            reply_markup=get_back_kb(f"account:premium:{account_id}"),
        )
        return

    message_id = result["message_id"]
    amount_display = result.get("amount_display", "?")

    # Now get payment URL
    await status_msg.edit_text(
        f"⏳ <b>Получение ссылки на оплату...</b>\n\n"
        f"📱 {account.phone}\n"
        f"💰 Сумма: {amount_display}",
        parse_mode="HTML",
    )

    payment_result = await get_payment_url_for_account(
        account_id=account_id,
        session=session,
        message_id=message_id,
        proxy_config=proxy_config,
    )

    if not payment_result.get("success"):
        error = payment_result.get("error", "Unknown error")
        await status_msg.edit_text(
            f"❌ <b>Ошибка получения ссылки</b>\n\n"
            f"<code>{error}</code>\n\n"
            f"Попробуйте позже.",
            parse_mode="HTML",
            reply_markup=get_back_kb(f"account:premium:{account_id}"),
        )
        return

    payment_url = payment_result.get("payment_url")
    native_provider = payment_result.get("native_provider")
    can_tokenize = payment_result.get("can_tokenize", False)

    # Check if we can tokenize card directly (Smart Glocal or Stripe)
    if can_tokenize and payment_result.get("public_token"):
        # Create payment session and redirect to web form
        from src.presentation.api.routes.premium import create_payment_session
        from src.config import get_settings

        public_token = payment_result.get("public_token")
        form_id = payment_result.get("form_id")
        bot_id = payment_result.get("bot_id")
        session_string = payment_result.get("session_string")
        amount = payment_result.get("amount")
        currency = payment_result.get("currency", "RUB")

        # Format amount for display
        amount_str = f"{amount / 100:.2f}" if amount else amount_display.split()[0]

        # Create payment session with proxy config for anti-detection
        session_id = create_payment_session(
            account_id=str(account_id),
            form_id=form_id,
            public_token=public_token,
            amount=amount_str,
            currency=currency,
            recipient_name=account.phone,
            bot_id=bot_id,
            message_id=message_id,
            session_string=session_string,
            proxy_config=proxy_config,  # CRITICAL: Pass proxy to avoid IP leak
        )

        # Build payment URL
        settings = get_settings()
        payment_form_url = f"{settings.api_base_url}/api/v1/premium/pay/{session_id}"

        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="💳 Оплатить картой", url=payment_form_url))
        kb.row(InlineKeyboardButton(
            text="✅ Я оплатил",
            callback_data=f"account:premium:check:{account_id}",
        ))
        kb.row(InlineKeyboardButton(text="◀️ Назад", callback_data=f"account:view:{account_id}"))

        await status_msg.edit_text(
            f"💳 <b>Оплата Telegram Premium</b>\n\n"
            f"📱 {account.phone}\n"
            f"💰 Сумма: <b>{amount_str} {currency}</b>\n\n"
            f"Нажмите «Оплатить картой», введите данные карты на странице оплаты.\n\n"
            f"После успешной оплаты Premium будет активирован автоматически.",
            parse_mode="HTML",
            reply_markup=kb.as_markup(),
        )

    elif payment_url:
        # External payment URL
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="💳 Оплатить", url=payment_url))
        kb.row(InlineKeyboardButton(
            text="✅ Я оплатил",
            callback_data=f"account:premium:check:{account_id}",
        ))
        kb.row(InlineKeyboardButton(text="◀️ Назад", callback_data=f"account:view:{account_id}"))

        # Warn that external URL may not work reliably
        warning = ""
        if "smart-glocal" in payment_url.lower() or "tokenize" in payment_url.lower():
            warning = (
                "\n\n⚠️ <i>Примечание: эта ссылка предназначена для встроенного "
                "браузера Telegram. В обычном браузере оплата может не завершиться. "
                "Если не получается, попробуйте оплатить вручную через @PremiumBot в клиенте Telegram.</i>"
            )

        await status_msg.edit_text(
            f"💳 <b>Оплата Telegram Premium</b>\n\n"
            f"📱 {account.phone}\n"
            f"💰 Сумма: <b>{amount_display}</b>\n\n"
            f"Нажмите «Оплатить», введите данные карты на сайте и завершите оплату.\n\n"
            f"После успешной оплаты нажмите «Я оплатил» для проверки статуса."
            f"{warning}",
            parse_mode="HTML",
            reply_markup=kb.as_markup(),
        )

    else:
        # No payment method available
        await status_msg.edit_text(
            f"❌ <b>Не удалось получить метод оплаты</b>\n\n"
            f"Провайдер: {native_provider or 'неизвестен'}\n\n"
            f"Попробуйте оплатить вручную через @PremiumBot.",
            parse_mode="HTML",
            reply_markup=get_back_kb(f"account:premium:{account_id}"),
        )


@router.message(AccountStates.waiting_card_number)
async def premium_card_number(message: Message, state: FSMContext) -> None:
    """Process card number input."""
    # Clean card number
    card_number = message.text.replace(" ", "").replace("-", "")

    # Validate
    if not card_number.isdigit() or len(card_number) < 13 or len(card_number) > 19:
        await message.answer(
            "❌ Неверный номер карты.\n\n"
            "Введите 13-19 цифр без пробелов.",
        )
        return

    # Delete message with card number for security
    try:
        await message.delete()
    except Exception:
        pass

    # Save and ask for expiry
    await state.update_data(card_number=card_number)
    await state.set_state(AccountStates.waiting_card_expiry)

    data = await state.get_data()
    account_id = data.get("premium_account_id")

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"account:premium:{account_id}"))

    await message.answer(
        f"✅ Номер карты: <code>****{card_number[-4:]}</code>\n\n"
        f"Введите <b>срок действия</b> (ММ/ГГ или ММ/ГГГГ):\n\n"
        f"<i>Пример: 12/25 или 12/2025</i>",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )


@router.message(AccountStates.waiting_card_expiry)
async def premium_card_expiry(message: Message, state: FSMContext) -> None:
    """Process card expiry input."""
    import re

    text = message.text.strip()

    # Parse expiry
    match = re.match(r"(\d{1,2})[/\-.](\d{2,4})", text)
    if not match:
        await message.answer(
            "❌ Неверный формат.\n\n"
            "Введите в формате ММ/ГГ или ММ/ГГГГ (например: 12/25)",
        )
        return

    month = int(match.group(1))
    year = int(match.group(2))

    # Normalize year
    if year < 100:
        year += 2000

    # Validate
    if not (1 <= month <= 12):
        await message.answer("❌ Месяц должен быть от 01 до 12")
        return

    if year < 2024 or year > 2040:
        await message.answer("❌ Неверный год")
        return

    # Delete message
    try:
        await message.delete()
    except Exception:
        pass

    # Save and ask for CVC
    await state.update_data(card_exp_month=month, card_exp_year=year)
    await state.set_state(AccountStates.waiting_card_cvc)

    data = await state.get_data()
    account_id = data.get("premium_account_id")

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"account:premium:{account_id}"))

    await message.answer(
        f"✅ Срок: {month:02d}/{year}\n\n"
        f"Введите <b>CVC/CVV</b> (3-4 цифры с обратной стороны карты):",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )


@router.message(AccountStates.waiting_card_cvc)
async def premium_card_cvc_and_pay(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Process CVC and complete payment."""
    from src.services.premium_service import pay_premium_with_card, CardData

    cvc = message.text.strip()

    # Validate
    if not cvc.isdigit() or len(cvc) < 3 or len(cvc) > 4:
        await message.answer("❌ CVC должен быть 3-4 цифры")
        return

    # Delete message with CVC
    try:
        await message.delete()
    except Exception:
        pass

    data = await state.get_data()
    account_id = UUID(data["premium_account_id"])
    message_id = data["premium_message_id"]
    proxy_config = data.get("proxy_config")

    # Clear state
    await state.clear()

    # Create card data
    card = CardData(
        number=data["card_number"],
        exp_month=data["card_exp_month"],
        exp_year=data["card_exp_year"],
        cvc=cvc,
    )

    status_msg = await message.answer(
        f"⏳ <b>Обработка платежа...</b>\n\n"
        f"Отправляю данные в Stripe...",
        parse_mode="HTML",
    )

    # Process payment
    result = await pay_premium_with_card(
        account_id=account_id,
        session=session,
        message_id=message_id,
        card=card,
        save_card=False,
        proxy_config=proxy_config,
    )

    if not result.get("success"):
        error = result.get("error", "Unknown error")
        await status_msg.edit_text(
            f"❌ <b>Ошибка оплаты</b>\n\n"
            f"<code>{error}</code>\n\n"
            f"Проверьте данные карты и попробуйте снова.",
            parse_mode="HTML",
            reply_markup=get_back_kb(f"account:premium:{account_id}"),
        )
        return

    if result.get("completed"):
        # Payment successful!
        repo = PostgresAccountRepository(session)
        account = await repo.get_by_id(account_id)
        if account:
            account.is_premium = True
            await repo.save(account)

        await status_msg.edit_text(
            f"🎉 <b>Оплата успешна!</b>\n\n"
            f"✅ Telegram Premium активирован!\n\n"
            f"Поздравляем с покупкой!",
            parse_mode="HTML",
            reply_markup=get_back_kb(f"account:view:{account_id}"),
        )

    elif result.get("has_url"):
        # External payment URL (web-based checkout)
        payment_url = result.get("payment_url", "")

        kb = InlineKeyboardBuilder()
        if payment_url:
            kb.row(InlineKeyboardButton(text="💳 Оплатить", url=payment_url))
        kb.row(InlineKeyboardButton(
            text="✅ Я оплатил",
            callback_data=f"account:premium:check:{account_id}",
        ))
        kb.row(InlineKeyboardButton(text="◀️ Назад", callback_data=f"account:view:{account_id}"))

        await status_msg.edit_text(
            f"💳 <b>Оплата через внешний сервис</b>\n\n"
            f"Нажмите «Оплатить» и завершите оплату.\n\n"
            f"После оплаты нажмите «Я оплатил».",
            parse_mode="HTML",
            reply_markup=kb.as_markup(),
        )

    elif result.get("needs_verification"):
        # Need 3DS
        verification_url = result.get("verification_url", "")

        kb = InlineKeyboardBuilder()
        if verification_url:
            kb.row(InlineKeyboardButton(text="🔐 Пройти 3DS", url=verification_url))
        kb.row(InlineKeyboardButton(
            text="✅ Я подтвердил",
            callback_data=f"account:premium:check:{account_id}",
        ))
        kb.row(InlineKeyboardButton(text="◀️ Назад", callback_data=f"account:view:{account_id}"))

        await status_msg.edit_text(
            f"🔐 <b>Требуется подтверждение 3DS</b>\n\n"
            f"Нажмите «Пройти 3DS» и подтвердите платёж в банке.\n\n"
            f"После подтверждения нажмите «Я подтвердил».",
            parse_mode="HTML",
            reply_markup=kb.as_markup(),
        )


@router.callback_query(F.data.regexp(r"^account:premium:check:[0-9a-f-]+$"))
async def premium_check_status(callback: CallbackQuery, session: AsyncSession) -> None:
    """Check if premium was activated."""
    from src.services.premium_service import check_premium_status
    from src.infrastructure.database.repositories import PostgresProxyRepository

    account_id = UUID(callback.data.split(":")[3])

    repo = PostgresAccountRepository(session)
    account = await repo.get_by_id(account_id)

    if not account:
        await callback.answer("❌ Аккаунт не найден", show_alert=True)
        return

    await callback.answer("⏳ Проверяю статус Premium...", show_alert=False)

    # Get proxy
    proxy_config = None
    if account.proxy_id:
        proxy_repo = PostgresProxyRepository(session)
        proxy = await proxy_repo.get_by_id(account.proxy_id)
        if proxy:
            proxy_config = {
                "host": proxy.host,
                "port": proxy.port,
                "username": proxy.username,
                "password": proxy.password,
            }

    result = await check_premium_status(
        account_id=account_id,
        session=session,
        proxy_config=proxy_config,
    )

    if not result.get("success"):
        await callback.message.edit_text(
            f"❌ Ошибка проверки: {result.get('error', '?')}",
            reply_markup=get_back_kb(f"account:premium:{account_id}"),
        )
        return

    if result.get("has_premium"):
        # Update account
        account.is_premium = True
        await repo.save(account)

        await callback.message.edit_text(
            f"🎉 <b>Premium активирован!</b>\n\n"
            f"📱 {account.phone}\n"
            f"👤 @{account.username or '—'}\n\n"
            f"✅ Telegram Premium успешно активирован!",
            parse_mode="HTML",
            reply_markup=get_back_kb(f"account:view:{account_id}"),
        )
    else:
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(
            text="🔄 Проверить ещё раз",
            callback_data=f"account:premium:check:{account_id}",
        ))
        kb.row(InlineKeyboardButton(text="◀️ Назад", callback_data=f"account:view:{account_id}"))

        await callback.message.edit_text(
            f"⏳ <b>Premium пока не активирован</b>\n\n"
            f"📱 {account.phone}\n\n"
            f"Если вы прошли 3DS подтверждение, подождите 1-2 минуты.\n"
            f"Иногда активация занимает время.",
            parse_mode="HTML",
            reply_markup=kb.as_markup(),
        )


# =============================================================================
# Account Re-authorization (for imported accounts)
# =============================================================================


@router.callback_query(F.data.regexp(r"^account:reauth:[0-9a-f-]+$"))
async def reauth_account_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """
    Start automatic re-authorization for imported account.

    This will:
    1. Connect to the existing session
    2. Request new login code
    3. Intercept the code from the old session
    4. Complete authorization with new native session
    """
    from src.application.services.account_auth import get_auth_service
    from src.infrastructure.database.repositories import PostgresProxyRepository

    account_id = UUID(callback.data.split(":")[-1])

    await callback.answer("⏳ Начинаю переавторизацию...", show_alert=False)

    repo = PostgresAccountRepository(session)
    account = await repo.get_by_id(account_id)

    if not account:
        await callback.answer("❌ Аккаунт не найден", show_alert=True)
        return

    # Check source
    if account.source == AccountSource.PHONE:
        await callback.message.answer(
            "ℹ️ Этот аккаунт уже авторизован через номер телефона.\n"
            "Переавторизация не требуется.",
            reply_markup=get_back_kb(f"account:view:{account_id}"),
        )
        return

    # Check if has session data
    if not account.session_data:
        await callback.message.answer(
            "❌ У аккаунта отсутствуют данные сессии.\n"
            "Невозможно выполнить переавторизацию.",
            reply_markup=get_back_kb(f"account:view:{account_id}"),
        )
        return

    # Check if has proxy
    if not account.proxy_id:
        await callback.message.answer(
            "❌ У аккаунта не назначен прокси.\n"
            "Сначала назначьте прокси.",
            reply_markup=get_back_kb(f"account:view:{account_id}"),
        )
        return

    # Get proxy
    proxy_repo = PostgresProxyRepository(session)
    proxy = await proxy_repo.get_by_id(account.proxy_id)

    if not proxy:
        await callback.message.answer(
            "❌ Прокси не найден.",
            reply_markup=get_back_kb(f"account:view:{account_id}"),
        )
        return

    # Check for 2FA password - we need it stored somewhere
    # For now, prompt user to enter it if needed
    await state.update_data(
        reauth_account_id=str(account_id),
        reauth_proxy_id=str(proxy.id),
    )
    await state.set_state(AccountStates.waiting_reauth_2fa)

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="🔓 Без 2FA (пропустить)",
        callback_data=f"account:reauth:no2fa:{account_id}",
    ))
    kb.row(InlineKeyboardButton(
        text="❌ Отмена",
        callback_data=f"account:view:{account_id}",
    ))

    await callback.message.answer(
        f"🔄 <b>Переавторизация аккаунта</b>\n\n"
        f"📱 Аккаунт: {account.phone}\n"
        f"🌐 Прокси: {proxy.host}:{proxy.port}\n\n"
        f"Если у аккаунта включена <b>2FA</b>, введите пароль:\n\n"
        f"<i>Или нажмите 'Без 2FA' если пароль не установлен</i>",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.regexp(r"^account:reauth:no2fa:[0-9a-f-]+$"))
async def reauth_account_no2fa(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Start re-authorization without 2FA password."""
    account_id = UUID(callback.data.split(":")[-1])

    await state.update_data(reauth_2fa_password=None)
    await _perform_reauth(callback, state, session, account_id, None)


@router.message(AccountStates.waiting_reauth_2fa)
async def reauth_account_with_2fa(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Receive 2FA password and start re-authorization."""
    data = await state.get_data()
    account_id = UUID(data.get("reauth_account_id"))
    twofa_password = message.text.strip()

    # Delete the password message for security
    try:
        await message.delete()
    except Exception:
        pass

    await _perform_reauth(message, state, session, account_id, twofa_password)


async def _perform_reauth(
    event,  # Can be CallbackQuery or Message
    state: FSMContext,
    session: AsyncSession,
    account_id: UUID,
    twofa_password: str | None,
) -> None:
    """Perform the actual re-authorization."""
    import asyncio
    from src.application.services.account_auth import get_auth_service
    from src.infrastructure.database.repositories import PostgresProxyRepository

    # Get the message object
    if hasattr(event, 'message'):
        msg = event.message
    else:
        msg = event

    repo = PostgresAccountRepository(session)
    account = await repo.get_by_id(account_id)

    if not account:
        await msg.answer("❌ Аккаунт не найден", reply_markup=get_main_menu_kb())
        await state.clear()
        return

    proxy_repo = PostgresProxyRepository(session)
    proxy = await proxy_repo.get_by_id(account.proxy_id)

    if not proxy:
        await msg.answer("❌ Прокси не найден", reply_markup=get_main_menu_kb())
        await state.clear()
        return

    # Create status message
    status_msg = await msg.answer(
        f"🔄 <b>Переавторизация</b>\n\n"
        f"📱 Аккаунт: {account.phone}\n\n"
        f"⏳ Подключаюсь к старой сессии...",
    )

    auth_service = get_auth_service()

    async def progress_callback(step: str, message: str):
        """Update status message with progress."""
        try:
            await status_msg.edit_text(
                f"🔄 <b>Переавторизация</b>\n\n"
                f"📱 Аккаунт: {account.phone}\n\n"
                f"⏳ {message}",
            )
        except Exception:
            pass

    try:
        # Perform automatic re-authorization
        new_session_data, user_info = await auth_service.auto_reauthorize(
            old_session_data=account.session_data,
            phone=account.phone,
            proxy=proxy,
            twofa_password=twofa_password,
            timeout_seconds=120,
            progress_callback=progress_callback,
        )

        # Update account with new session
        account.session_data = new_session_data
        account.source = AccountSource.PHONE  # Now it's a native session
        account.telegram_id = user_info.get("telegram_id")
        account.username = user_info.get("username")
        account.first_name = user_info.get("first_name", "")
        account.last_name = user_info.get("last_name", "")
        account.is_premium = user_info.get("is_premium", False)
        account.status = AccountStatus.READY
        account.error_message = None

        await repo.save(account)
        await state.clear()

        await status_msg.edit_text(
            f"✅ <b>Переавторизация успешна!</b>\n\n"
            f"📱 Аккаунт: {account.phone}\n"
            f"👤 {account.first_name} {account.last_name}\n"
            f"🆔 @{account.username or '—'}\n\n"
            f"📁 Источник: 📱 Авторизован по номеру\n"
            f"Статус: 🔵 Готов к работе",
            reply_markup=get_back_kb(f"account:view:{account_id}"),
        )

    except TimeoutError:
        await status_msg.edit_text(
            f"⏰ <b>Таймаут</b>\n\n"
            f"Код авторизации не пришёл за 2 минуты.\n\n"
            f"Возможные причины:\n"
            f"• Старая сессия невалидна\n"
            f"• Проблемы с прокси\n"
            f"• Telegram не отправил код",
            reply_markup=get_back_kb(f"account:view:{account_id}"),
        )
        await state.clear()

    except ValueError as e:
        error_msg = str(e)
        if "2FA" in error_msg:
            # Need 2FA password
            await status_msg.edit_text(
                f"🔐 <b>Требуется пароль 2FA</b>\n\n"
                f"Введите пароль двухфакторной аутентификации:",
            )
            await state.update_data(reauth_account_id=str(account_id))
            await state.set_state(AccountStates.waiting_reauth_2fa)
        else:
            await status_msg.edit_text(
                f"❌ <b>Ошибка</b>\n\n"
                f"<code>{error_msg[:200]}</code>",
                reply_markup=get_back_kb(f"account:view:{account_id}"),
            )
            await state.clear()

    except Exception as e:
        import traceback
        traceback.print_exc()
        await status_msg.edit_text(
            f"❌ <b>Ошибка переавторизации</b>\n\n"
            f"<code>{str(e)[:200]}</code>",
            reply_markup=get_back_kb(f"account:view:{account_id}"),
        )
        await state.clear()


# =============================================================================
# Account Customization (name, bio, avatar)
# =============================================================================


@router.callback_query(F.data.regexp(r"^account:customize:[0-9a-f-]+$"))
async def customize_account_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show customization options for account."""
    from src.infrastructure.database.repositories import PostgresProxyRepository

    account_id = UUID(callback.data.split(":")[-1])

    repo = PostgresAccountRepository(session)
    account = await repo.get_by_id(account_id)

    if not account:
        await callback.answer("❌ Аккаунт не найден", show_alert=True)
        return

    if not account.proxy_id:
        await callback.message.answer(
            "❌ У аккаунта не назначен прокси.\n"
            "Сначала назначьте прокси.",
            reply_markup=get_back_kb(f"account:view:{account_id}"),
        )
        return

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="👤 Изменить имя",
        callback_data=f"account:customize:name:{account_id}",
    ))
    kb.row(InlineKeyboardButton(
        text="📝 Изменить био",
        callback_data=f"account:customize:bio:{account_id}",
    ))
    kb.row(InlineKeyboardButton(
        text="🖼 Изменить аватар",
        callback_data=f"account:customize:avatar:{account_id}",
    ))
    kb.row(InlineKeyboardButton(
        text="🗑 Удалить аватар",
        callback_data=f"account:customize:delavatar:{account_id}",
    ))
    kb.row(InlineKeyboardButton(
        text="◀️ Назад",
        callback_data=f"account:view:{account_id}",
    ))

    await callback.message.edit_text(
        f"✏️ <b>Кастомизация аккаунта</b>\n\n"
        f"📱 Аккаунт: {account.phone}\n"
        f"👤 Имя: {account.first_name} {account.last_name}\n"
        f"🆔 Username: @{account.username or '—'}\n\n"
        f"Выберите что изменить:",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^account:customize:name:[0-9a-f-]+$"))
async def customize_name_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Start name customization."""
    account_id = UUID(callback.data.split(":")[-1])

    repo = PostgresAccountRepository(session)
    account = await repo.get_by_id(account_id)

    if not account:
        await callback.answer("❌ Аккаунт не найден", show_alert=True)
        return

    await state.update_data(customize_account_id=str(account_id))
    await state.set_state(AccountStates.waiting_customize_name)

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="❌ Отмена",
        callback_data=f"account:customize:{account_id}",
    ))

    await callback.message.edit_text(
        f"👤 <b>Изменение имени</b>\n\n"
        f"Текущее имя: <b>{account.first_name} {account.last_name}</b>\n\n"
        f"Отправьте новое имя в формате:\n"
        f"<code>Имя</code> или <code>Имя Фамилия</code>",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.message(AccountStates.waiting_customize_name)
async def customize_name_apply(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Apply new name to account."""
    from src.application.services.account_profile import get_profile_service
    from src.infrastructure.database.repositories import PostgresProxyRepository

    data = await state.get_data()
    account_id = UUID(data.get("customize_account_id"))

    repo = PostgresAccountRepository(session)
    account = await repo.get_by_id(account_id)

    if not account:
        await message.answer("❌ Аккаунт не найден", reply_markup=get_main_menu_kb())
        await state.clear()
        return

    proxy_repo = PostgresProxyRepository(session)
    proxy = await proxy_repo.get_by_id(account.proxy_id)

    if not proxy:
        await message.answer("❌ Прокси не найден", reply_markup=get_main_menu_kb())
        await state.clear()
        return

    # Parse name
    name_parts = message.text.strip().split(None, 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    status_msg = await message.answer("⏳ Обновляю имя...")

    try:
        profile_service = get_profile_service()
        result = await profile_service.update_profile(
            session_data=account.session_data,
            proxy=proxy,
            first_name=first_name,
            last_name=last_name,
        )

        # Update account in DB
        account.first_name = result.get("first_name", first_name)
        account.last_name = result.get("last_name", last_name)
        await repo.save(account)

        await state.clear()

        await status_msg.edit_text(
            f"✅ <b>Имя обновлено!</b>\n\n"
            f"👤 Новое имя: {account.first_name} {account.last_name}",
            reply_markup=get_back_kb(f"account:customize:{account_id}"),
        )

    except Exception as e:
        await status_msg.edit_text(
            f"❌ <b>Ошибка</b>\n\n<code>{str(e)[:200]}</code>",
            reply_markup=get_back_kb(f"account:customize:{account_id}"),
        )
        await state.clear()


@router.callback_query(F.data.regexp(r"^account:customize:bio:[0-9a-f-]+$"))
async def customize_bio_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Start bio customization."""
    account_id = UUID(callback.data.split(":")[-1])

    await state.update_data(customize_account_id=str(account_id))
    await state.set_state(AccountStates.waiting_customize_bio)

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="🗑 Очистить био",
        callback_data=f"account:customize:clearbio:{account_id}",
    ))
    kb.row(InlineKeyboardButton(
        text="❌ Отмена",
        callback_data=f"account:customize:{account_id}",
    ))

    await callback.message.edit_text(
        f"📝 <b>Изменение био</b>\n\n"
        f"Отправьте новый текст био (до 70 символов):\n\n"
        f"<i>Или нажмите 'Очистить био' чтобы удалить</i>",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^account:customize:clearbio:[0-9a-f-]+$"))
async def customize_bio_clear(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Clear bio."""
    from src.application.services.account_profile import get_profile_service
    from src.infrastructure.database.repositories import PostgresProxyRepository

    account_id = UUID(callback.data.split(":")[-1])

    repo = PostgresAccountRepository(session)
    account = await repo.get_by_id(account_id)

    if not account:
        await callback.answer("❌ Аккаунт не найден", show_alert=True)
        return

    proxy_repo = PostgresProxyRepository(session)
    proxy = await proxy_repo.get_by_id(account.proxy_id)

    if not proxy:
        await callback.answer("❌ Прокси не найден", show_alert=True)
        return

    await callback.answer("⏳ Очищаю био...")

    try:
        profile_service = get_profile_service()
        await profile_service.update_profile(
            session_data=account.session_data,
            proxy=proxy,
            bio="",
        )

        await state.clear()

        await callback.message.edit_text(
            f"✅ <b>Био очищено!</b>",
            reply_markup=get_back_kb(f"account:customize:{account_id}"),
        )

    except Exception as e:
        await callback.message.edit_text(
            f"❌ <b>Ошибка</b>\n\n<code>{str(e)[:200]}</code>",
            reply_markup=get_back_kb(f"account:customize:{account_id}"),
        )


@router.message(AccountStates.waiting_customize_bio)
async def customize_bio_apply(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Apply new bio to account."""
    from src.application.services.account_profile import get_profile_service
    from src.infrastructure.database.repositories import PostgresProxyRepository

    data = await state.get_data()
    account_id = UUID(data.get("customize_account_id"))

    repo = PostgresAccountRepository(session)
    account = await repo.get_by_id(account_id)

    if not account:
        await message.answer("❌ Аккаунт не найден", reply_markup=get_main_menu_kb())
        await state.clear()
        return

    proxy_repo = PostgresProxyRepository(session)
    proxy = await proxy_repo.get_by_id(account.proxy_id)

    if not proxy:
        await message.answer("❌ Прокси не найден", reply_markup=get_main_menu_kb())
        await state.clear()
        return

    bio = message.text.strip()[:70]  # Max 70 chars

    status_msg = await message.answer("⏳ Обновляю био...")

    try:
        profile_service = get_profile_service()
        await profile_service.update_profile(
            session_data=account.session_data,
            proxy=proxy,
            bio=bio,
        )

        await state.clear()

        await status_msg.edit_text(
            f"✅ <b>Био обновлено!</b>\n\n"
            f"📝 Новое био: {bio}",
            reply_markup=get_back_kb(f"account:customize:{account_id}"),
        )

    except Exception as e:
        await status_msg.edit_text(
            f"❌ <b>Ошибка</b>\n\n<code>{str(e)[:200]}</code>",
            reply_markup=get_back_kb(f"account:customize:{account_id}"),
        )
        await state.clear()


@router.callback_query(F.data.regexp(r"^account:customize:avatar:[0-9a-f-]+$"))
async def customize_avatar_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Start avatar customization."""
    account_id = UUID(callback.data.split(":")[-1])

    await state.update_data(customize_account_id=str(account_id))
    await state.set_state(AccountStates.waiting_customize_avatar)

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="❌ Отмена",
        callback_data=f"account:customize:{account_id}",
    ))

    await callback.message.edit_text(
        f"🖼 <b>Изменение аватара</b>\n\n"
        f"Отправьте новое фото для аватара:\n\n"
        f"<i>Рекомендуется квадратное фото минимум 512x512</i>",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.message(AccountStates.waiting_customize_avatar, F.photo)
async def customize_avatar_apply(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Apply new avatar to account."""
    from src.application.services.account_profile import get_profile_service
    from src.infrastructure.database.repositories import PostgresProxyRepository

    data = await state.get_data()
    account_id = UUID(data.get("customize_account_id"))

    repo = PostgresAccountRepository(session)
    account = await repo.get_by_id(account_id)

    if not account:
        await message.answer("❌ Аккаунт не найден", reply_markup=get_main_menu_kb())
        await state.clear()
        return

    proxy_repo = PostgresProxyRepository(session)
    proxy = await proxy_repo.get_by_id(account.proxy_id)

    if not proxy:
        await message.answer("❌ Прокси не найден", reply_markup=get_main_menu_kb())
        await state.clear()
        return

    status_msg = await message.answer("⏳ Загружаю аватар...")

    try:
        # Download photo
        photo = message.photo[-1]  # Largest size
        file = await message.bot.download(photo)
        photo_bytes = file.read()

        profile_service = get_profile_service()
        await profile_service.update_photo(
            session_data=account.session_data,
            photo_bytes=photo_bytes,
            proxy=proxy,
        )

        await state.clear()

        await status_msg.edit_text(
            f"✅ <b>Аватар обновлён!</b>",
            reply_markup=get_back_kb(f"account:customize:{account_id}"),
        )

    except Exception as e:
        await status_msg.edit_text(
            f"❌ <b>Ошибка</b>\n\n<code>{str(e)[:200]}</code>",
            reply_markup=get_back_kb(f"account:customize:{account_id}"),
        )
        await state.clear()


@router.callback_query(F.data.regexp(r"^account:customize:delavatar:[0-9a-f-]+$"))
async def customize_avatar_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    """Delete all avatars."""
    from src.application.services.account_profile import get_profile_service
    from src.infrastructure.database.repositories import PostgresProxyRepository

    account_id = UUID(callback.data.split(":")[-1])

    repo = PostgresAccountRepository(session)
    account = await repo.get_by_id(account_id)

    if not account:
        await callback.answer("❌ Аккаунт не найден", show_alert=True)
        return

    proxy_repo = PostgresProxyRepository(session)
    proxy = await proxy_repo.get_by_id(account.proxy_id)

    if not proxy:
        await callback.answer("❌ Прокси не найден", show_alert=True)
        return

    await callback.answer("⏳ Удаляю аватары...")

    try:
        profile_service = get_profile_service()
        result = await profile_service.delete_photos(
            session_data=account.session_data,
            proxy=proxy,
        )

        await callback.message.edit_text(
            f"✅ <b>Аватары удалены!</b>\n\n"
            f"Удалено фото: {result.get('deleted_count', 0)}",
            reply_markup=get_back_kb(f"account:customize:{account_id}"),
        )

    except Exception as e:
        await callback.message.edit_text(
            f"❌ <b>Ошибка</b>\n\n<code>{str(e)[:200]}</code>",
            reply_markup=get_back_kb(f"account:customize:{account_id}"),
        )


@router.callback_query(F.data.startswith("account:delete:confirm:"))
async def delete_account(callback: CallbackQuery, session: AsyncSession) -> None:
    """Delete account."""
    account_id = UUID(callback.data.split(":")[-1])

    repo = PostgresAccountRepository(session)
    deleted = await repo.delete(account_id)
    await session.commit()

    if deleted:
        await callback.message.edit_text(
            "✅ Аккаунт удалён.",
            reply_markup=get_accounts_menu_kb(),
        )
    else:
        await callback.answer("❌ Ошибка удаления", show_alert=True)


@router.callback_query(F.data.startswith("account:delete:"))
async def delete_account_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    """Confirm account deletion."""
    account_id = callback.data.split(":")[-1]

    await callback.message.edit_text(
        "⚠️ <b>Удаление аккаунта</b>\n\n"
        "Вы уверены? Это действие необратимо.\n"
        "Все диалоги аккаунта будут удалены.",
        reply_markup=get_confirm_kb(
            confirm_callback=f"account:delete:confirm:{account_id}",
            cancel_callback=f"account:view:{account_id}",
        ),
    )
    await callback.answer()


# =============================================================================
# Add Account
# =============================================================================

@router.callback_query(F.data == "accounts:add")
async def add_account_menu(callback: CallbackQuery) -> None:
    """Show add account options."""
    await callback.message.edit_text(
        "➕ <b>Добавление аккаунта</b>\n\n"
        "Выберите способ добавления:",
        reply_markup=get_account_add_method_kb(),
    )
    await callback.answer()


# =============================================================================
# Add Account via ZIP Archive
# =============================================================================

@router.callback_query(F.data == "accounts:add:zip")
async def add_account_zip_start(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Start ZIP archive upload - first select proxy group."""
    from src.infrastructure.database.repositories import ProxyGroupRepository, PostgresProxyRepository

    # Check if there are proxy groups
    group_repo = ProxyGroupRepository(session)
    groups = await group_repo.get_all()

    kb = InlineKeyboardBuilder()

    if groups:
        # Show proxy groups first
        for group in groups:
            available = await group_repo.count_available_proxies_in_group(group.id)
            if available > 0:
                country = f" [{group.country_code}]" if group.country_code else ""
                kb.row(InlineKeyboardButton(
                    text=f"📁 {group.name}{country} ({available} своб.)",
                    callback_data=f"accounts:add:zip:group:{group.id}",
                ))

    # Also offer to select from all proxies
    proxy_repo = PostgresProxyRepository(session)
    all_available = await proxy_repo.count_available()

    if all_available > 0:
        kb.row(InlineKeyboardButton(
            text=f"🌐 Все прокси ({all_available} своб.)",
            callback_data="accounts:add:zip:all_proxies",
        ))

    kb.row(InlineKeyboardButton(
        text="◀️ Назад",
        callback_data="accounts:add",
    ))

    if not groups and all_available == 0:
        await callback.message.edit_text(
            "📦 <b>Загрузка ZIP-архива</b>\n\n"
            "⚠️ <b>Нет доступных прокси!</b>\n\n"
            "Для загрузки и проверки аккаунта нужен прокси.\n"
            "Сначала добавьте прокси в разделе 🌐 Прокси.",
            reply_markup=get_back_kb("accounts:menu"),
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "📦 <b>Загрузка ZIP-архива</b>\n\n"
        "Шаг 1/3: <b>Выберите группу прокси</b>\n\n"
        "Прокси будет выбран из указанной группы.\n\n"
        "<i>Группы помогают организовать прокси по странам/типам</i>",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("accounts:add:zip:group:"))
async def add_account_zip_select_from_group(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Select proxy from a specific group for ZIP upload."""
    from src.infrastructure.database.repositories import ProxyGroupRepository

    group_id = UUID(callback.data.split(":")[4])

    group_repo = ProxyGroupRepository(session)
    group = await group_repo.get_by_id(group_id)

    if not group:
        await callback.answer("❌ Группа не найдена", show_alert=True)
        return

    proxies = await group_repo.get_available_proxies_in_group(group_id)

    if not proxies:
        await callback.answer("❌ В этой группе нет свободных прокси", show_alert=True)
        return

    # Save group to state
    await state.update_data(proxy_group_id=str(group_id), proxy_group_name=group.name)

    # Build proxy selection keyboard
    kb = InlineKeyboardBuilder()

    for proxy in proxies[:10]:  # Max 10 proxies
        latency = f" ({proxy.last_check_latency_ms}ms)" if proxy.last_check_latency_ms else ""
        kb.row(InlineKeyboardButton(
            text=f"🌐 {proxy.host}:{proxy.port}{latency}",
            callback_data=f"accounts:add:zip:proxy:{proxy.id}",
        ))

    kb.row(InlineKeyboardButton(
        text="◀️ Назад",
        callback_data="accounts:add:zip",
    ))

    await callback.message.edit_text(
        f"📦 <b>Загрузка ZIP-архива</b>\n\n"
        f"Шаг 2/3: <b>Выберите прокси</b>\n\n"
        f"📁 Группа: <b>{group.name}</b>\n\n"
        f"Доступно: {len(proxies)} прокси",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "accounts:add:zip:all_proxies")
async def add_account_zip_select_from_all(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Select proxy from all available proxies for ZIP upload."""
    from src.infrastructure.database.repositories import PostgresProxyRepository

    proxy_repo = PostgresProxyRepository(session)
    proxies = await proxy_repo.list_available()

    if not proxies:
        await callback.answer("❌ Нет свободных прокси", show_alert=True)
        return

    # Clear group from state (selecting from all)
    await state.update_data(proxy_group_id=None, proxy_group_name=None)

    # Build proxy selection keyboard
    kb = InlineKeyboardBuilder()

    for proxy in proxies[:10]:  # Max 10 proxies
        latency = f" ({proxy.last_check_latency_ms}ms)" if proxy.last_check_latency_ms else ""
        kb.row(InlineKeyboardButton(
            text=f"🌐 {proxy.host}:{proxy.port}{latency}",
            callback_data=f"accounts:add:zip:proxy:{proxy.id}",
        ))

    kb.row(InlineKeyboardButton(
        text="◀️ Назад",
        callback_data="accounts:add:zip",
    ))

    await callback.message.edit_text(
        "📦 <b>Загрузка ZIP-архива</b>\n\n"
        "Шаг 2/3: <b>Выберите прокси</b>\n\n"
        f"Доступно: {len(proxies)} прокси",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("accounts:add:zip:proxy:"))
async def add_account_zip_proxy_selected(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Proxy selected for ZIP upload, now request file."""
    from src.infrastructure.database.repositories import PostgresProxyRepository

    proxy_id = UUID(callback.data.split(":")[4])

    proxy_repo = PostgresProxyRepository(session)
    proxy = await proxy_repo.get_by_id(proxy_id)

    if not proxy:
        await callback.answer("❌ Прокси не найден", show_alert=True)
        return

    # Save proxy to state
    await state.update_data(proxy_id=str(proxy_id), proxy_host=proxy.host, proxy_port=proxy.port)
    await state.set_state(AccountStates.waiting_zip_file)

    # Get group name if selected from a group
    state_data = await state.get_data()
    group_name = state_data.get("proxy_group_name")
    group_info = f"\n📁 Группа: <b>{group_name}</b>" if group_name else ""

    await callback.message.edit_text(
        f"📦 <b>Загрузка ZIP-архива</b>\n\n"
        f"Шаг 3/3: <b>Отправьте архив</b>\n\n"
        f"🌐 Прокси: <code>{proxy.host}:{proxy.port}</code>{group_info}\n\n"
        "<b>Поддерживаемые форматы:</b>\n\n"
        "1️⃣ <b>tdata</b> (Telegram Desktop):\n"
        "<code>archive.zip/tdata/</code>\n"
        "  ├── D877F.../  (зашифрованные данные)\n"
        "  ├── key_datas\n"
        "  └── Password2FA.txt\n\n"
        "2️⃣ <b>Telethon session</b>:\n"
        "<code>archive.zip/</code>\n"
        "  ├── *.session\n"
        "  └── *.json\n\n"
        "⚡ tdata будет автоматически конвертирован в Telethon сессию.",
    )
    await callback.message.answer(
        "Ожидаю ZIP-архив...",
        reply_markup=get_cancel_kb(),
    )
    await callback.answer()


@router.message(AccountStates.waiting_zip_file, F.document)
async def receive_zip_file(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Receive and process ZIP archive with account data (tdata or session)."""
    import io
    import zipfile
    import tempfile
    import shutil
    import os
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import (
        SessionPasswordNeededError,
        AuthKeyDuplicatedError,
        PhoneNumberBannedError,
    )
    from src.config import get_settings
    from src.infrastructure.database.repositories import PostgresProxyRepository
    import python_socks

    doc = message.document

    if not doc.file_name.endswith(".zip"):
        await message.answer("❌ Отправьте файл с расширением .zip")
        return

    # Get proxy from state
    state_data = await state.get_data()
    proxy_id = state_data.get("proxy_id")

    if not proxy_id:
        await message.answer(
            "❌ Прокси не выбран. Начните заново.",
            reply_markup=get_main_menu_kb(),
        )
        await state.clear()
        return

    # Get proxy details
    proxy_repo = PostgresProxyRepository(session)
    proxy = await proxy_repo.get_by_id(UUID(proxy_id))

    if not proxy:
        await message.answer(
            "❌ Прокси не найден. Начните заново.",
            reply_markup=get_main_menu_kb(),
        )
        await state.clear()
        return

    status_msg = await message.answer("⏳ Распаковываю архив...")

    temp_dir = None
    client = None
    try:
        # Download ZIP file
        file = await message.bot.download(doc)
        zip_bytes = file.read()

        # Create temp directory for extraction
        temp_dir = tempfile.mkdtemp()

        # Extract ZIP
        with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zf:
            zf.extractall(temp_dir)

        # Check if it's tdata or session format
        is_tdata = _check_is_tdata(temp_dir)

        if is_tdata:
            await status_msg.edit_text("⏳ Обнаружен tdata, конвертирую в Telethon сессию...")
            account_data = await _convert_tdata_to_session(temp_dir)
        else:
            await status_msg.edit_text("⏳ Обрабатываю session файлы...")
            account_data = await _parse_session_files(temp_dir)

        if not account_data:
            await message.answer(
                "❌ Не удалось извлечь данные аккаунта.\n\n"
                "Убедитесь, что архив содержит:\n"
                "• tdata папку (с key_datas и D877F...)\n"
                "• или .session файл с .json",
                reply_markup=get_main_menu_kb(),
            )
            await state.clear()
            return

        # Get session string or bytes
        session_string = account_data.get("session_string")
        session_bytes = account_data.get("session_bytes")

        if not session_string and not session_bytes:
            await message.answer(
                "❌ Не удалось получить сессию из архива.",
                reply_markup=get_main_menu_kb(),
            )
            await state.clear()
            return

        # Build proxy dict for Telethon
        proxy_dict = {
            'proxy_type': python_socks.ProxyType.SOCKS5,
            'addr': proxy.host,
            'port': proxy.port,
            'username': proxy.username,
            'password': proxy.password,
            'rdns': True,
        }

        settings = get_settings()

        # Validate session through proxy
        await status_msg.edit_text(
            f"⏳ Проверяю сессию через прокси {proxy.host}:{proxy.port}..."
        )

        if session_string:
            # StringSession
            client = TelegramClient(
                StringSession(session_string),
                settings.telegram.api_id,
                settings.telegram.api_hash.get_secret_value(),
                proxy=proxy_dict,
            )
        else:
            # SQLite session file - try to convert to StringSession first
            temp_session_path = os.path.join(temp_dir, "temp_session")
            with open(temp_session_path + ".session", 'wb') as f:
                f.write(session_bytes)

            # Try converting to StringSession
            converted_string = await _convert_session_to_telethon_string(temp_session_path + ".session")
            if converted_string:
                session_string = converted_string
                client = TelegramClient(
                    StringSession(session_string),
                    settings.telegram.api_id,
                    settings.telegram.api_hash.get_secret_value(),
                    proxy=proxy_dict,
                )
            else:
                client = TelegramClient(
                    temp_session_path,
                    settings.telegram.api_id,
                    settings.telegram.api_hash.get_secret_value(),
                    proxy=proxy_dict,
                )

        try:
            import asyncio
            try:
                await asyncio.wait_for(client.connect(), timeout=30)
            except asyncio.TimeoutError:
                await message.answer(
                    "❌ Таймаут подключения к Telegram через прокси.\n"
                    "Проверьте работоспособность прокси.",
                    reply_markup=get_main_menu_kb(),
                )
                await state.clear()
                return

            # Check if authorized
            if not await client.is_user_authorized():
                await message.answer(
                    "❌ Сессия невалидна или устарела.\n"
                    "Аккаунт требует повторной авторизации.",
                    reply_markup=get_main_menu_kb(),
                )
                await state.clear()
                return

            # Get user info
            me = await client.get_me()

            phone = f"+{me.phone}" if me.phone else account_data.get("phone", "")
            if phone and not phone.startswith("+"):
                phone = f"+{phone}"

            if not phone:
                await message.answer(
                    "❌ Не удалось определить номер телефона.",
                    reply_markup=get_main_menu_kb(),
                )
                await state.clear()
                return

            # Update account_data with fresh info from Telegram
            account_data["phone"] = phone
            account_data["telegram_id"] = me.id
            account_data["username"] = me.username
            account_data["first_name"] = me.first_name or ""
            account_data["last_name"] = me.last_name or ""
            account_data["is_premium"] = getattr(me, 'premium', False)

            # Get string session for storage (convert SQLite session if needed)
            if session_bytes and not session_string:
                # Export to StringSession
                session_string = StringSession.save(client.session)

        except SessionPasswordNeededError:
            # Need 2FA - check if we have it from files
            twofa_pass = account_data.get("twofa")

            if twofa_pass:
                try:
                    await client.sign_in(password=twofa_pass)
                    me = await client.get_me()

                    phone = f"+{me.phone}" if me.phone else account_data.get("phone", "")
                    if phone and not phone.startswith("+"):
                        phone = f"+{phone}"

                    account_data["phone"] = phone
                    account_data["telegram_id"] = me.id
                    account_data["username"] = me.username
                    account_data["first_name"] = me.first_name or ""
                    account_data["last_name"] = me.last_name or ""
                    account_data["is_premium"] = getattr(me, 'premium', False)

                    if session_bytes and not session_string:
                        session_string = StringSession.save(client.session)

                except Exception as e:
                    await message.answer(
                        f"❌ Неверный 2FA пароль из архива: {e}",
                        reply_markup=get_main_menu_kb(),
                    )
                    await state.clear()
                    return
            else:
                # No 2FA password - ask user
                await state.update_data(
                    zip_account_data=account_data,
                    zip_session_string=session_string,
                    zip_session_bytes=session_bytes,
                    zip_is_tdata=is_tdata,
                    zip_temp_dir=temp_dir,
                )
                await state.set_state(AccountStates.waiting_zip_2fa)

                await message.answer(
                    "🔐 <b>Требуется 2FA пароль</b>\n\n"
                    "Аккаунт защищён двухфакторной аутентификацией.\n"
                    "В архиве не найден файл с паролем.\n\n"
                    "Введите 2FA пароль:",
                    reply_markup=get_cancel_kb(),
                )
                # Don't cleanup temp_dir yet - we need it for 2FA
                temp_dir = None
                return

        except AuthKeyDuplicatedError:
            await message.answer(
                "❌ <b>Сессия уже используется!</b>\n\n"
                "Эта сессия активна на другом устройстве/IP.\n"
                "Telegram заблокировал параллельное использование.\n\n"
                "Варианты:\n"
                "• Закройте Telegram на другом устройстве\n"
                "• Подождите несколько минут\n"
                "• Используйте другую сессию",
                reply_markup=get_main_menu_kb(),
            )
            await state.clear()
            return

        except PhoneNumberBannedError:
            await message.answer(
                "❌ <b>Аккаунт заблокирован!</b>\n\n"
                "Номер телефона забанен в Telegram.",
                reply_markup=get_main_menu_kb(),
            )
            await state.clear()
            return

        except Exception as e:
            await message.answer(
                f"❌ Ошибка проверки сессии: {e}",
                reply_markup=get_main_menu_kb(),
            )
            await state.clear()
            return

        # Check if account exists
        repo = PostgresAccountRepository(session)
        existing = await repo.get_by_phone(phone)

        if existing:
            await message.answer(
                f"❌ Аккаунт с номером {phone} уже существует.",
                reply_markup=get_main_menu_kb(),
            )
            await state.clear()
            return

        # Encrypt session data
        from src.utils.crypto import get_session_encryption
        encryption = get_session_encryption()

        if session_string:
            encrypted = encryption.encrypt(session_string.encode('utf-8'))
        else:
            encrypted = encryption.encrypt(session_bytes)

        # Create account with proxy assigned
        service = get_account_service(session)
        account_source = AccountSource.TDATA if is_tdata else AccountSource.JSON_SESSION
        account = await service.create_account(
            phone=phone,
            session_data=encrypted,
            source=account_source,
        )

        # Update with validated data
        account.telegram_id = account_data.get("telegram_id")
        account.username = account_data.get("username")
        account.first_name = account_data.get("first_name", "")
        account.last_name = account_data.get("last_name", "")
        account.proxy_id = proxy.id  # Assign proxy!

        await service.account_repo.save(account)

        await state.clear()

        # Build success message
        twofa_info = ""
        if account_data.get("twofa"):
            twofa_info = f"\n🔐 2FA: <code>{account_data['twofa']}</code>"

        premium_status = "⭐ Premium" if account_data.get("is_premium") else ""
        spamblock = account_data.get("spamblock", "")
        spamblock_info = f"\n⚠️ Спамблок: {spamblock}" if spamblock and spamblock != "free" else ""

        source_type = "tdata" if is_tdata else "session"

        await message.answer(
            f"✅ <b>Аккаунт добавлен из {source_type}!</b>\n\n"
            f"👤 {account.first_name} {account.last_name} {premium_status}\n"
            f"📱 {phone}\n"
            f"🆔 @{account.username or '—'}\n"
            f"🔢 ID: {account.telegram_id or '—'}"
            f"{twofa_info}"
            f"{spamblock_info}\n\n"
            f"🌐 Прокси: <code>{proxy.host}:{proxy.port}</code>\n"
            f"Статус: ✅ Проверен и готов к работе",
            reply_markup=get_main_menu_kb(),
        )

    except zipfile.BadZipFile:
        await message.answer(
            "❌ Некорректный ZIP-архив.",
            reply_markup=get_main_menu_kb(),
        )
        await state.clear()
    except Exception as e:
        import traceback
        traceback.print_exc()
        await message.answer(
            f"❌ Ошибка обработки архива: {e}",
            reply_markup=get_main_menu_kb(),
        )
        await state.clear()
    finally:
        # Disconnect client
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass
        # Cleanup temp directory
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


@router.message(AccountStates.waiting_zip_2fa)
async def receive_zip_2fa(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Receive 2FA password for ZIP session validation."""
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from src.config import get_settings
    from src.infrastructure.database.repositories import PostgresProxyRepository
    import python_socks
    import shutil
    import os

    twofa_pass = message.text.strip()

    state_data = await state.get_data()
    account_data = state_data.get("zip_account_data", {})
    session_string = state_data.get("zip_session_string")
    session_bytes = state_data.get("zip_session_bytes")
    is_tdata = state_data.get("zip_is_tdata", False)
    temp_dir = state_data.get("zip_temp_dir")
    proxy_id = state_data.get("proxy_id")

    # Get proxy
    proxy_repo = PostgresProxyRepository(session)
    proxy = await proxy_repo.get_by_id(UUID(proxy_id))

    if not proxy:
        await message.answer(
            "❌ Прокси не найден. Начните заново.",
            reply_markup=get_main_menu_kb(),
        )
        await state.clear()
        return

    status_msg = await message.answer("⏳ Проверяю 2FA пароль...")

    client = None
    try:
        proxy_dict = {
            'proxy_type': python_socks.ProxyType.SOCKS5,
            'addr': proxy.host,
            'port': proxy.port,
            'username': proxy.username,
            'password': proxy.password,
            'rdns': True,
        }

        settings = get_settings()

        if session_string:
            client = TelegramClient(
                StringSession(session_string),
                settings.telegram.api_id,
                settings.telegram.api_hash.get_secret_value(),
                proxy=proxy_dict,
            )
        elif session_bytes and temp_dir:
            temp_session_path = os.path.join(temp_dir, "temp_session")
            with open(temp_session_path + ".session", 'wb') as f:
                f.write(session_bytes)

            # Try converting to StringSession
            converted_string = await _convert_session_to_telethon_string(temp_session_path + ".session")
            if converted_string:
                session_string = converted_string
                client = TelegramClient(
                    StringSession(session_string),
                    settings.telegram.api_id,
                    settings.telegram.api_hash.get_secret_value(),
                    proxy=proxy_dict,
                )
            else:
                client = TelegramClient(
                    temp_session_path,
                    settings.telegram.api_id,
                    settings.telegram.api_hash.get_secret_value(),
                    proxy=proxy_dict,
                )
        else:
            await message.answer(
                "❌ Данные сессии утеряны. Начните заново.",
                reply_markup=get_main_menu_kb(),
            )
            await state.clear()
            return

        import asyncio
        try:
            await asyncio.wait_for(client.connect(), timeout=30)
        except asyncio.TimeoutError:
            await message.answer(
                "❌ Таймаут подключения к Telegram через прокси.",
                reply_markup=get_main_menu_kb(),
            )
            await state.clear()
            return

        try:
            await client.sign_in(password=twofa_pass)
        except Exception as e:
            await message.answer(
                f"❌ Неверный 2FA пароль: {e}\n\n"
                "Попробуйте ещё раз или /cancel для отмены.",
            )
            return

        # Get user info
        me = await client.get_me()

        phone = f"+{me.phone}" if me.phone else account_data.get("phone", "")
        if phone and not phone.startswith("+"):
            phone = f"+{phone}"

        account_data["phone"] = phone
        account_data["telegram_id"] = me.id
        account_data["username"] = me.username
        account_data["first_name"] = me.first_name or ""
        account_data["last_name"] = me.last_name or ""
        account_data["is_premium"] = getattr(me, 'premium', False)
        account_data["twofa"] = twofa_pass

        # Get string session
        if session_bytes and not session_string:
            session_string = StringSession.save(client.session)

        # Check if account exists
        repo = PostgresAccountRepository(session)
        existing = await repo.get_by_phone(phone)

        if existing:
            await message.answer(
                f"❌ Аккаунт с номером {phone} уже существует.",
                reply_markup=get_main_menu_kb(),
            )
            await state.clear()
            return

        # Encrypt session data
        from src.utils.crypto import get_session_encryption
        encryption = get_session_encryption()

        if session_string:
            encrypted = encryption.encrypt(session_string.encode('utf-8'))
        else:
            encrypted = encryption.encrypt(session_bytes)

        # Create account
        service = get_account_service(session)
        account_source = AccountSource.TDATA if is_tdata else AccountSource.JSON_SESSION
        account = await service.create_account(
            phone=phone,
            session_data=encrypted,
            source=account_source,
        )

        account.telegram_id = account_data.get("telegram_id")
        account.username = account_data.get("username")
        account.first_name = account_data.get("first_name", "")
        account.last_name = account_data.get("last_name", "")
        account.proxy_id = proxy.id

        await service.account_repo.save(account)

        await state.clear()

        premium_status = "⭐ Premium" if account_data.get("is_premium") else ""
        source_type = "tdata" if is_tdata else "session"

        await message.answer(
            f"✅ <b>Аккаунт добавлен из {source_type}!</b>\n\n"
            f"👤 {account.first_name} {account.last_name} {premium_status}\n"
            f"📱 {phone}\n"
            f"🆔 @{account.username or '—'}\n"
            f"🔢 ID: {account.telegram_id or '—'}\n"
            f"🔐 2FA: сохранён\n\n"
            f"🌐 Прокси: <code>{proxy.host}:{proxy.port}</code>\n"
            f"Статус: ✅ Проверен и готов к работе",
            reply_markup=get_main_menu_kb(),
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        await message.answer(
            f"❌ Ошибка: {e}",
            reply_markup=get_main_menu_kb(),
        )
        await state.clear()
    finally:
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


def _check_is_tdata(extract_dir: str) -> bool:
    """Check if extracted files contain tdata structure."""
    import os

    # Look for tdata folder or key_datas file
    for root, dirs, files in os.walk(extract_dir):
        # Check for key_datas file (marker of tdata)
        if 'key_datas' in files:
            return True
        # Check for tdata folder name
        if 'tdata' in dirs:
            return True
        # Check for folders starting with D877F (data folders)
        for d in dirs:
            if len(d) == 16 and d[0].isupper():
                # Likely a tdata data folder
                key_datas_path = os.path.join(root, 'key_datas')
                if os.path.exists(key_datas_path):
                    return True

    return False


def _find_tdata_folder(extract_dir: str) -> str | None:
    """Find the tdata folder in extracted files."""
    import os

    # Direct tdata folder
    tdata_path = os.path.join(extract_dir, 'tdata')
    if os.path.isdir(tdata_path):
        return tdata_path

    # Look in subdirectories
    for root, dirs, files in os.walk(extract_dir):
        if 'tdata' in dirs:
            return os.path.join(root, 'tdata')
        # Check if current dir is tdata by presence of key_datas
        if 'key_datas' in files:
            return root

    return None


def _create_string_session(dc_id: int, auth_key: bytes) -> str:
    """Create Telethon StringSession from auth_key manually."""
    import struct
    import base64
    import ipaddress

    # DC IPs (Telegram production servers)
    dc_ips = {
        1: '149.154.175.53',
        2: '149.154.167.51',
        3: '149.154.175.100',
        4: '149.154.167.91',
        5: '91.108.56.130',
    }

    ip = dc_ips.get(dc_id, dc_ips[2])
    port = 443

    # Pack session data for Telethon StringSession format
    # Format: >B{ip_len}sH256s where ip_len is 4 for IPv4, 16 for IPv6
    ip_bytes = ipaddress.ip_address(ip).packed
    ip_len = len(ip_bytes)

    # Telethon uses format string with variable IP length
    struct_format = f'>B{ip_len}sH256s'

    session_data = struct.pack(
        struct_format,
        dc_id,
        ip_bytes,
        port,
        auth_key
    )

    # Telethon StringSession format: '1' + base64(session_data)
    return '1' + base64.urlsafe_b64encode(session_data).decode('ascii')


async def _convert_tdata_to_session(extract_dir: str) -> dict | None:
    """
    Convert tdata to Telethon session using opentele.

    Returns dict with session_string and account metadata.
    """
    import os
    import json

    result = {
        "phone": None,
        "telegram_id": None,
        "username": None,
        "first_name": "",
        "last_name": "",
        "twofa": None,
        "is_premium": False,
        "spamblock": None,
        "session_string": None,
        "session_bytes": None,
    }

    try:
        # Find tdata folder
        tdata_path = _find_tdata_folder(extract_dir)
        logger.info(f"tdata_path found: {tdata_path}")
        if not tdata_path:
            logger.warning(f"No tdata folder found in {extract_dir}")
            return None

        # Parse metadata from JSON and 2FA files (also search parent dir)
        await _parse_metadata_files(tdata_path, result)
        await _parse_metadata_files(extract_dir, result)

        # Convert tdata to Telethon session using opentele
        try:
            from opentele.td import TDesktop
            logger.info("opentele imported successfully")

            # Load tdata
            logger.info(f"Loading TDesktop from {tdata_path}")
            tdesk = TDesktop(tdata_path)

            logger.info(f"TDesktop isLoaded: {tdesk.isLoaded()}")
            if not tdesk.isLoaded():
                logger.warning("TDesktop is not loaded")
                return None

            # Get first account
            logger.info(f"TDesktop accounts count: {len(tdesk.accounts) if tdesk.accounts else 0}")
            if not tdesk.accounts:
                logger.warning("No accounts in tdata")
                return None

            account = tdesk.accounts[0]

            # Get telegram_id from tdata
            if account.UserId:
                result["telegram_id"] = account.UserId

            # Create session string manually from auth_key
            # (bypasses buggy opentele ToTelethon method)
            if hasattr(account, 'authKey') and hasattr(account.authKey, 'key'):
                auth_key_bytes = account.authKey.key
                dc_id = account.MainDcId or 2

                result["session_string"] = _create_string_session(dc_id, auth_key_bytes)

        except ImportError as e:
            # opentele not installed
            logger.error(f"opentele not installed: {e}")
            return None
        except Exception as e:
            logger.exception(f"Error converting tdata to session: {e}")
            return None

        # We need at least session_string to proceed
        # Phone can be extracted later when connecting
        if result["session_string"]:
            # If no phone found in metadata, use telegram_id as placeholder
            if not result["phone"] and result["telegram_id"]:
                result["phone"] = str(result["telegram_id"])
            return result

        return None

    except Exception as e:
        logger.exception(f"Error in _convert_tdata_to_session: {e}")
        return None


async def _parse_session_files(extract_dir: str) -> dict | None:
    """Parse regular .session and .json files."""
    import os
    import json
    import sqlite3

    result = {
        "phone": None,
        "telegram_id": None,
        "username": None,
        "first_name": "",
        "last_name": "",
        "twofa": None,
        "is_premium": False,
        "spamblock": None,
        "session_string": None,
        "session_bytes": None,
    }

    session_file = None
    json_file = None

    # Find .session and .json files
    for root, dirs, files in os.walk(extract_dir):
        for f in files:
            if f.endswith('.session') and not f.startswith('__'):
                session_file = os.path.join(root, f)
            elif f.endswith('.json') and not f.startswith('__'):
                json_file = os.path.join(root, f)

    # Parse JSON metadata
    if json_file:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            result["phone"] = str(data.get("phone", ""))
            result["telegram_id"] = data.get("id")
            result["username"] = data.get("username")
            result["first_name"] = data.get("first_name", "")
            result["last_name"] = data.get("last_name", "")
            result["is_premium"] = data.get("is_premium", False)
            result["spamblock"] = data.get("spamblock")

            if data.get("twoFA"):
                result["twofa"] = str(data.get("twoFA"))
        except Exception:
            pass

    # Read and convert session file
    if session_file:
        try:
            # Try to detect session type and convert to Telethon StringSession
            session_string = await _convert_session_to_telethon_string(session_file)
            if session_string:
                result["session_string"] = session_string
            else:
                # Fallback to raw bytes (Telethon SQLite)
                with open(session_file, 'rb') as f:
                    result["session_bytes"] = f.read()

            # Extract phone from filename if not in JSON
            if not result["phone"]:
                base_name = os.path.basename(session_file)
                phone_from_name = base_name.replace('.session', '')
                if phone_from_name.isdigit():
                    result["phone"] = phone_from_name
        except Exception:
            pass

    # Look for Password2FA.txt
    await _parse_metadata_files(extract_dir, result)

    if (result["session_bytes"] or result["session_string"]) and result["phone"]:
        return result

    return None


async def _convert_session_to_telethon_string(session_file: str) -> str | None:
    """
    Convert session file to Telethon StringSession.
    Handles both Telethon SQLite and Pyrogram sessions.
    """
    import sqlite3

    try:
        conn = sqlite3.connect(session_file)
        cursor = conn.cursor()

        # Check table structure to detect session type
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]

        if 'sessions' in tables:
            # Telethon SQLite session
            cursor.execute("SELECT dc_id, server_address, port, auth_key FROM sessions WHERE dc_id != 0 LIMIT 1")
            row = cursor.fetchone()

            if row:
                dc_id, server_address, port, auth_key = row

                if auth_key and len(auth_key) == 256:
                    conn.close()
                    return _create_string_session(dc_id, auth_key)

        elif 'peers' in tables or 'version' in tables:
            # Might be Pyrogram session - try converter
            conn.close()
            try:
                from telegram_session_converter import PyrogramSession
                pyrogram_session = PyrogramSession.from_file(session_file)
                return pyrogram_session.to_telethon_string()
            except Exception:
                pass

        conn.close()
    except Exception:
        pass

    return None


async def _parse_metadata_files(search_dir: str, result: dict) -> None:
    """Parse Password2FA.txt, 2FA.txt and other metadata files."""
    import os
    import json

    for root, dirs, files in os.walk(search_dir):
        for f in files:
            filepath = os.path.join(root, f)
            f_lower = f.lower()

            # 2FA password files (various naming conventions)
            if f_lower in ('password2fa.txt', '2fa.txt', 'twofa.txt'):
                try:
                    with open(filepath, 'r', encoding='utf-8') as file:
                        twofa = file.read().strip()
                        if twofa and not result["twofa"]:
                            result["twofa"] = twofa
                            logger.info(f"Found 2FA password in {f}")
                except Exception:
                    pass

            # JSON with account data
            elif f.endswith('.json') and not f.startswith('__'):
                try:
                    with open(filepath, 'r', encoding='utf-8') as file:
                        data = json.load(file)

                    if not result["phone"] and data.get("phone"):
                        result["phone"] = str(data.get("phone", ""))
                    if not result["telegram_id"] and data.get("id"):
                        result["telegram_id"] = data.get("id")
                    if not result["username"] and data.get("username"):
                        result["username"] = data.get("username")
                    if not result["first_name"] and data.get("first_name"):
                        result["first_name"] = data.get("first_name", "")
                    if not result["last_name"] and data.get("last_name"):
                        result["last_name"] = data.get("last_name", "")
                    if data.get("is_premium"):
                        result["is_premium"] = data.get("is_premium", False)
                    if data.get("spamblock"):
                        result["spamblock"] = data.get("spamblock")
                    if data.get("twoFA") and not result["twofa"]:
                        result["twofa"] = str(data.get("twoFA"))
                except Exception:
                    pass


@router.callback_query(F.data == "accounts:add:session")
async def add_account_session(callback: CallbackQuery, state: FSMContext) -> None:
    """Start session file upload."""
    await state.set_state(AccountStates.waiting_phone_for_session)
    
    await callback.message.edit_text(
        "📁 <b>Загрузка session-файла</b>\n\n"
        "Сначала введите номер телефона аккаунта\n"
        "(в международном формате, например: +79001234567):",
    )
    await callback.message.answer(
        "Ожидаю номер телефона...",
        reply_markup=get_cancel_kb(),
    )
    await callback.answer()


@router.message(AccountStates.waiting_phone_for_session)
async def receive_phone_for_session(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Receive phone number for session upload."""
    phone = message.text.strip()
    
    # Basic validation
    if not phone.startswith("+") or len(phone) < 10:
        await message.answer(
            "❌ Неверный формат. Введите номер в международном формате (+79001234567):",
        )
        return
    
    # Check if exists
    repo = PostgresAccountRepository(session)
    existing = await repo.get_by_phone(phone)
    
    if existing:
        await message.answer(
            "❌ Аккаунт с этим номером уже существует.",
            reply_markup=get_main_menu_kb(),
        )
        await state.clear()
        return
    
    await state.update_data(phone=phone)
    await state.set_state(AccountStates.waiting_session_file)
    
    await message.answer(
        f"📱 Номер: <code>{phone}</code>\n\n"
        "Теперь отправьте .session файл от Telethon:",
    )


@router.message(AccountStates.waiting_session_file, F.document)
async def receive_session_file(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Receive and process session file."""
    doc = message.document
    
    if not doc.file_name.endswith(".session"):
        await message.answer("❌ Отправьте файл с расширением .session")
        return
    
    data = await state.get_data()
    phone = data.get("phone")
    
    # Download file
    file = await message.bot.download(doc)
    session_bytes = file.read()
    
    # Encrypt session
    from src.utils.crypto import get_session_encryption
    encryption = get_session_encryption()
    encrypted = encryption.encrypt(session_bytes)
    
    # Create account
    service = get_account_service(session)

    try:
        account = await service.create_account(
            phone=phone,
            session_data=encrypted,
            source=AccountSource.JSON_SESSION,
        )

        await state.clear()
        await message.answer(
            f"✅ <b>Аккаунт добавлен!</b>\n\n"
            f"Телефон: {phone}\n"
            f"ID: <code>{account.id}</code>\n\n"
            f"Статус: 🔵 Готов к работе\n\n"
            f"Не забудьте назначить прокси перед активацией.",
            reply_markup=get_main_menu_kb(),
        )

    except Exception as e:
        await message.answer(
            f"❌ Ошибка создания: {e}",
            reply_markup=get_main_menu_kb(),
        )
        await state.clear()


# =============================================================================
# Phone Authentication (Interactive Login)
# =============================================================================

@router.callback_query(F.data == "accounts:add:phone")
async def add_account_phone_start(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Start phone authentication flow - first select proxy group."""
    from src.infrastructure.database.repositories import ProxyGroupRepository, PostgresProxyRepository

    # Check if there are proxy groups
    group_repo = ProxyGroupRepository(session)
    groups = await group_repo.get_all()

    kb = InlineKeyboardBuilder()

    if groups:
        # Show proxy groups first
        for group in groups:
            available = await group_repo.count_available_proxies_in_group(group.id)
            if available > 0:
                country = f" [{group.country_code}]" if group.country_code else ""
                kb.row(InlineKeyboardButton(
                    text=f"📁 {group.name}{country} ({available} своб.)",
                    callback_data=f"accounts:add:phone:group:{group.id}",
                ))

    # Also offer to select from all proxies
    proxy_repo = PostgresProxyRepository(session)
    all_available = await proxy_repo.count_available()

    if all_available > 0:
        kb.row(InlineKeyboardButton(
            text=f"🌐 Все прокси ({all_available} своб.)",
            callback_data="accounts:add:phone:all_proxies",
        ))

    kb.row(InlineKeyboardButton(
        text="◀️ Назад",
        callback_data="accounts:add",
    ))

    if not groups and all_available == 0:
        await callback.message.edit_text(
            "📱 <b>Авторизация по номеру</b>\n\n"
            "⚠️ <b>Нет доступных прокси!</b>\n\n"
            "Для авторизации аккаунта нужен прокси.\n"
            "Сначала добавьте прокси в разделе 🌐 Прокси.",
            reply_markup=get_back_kb("accounts:menu"),
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "📱 <b>Авторизация по номеру</b>\n\n"
        "Шаг 1/4: <b>Выберите группу прокси</b>\n\n"
        "Прокси будет выбран из указанной группы.\n\n"
        "<i>Группы помогают организовать прокси по странам/типам</i>",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("accounts:add:phone:group:"))
async def add_account_phone_select_from_group(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Select proxy from a specific group for phone auth."""
    from src.infrastructure.database.repositories import ProxyGroupRepository

    group_id = UUID(callback.data.split(":")[4])

    group_repo = ProxyGroupRepository(session)
    group = await group_repo.get_by_id(group_id)

    if not group:
        await callback.answer("❌ Группа не найдена", show_alert=True)
        return

    proxies = await group_repo.get_available_proxies_in_group(group_id)

    if not proxies:
        await callback.answer("❌ В этой группе нет свободных прокси", show_alert=True)
        return

    # Save group to state
    await state.update_data(proxy_group_id=str(group_id), proxy_group_name=group.name)

    # Build proxy selection keyboard
    kb = InlineKeyboardBuilder()

    for proxy in proxies[:10]:  # Max 10 proxies
        latency = f" ({proxy.last_check_latency_ms}ms)" if proxy.last_check_latency_ms else ""
        kb.row(InlineKeyboardButton(
            text=f"🌐 {proxy.host}:{proxy.port}{latency}",
            callback_data=f"accounts:add:selectproxy:{proxy.id}",
        ))

    kb.row(InlineKeyboardButton(
        text="◀️ Назад",
        callback_data="accounts:add:phone",
    ))

    await callback.message.edit_text(
        f"📱 <b>Авторизация по номеру</b>\n\n"
        f"Шаг 2/4: <b>Выберите прокси</b>\n\n"
        f"📁 Группа: <b>{group.name}</b>\n\n"
        f"Доступно: {len(proxies)} прокси",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "accounts:add:phone:all_proxies")
async def add_account_phone_select_from_all(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Select proxy from all available proxies for phone auth."""
    from src.infrastructure.database.repositories import PostgresProxyRepository

    proxy_repo = PostgresProxyRepository(session)
    proxies = await proxy_repo.list_available()

    if not proxies:
        await callback.answer("❌ Нет свободных прокси", show_alert=True)
        return

    # Clear group from state (selecting from all)
    await state.update_data(proxy_group_id=None, proxy_group_name=None)

    # Build proxy selection keyboard
    kb = InlineKeyboardBuilder()

    for proxy in proxies[:10]:  # Max 10 proxies
        latency = f" ({proxy.last_check_latency_ms}ms)" if proxy.last_check_latency_ms else ""
        kb.row(InlineKeyboardButton(
            text=f"🌐 {proxy.host}:{proxy.port}{latency}",
            callback_data=f"accounts:add:selectproxy:{proxy.id}",
        ))

    kb.row(InlineKeyboardButton(
        text="◀️ Назад",
        callback_data="accounts:add:phone",
    ))

    await callback.message.edit_text(
        "📱 <b>Авторизация по номеру</b>\n\n"
        "Шаг 2/4: <b>Выберите прокси</b>\n\n"
        f"Доступно: {len(proxies)} прокси",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("accounts:add:selectproxy:"))
async def add_account_select_proxy(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Proxy selected, now ask for phone."""
    from src.infrastructure.database.repositories import PostgresProxyRepository

    proxy_id = UUID(callback.data.split(":")[3])

    proxy_repo = PostgresProxyRepository(session)
    proxy = await proxy_repo.get_by_id(proxy_id)

    if not proxy:
        await callback.answer("❌ Прокси не найден", show_alert=True)
        return

    # Check if proxy is still available (not assigned to another account)
    if await proxy_repo.is_assigned(proxy_id):
        await callback.answer("❌ Этот прокси уже занят другим аккаунтом", show_alert=True)
        # Refresh proxy list
        await add_account_phone_start(callback, session, state)
        return

    # Save proxy to state
    await state.update_data(proxy_id=str(proxy_id), proxy_host=proxy.host, proxy_port=proxy.port)
    await state.set_state(AccountStates.waiting_phone)

    # Get group name if selected from a group
    state_data = await state.get_data()
    group_name = state_data.get("proxy_group_name")
    group_info = f"\n📁 Группа: <b>{group_name}</b>" if group_name else ""

    await callback.message.edit_text(
        f"📱 <b>Авторизация по номеру</b>\n\n"
        f"Шаг 3/4: <b>Введите номер телефона</b>\n\n"
        f"🌐 Прокси: <code>{proxy.host}:{proxy.port}</code>{group_info}\n\n"
        f"Введите номер в международном формате:\n"
        f"<code>+79001234567</code>\n\n"
        f"⚠️ На этот номер придёт код подтверждения.",
    )
    await callback.message.answer(
        "Ожидаю номер телефона...",
        reply_markup=get_cancel_kb(),
    )
    await callback.answer()


@router.message(AccountStates.waiting_phone)
async def receive_phone(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Receive phone and send code via proxy."""
    from telethon import TelegramClient
    from telethon.errors import FloodWaitError, PhoneNumberBannedError
    from src.config import get_settings
    from src.infrastructure.database.repositories import PostgresProxyRepository
    import python_socks
    
    phone = message.text.strip()
    
    # Validate
    if not phone.startswith("+") or len(phone) < 10:
        await message.answer(
            "❌ Неверный формат. Используйте +79001234567:",
        )
        return
    
    # Check existing
    repo = PostgresAccountRepository(session)
    existing = await repo.get_by_phone(phone)
    
    if existing:
        await message.answer(
            "❌ Аккаунт с этим номером уже существует.",
            reply_markup=get_main_menu_kb(),
        )
        await state.clear()
        return
    
    settings = get_settings()
    data = await state.get_data()
    
    # Get proxy from state
    proxy_id = data.get("proxy_id")
    proxy_config = None
    
    if proxy_id:
        proxy_repo = PostgresProxyRepository(session)
        proxy = await proxy_repo.get_by_id(UUID(proxy_id))
        
        if proxy:
            # Build proxy config for Telethon
            proxy_type_map = {
                "socks5": python_socks.ProxyType.SOCKS5,
                "socks4": python_socks.ProxyType.SOCKS4,
                "http": python_socks.ProxyType.HTTP,
                "https": python_socks.ProxyType.HTTP,
            }
            proxy_config = {
                "proxy_type": proxy_type_map.get(proxy.proxy_type.value, python_socks.ProxyType.SOCKS5),
                "addr": proxy.host,
                "port": proxy.port,
                "username": proxy.username,
                "password": proxy.password,
                "rdns": True,
            }
    
    await message.answer("⏳ Подключаюсь к Telegram через прокси...")
    
    try:
        from telethon.sessions import StringSession
        
        # Create client with StringSession (no files needed)
        client = TelegramClient(
            StringSession(),
            api_id=settings.telegram.api_id,
            api_hash=settings.telegram.api_hash.get_secret_value(),
            proxy=proxy_config,
        )
        
        await client.connect()
        
        # Send code request
        sent = await client.send_code_request(phone)
        
        # Save session string for next step
        session_string = client.session.save()
        
        # Save state data
        await state.update_data(
            phone=phone,
            session_string=session_string,
            phone_code_hash=sent.phone_code_hash,
        )
        
        await client.disconnect()
        
        await state.set_state(AccountStates.waiting_code)
        
        proxy_info = f"🌐 {data.get('proxy_host')}:{data.get('proxy_port')}" if proxy_id else "напрямую"
        
        await message.answer(
            f"📨 <b>Код отправлен!</b>\n\n"
            f"Подключение: {proxy_info}\n\n"
            f"Проверьте Telegram на номере {phone}\n"
            f"и введите полученный код:",
        )
        
    except FloodWaitError as e:
        await message.answer(
            f"❌ Слишком много попыток.\n"
            f"Подождите {e.seconds} секунд.",
            reply_markup=get_main_menu_kb(),
        )
        await state.clear()
        
    except PhoneNumberBannedError:
        await message.answer(
            "❌ Этот номер заблокирован в Telegram.",
            reply_markup=get_main_menu_kb(),
        )
        await state.clear()
        
    except Exception as e:
        await message.answer(
            f"❌ Ошибка: {e}",
            reply_markup=get_main_menu_kb(),
        )
        await state.clear()


@router.message(AccountStates.waiting_code)
async def receive_code(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Receive verification code."""
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import (
        PhoneCodeInvalidError,
        PhoneCodeExpiredError,
        SessionPasswordNeededError,
    )
    from src.config import get_settings
    from src.infrastructure.database.repositories import PostgresProxyRepository
    import python_socks
    
    code = message.text.strip().replace(" ", "").replace("-", "")
    
    if not code.isdigit() or len(code) < 4:
        await message.answer("❌ Введите корректный код (только цифры):")
        return
    
    data = await state.get_data()
    phone = data.get("phone")
    session_string = data.get("session_string")
    phone_code_hash = data.get("phone_code_hash")
    proxy_id = data.get("proxy_id")
    
    settings = get_settings()
    
    # Get proxy config
    proxy_config = None
    if proxy_id:
        proxy_repo = PostgresProxyRepository(session)
        proxy = await proxy_repo.get_by_id(UUID(proxy_id))
        
        if proxy:
            proxy_type_map = {
                "socks5": python_socks.ProxyType.SOCKS5,
                "socks4": python_socks.ProxyType.SOCKS4,
                "http": python_socks.ProxyType.HTTP,
                "https": python_socks.ProxyType.HTTP,
            }
            proxy_config = {
                "proxy_type": proxy_type_map.get(proxy.proxy_type.value, python_socks.ProxyType.SOCKS5),
                "addr": proxy.host,
                "port": proxy.port,
                "username": proxy.username,
                "password": proxy.password,
                "rdns": True,
            }
    
    await message.answer("⏳ Проверяю код...")
    
    try:
        # Use StringSession from previous step
        client = TelegramClient(
            StringSession(session_string),
            api_id=settings.telegram.api_id,
            api_hash=settings.telegram.api_hash.get_secret_value(),
            proxy=proxy_config,
        )
        
        await client.connect()
        
        # Sign in with code
        await client.sign_in(
            phone=phone,
            code=code,
            phone_code_hash=phone_code_hash,
        )
        
        # Get account info
        me = await client.get_me()
        
        # Export final session string
        final_session_string = client.session.save()
        await client.disconnect()
        
        # Encrypt session string (encode to bytes first)
        from src.utils.crypto import get_session_encryption
        encryption = get_session_encryption()
        encrypted = encryption.encrypt(final_session_string.encode('utf-8'))

        service = get_account_service(session)
        account = await service.create_account(
            phone=phone,
            session_data=encrypted,
            source=AccountSource.PHONE,
        )

        # Update with Telegram info
        account.telegram_id = me.id
        account.username = me.username
        account.first_name = me.first_name or ""
        account.last_name = me.last_name or ""
        
        # Assign proxy
        if proxy_id:
            account.proxy_id = UUID(proxy_id)
        
        await service.account_repo.save(account)
        
        await state.clear()
        
        proxy_info = f"🌐 {data.get('proxy_host')}:{data.get('proxy_port')}" if proxy_id else "—"
        
        await message.answer(
            f"✅ <b>Аккаунт успешно авторизован!</b>\n\n"
            f"👤 {me.first_name} {me.last_name or ''}\n"
            f"📱 {phone}\n"
            f"🆔 @{me.username or '—'}\n"
            f"🌐 Прокси: {proxy_info}\n\n"
            f"Статус: 🔵 Готов к работе",
            reply_markup=get_main_menu_kb(),
        )
        
    except PhoneCodeInvalidError:
        await message.answer("❌ Неверный код. Попробуйте ещё раз:")
        
    except PhoneCodeExpiredError:
        await message.answer(
            "❌ Код истёк. Начните заново.",
            reply_markup=get_main_menu_kb(),
        )
        await state.clear()
        
    except SessionPasswordNeededError:
        # 2FA enabled - save session for next step
        current_session_string = client.session.save()
        await client.disconnect()
        
        await state.update_data(session_string=current_session_string)
        await state.set_state(AccountStates.waiting_2fa)
        await message.answer(
            "🔐 <b>Двухфакторная аутентификация</b>\n\n"
            "На этом аккаунте включена 2FA.\n"
            "Введите пароль:"
        )
        
    except Exception as e:
        await message.answer(
            f"❌ Ошибка авторизации: {e}",
            reply_markup=get_main_menu_kb(),
        )
        await state.clear()


@router.message(AccountStates.waiting_2fa)
async def receive_2fa_password(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Receive 2FA password."""
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import PasswordHashInvalidError
    from src.config import get_settings
    from src.infrastructure.database.repositories import PostgresProxyRepository
    import python_socks
    
    password = message.text.strip()
    
    if len(password) < 1:
        await message.answer("❌ Введите пароль:")
        return
    
    data = await state.get_data()
    phone = data.get("phone")
    session_string = data.get("session_string")
    proxy_id = data.get("proxy_id")
    
    settings = get_settings()
    
    # Get proxy config
    proxy_config = None
    if proxy_id:
        proxy_repo = PostgresProxyRepository(session)
        proxy = await proxy_repo.get_by_id(UUID(proxy_id))
        
        if proxy:
            proxy_type_map = {
                "socks5": python_socks.ProxyType.SOCKS5,
                "socks4": python_socks.ProxyType.SOCKS4,
                "http": python_socks.ProxyType.HTTP,
                "https": python_socks.ProxyType.HTTP,
            }
            proxy_config = {
                "proxy_type": proxy_type_map.get(proxy.proxy_type.value, python_socks.ProxyType.SOCKS5),
                "addr": proxy.host,
                "port": proxy.port,
                "username": proxy.username,
                "password": proxy.password,
                "rdns": True,
            }
    
    await message.answer("⏳ Проверяю пароль...")
    
    try:
        client = TelegramClient(
            StringSession(session_string),
            api_id=settings.telegram.api_id,
            api_hash=settings.telegram.api_hash.get_secret_value(),
            proxy=proxy_config,
        )
        
        await client.connect()
        
        # Sign in with password
        await client.sign_in(password=password)
        
        # Get account info
        me = await client.get_me()
        
        # Export final session string
        final_session_string = client.session.save()
        await client.disconnect()
        
        # Encrypt session string
        from src.utils.crypto import get_session_encryption
        encryption = get_session_encryption()
        encrypted = encryption.encrypt(final_session_string.encode('utf-8'))

        service = get_account_service(session)
        account = await service.create_account(
            phone=phone,
            session_data=encrypted,
            source=AccountSource.PHONE,
        )

        # Update with Telegram info
        account.telegram_id = me.id
        account.username = me.username
        account.first_name = me.first_name or ""
        account.last_name = me.last_name or ""

        # Assign proxy
        if proxy_id:
            account.proxy_id = UUID(proxy_id)

        await service.account_repo.save(account)

        await state.clear()

        proxy_info = f"🌐 {data.get('proxy_host')}:{data.get('proxy_port')}" if proxy_id else "—"

        await message.answer(
            f"✅ <b>Аккаунт успешно авторизован!</b>\n\n"
            f"👤 {me.first_name} {me.last_name or ''}\n"
            f"📱 {phone}\n"
            f"🆔 @{me.username or '—'}\n"
            f"🌐 Прокси: {proxy_info}\n\n"
            f"Статус: 🔵 Готов к работе",
            reply_markup=get_main_menu_kb(),
        )
        
    except PasswordHashInvalidError:
        await message.answer("❌ Неверный пароль. Попробуйте ещё раз:")
        
    except Exception as e:
        await message.answer(
            f"❌ Ошибка: {e}",
            reply_markup=get_main_menu_kb(),
        )
        await state.clear()


# =============================================================================
# Account Settings (Limits)
# =============================================================================

@router.callback_query(F.data.startswith("account:settings:"))
async def account_settings(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show account settings menu."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    account_id = callback.data.split(":")[-1]

    repo = PostgresAccountRepository(session)
    account = await repo.get_by_id(UUID(account_id))

    if not account:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    text = (
        f"⚙️ <b>Настройки аккаунта</b>\n\n"
        f"📱 {account.phone}\n\n"
        f"<b>Лимиты:</b>\n"
        f"• Сообщений/час: {account.limits.max_messages_per_hour}\n"
        f"• Диалогов/день: {account.limits.max_new_conversations_per_day}\n"
        f"• Задержка: {account.limits.min_delay_between_messages}-{account.limits.max_delay_between_messages} сек\n"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📊 Изменить лимиты",
            callback_data=f"account:limits:{account_id}",
        )],
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"account:view:{account_id}",
        )],
    ])

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("account:limits:"))
async def account_limits_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start limits configuration."""
    account_id = callback.data.split(":")[-1]
    await state.update_data(account_id=account_id)
    await state.set_state(AccountStates.waiting_limits)
    
    await callback.message.edit_text(
        "📊 <b>Настройка лимитов</b>\n\n"
        "Введите лимиты через пробел:\n"
        "<code>сообщ/час диалогов/день мин_задержка макс_задержка</code>\n\n"
        "Например: <code>20 10 30 120</code>\n"
        "(20 сообщений в час, 10 диалогов в день, задержка 30-120 сек)",
    )
    await callback.message.answer("Ожидаю лимиты...", reply_markup=get_cancel_kb())
    await callback.answer()


@router.message(AccountStates.waiting_limits)
async def receive_limits(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Receive and save limits."""
    parts = message.text.strip().split()
    
    if len(parts) != 4:
        await message.answer(
            "❌ Введите 4 числа через пробел:\n"
            "<code>сообщ/час диалогов/день мин_задержка макс_задержка</code>",
        )
        return
    
    try:
        msg_per_hour = int(parts[0])
        conv_per_day = int(parts[1])
        min_delay = int(parts[2])
        max_delay = int(parts[3])
        
        if any(x < 1 for x in [msg_per_hour, conv_per_day, min_delay, max_delay]):
            raise ValueError("Values must be positive")
        
        if min_delay > max_delay:
            raise ValueError("Min delay > max delay")
            
    except ValueError as e:
        await message.answer(f"❌ Ошибка: {e}. Введите корректные числа.")
        return
    
    data = await state.get_data()
    account_id = UUID(data["account_id"])
    
    repo = PostgresAccountRepository(session)
    account = await repo.get_by_id(account_id)
    
    if account:
        account.limits.max_messages_per_hour = msg_per_hour
        account.limits.max_new_conversations_per_day = conv_per_day
        account.limits.min_delay_between_messages = min_delay
        account.limits.max_delay_between_messages = max_delay
        await repo.save(account)
    
    await state.clear()
    
    await message.answer(
        f"✅ <b>Лимиты обновлены!</b>\n\n"
        f"• Сообщений/час: {msg_per_hour}\n"
        f"• Диалогов/день: {conv_per_day}\n"
        f"• Задержка: {min_delay}-{max_delay} сек",
        reply_markup=get_main_menu_kb(),
    )


# =============================================================================
# Proxy Assignment
# =============================================================================

@router.callback_query(F.data.startswith("account:proxy:"))
async def account_proxy_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Show proxy assignment menu."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    account_id = callback.data.split(":")[-1]
    
    # Save to state for subsequent handlers
    await state.update_data(current_account_id=account_id)
    
    proxy_repo = PostgresProxyRepository(session)
    account_repo = PostgresAccountRepository(session)
    
    account = await account_repo.get_by_id(UUID(account_id))
    if not account:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return
    
    # Get available proxies
    available_proxies = await proxy_repo.list_available()
    
    # Current proxy info
    current_proxy = None
    if account.proxy_id:
        current_proxy = await proxy_repo.get_by_id(account.proxy_id)
    
    text = f"🌐 <b>Прокси для аккаунта</b>\n\n📱 {account.phone}\n\n"

    if current_proxy:
        text += f"<b>Текущий:</b> {current_proxy.host}:{current_proxy.port}\n\n"
    else:
        text += "<b>Текущий:</b> Не назначен\n\n"

    text += f"<b>Свободных прокси:</b> {len(available_proxies)}\n"
    text += "<i>(1 прокси = 1 аккаунт)</i>"
    
    # Build keyboard
    buttons = []
    
    for proxy in available_proxies[:8]:  # Max 8 proxies
        latency = f" ({proxy.last_check_latency_ms}ms)" if proxy.last_check_latency_ms else ""
        buttons.append([InlineKeyboardButton(
            text=f"🌐 {proxy.host}:{proxy.port}{latency}",
            callback_data=f"asp:{proxy.id}",  # Short: account set proxy
        )])
    
    if current_proxy:
        buttons.append([InlineKeyboardButton(
            text="❌ Отвязать прокси",
            callback_data=f"account:unsetproxy:{account_id}",
        )])
    
    buttons.append([InlineKeyboardButton(
        text="◀️ Назад",
        callback_data=f"account:view:{account_id}",
    )])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("asp:"))
async def account_set_proxy(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Assign proxy to account (short callback)."""
    from src.infrastructure.database.repositories import PostgresProxyRepository

    proxy_id = UUID(callback.data.split(":")[1])

    # Get account_id from state
    data = await state.get_data()
    account_id_str = data.get("current_account_id")

    if not account_id_str:
        await callback.answer("❌ Сессия истекла", show_alert=True)
        return

    account_id = UUID(account_id_str)

    # Check if proxy is already assigned to another account
    proxy_repo = PostgresProxyRepository(session)
    assigned_account = await proxy_repo.get_assigned_account_id(proxy_id)
    if assigned_account and assigned_account != account_id:
        await callback.answer("❌ Этот прокси уже занят другим аккаунтом", show_alert=True)
        return

    service = get_account_service(session)

    try:
        await service.assign_proxy(account_id, proxy_id)
        
        # Show success with back button
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        await callback.message.edit_text(
            "✅ <b>Прокси назначен!</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ К аккаунту", callback_data=f"account:view:{account_id}")]
            ])
        )
        await callback.answer()
        
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)[:100]}", show_alert=True)


@router.callback_query(F.data.startswith("account:unsetproxy:"))
async def account_unset_proxy(callback: CallbackQuery, session: AsyncSession) -> None:
    """Remove proxy from account."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    account_id = UUID(callback.data.split(":")[-1])
    
    account_repo = PostgresAccountRepository(session)
    
    account = await account_repo.get_by_id(account_id)
    
    if account and account.proxy_id:
        account.proxy_id = None
        await account_repo.save(account)
        await callback.answer("✅ Прокси отвязан", show_alert=True)
    
    # Show success with back button
    await callback.message.edit_text(
        "✅ <b>Прокси отвязан!</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ К аккаунту", callback_data=f"account:view:{account_id}")]
        ])
    )
    await callback.answer()


# =============================================================================
# Account Statistics
# =============================================================================

@router.callback_query(F.data.startswith("account:stats:"))
async def account_stats(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show detailed account statistics."""
    from src.infrastructure.database.repositories import PostgresDialogueRepository

    account_id = UUID(callback.data.split(":")[-1])

    service = get_account_service(session)
    dialogue_repo = PostgresDialogueRepository(session)

    try:
        account = await service.get_account(account_id)
    except Exception:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    # Get dialogues stats
    dialogues = await dialogue_repo.list_by_account(account_id, limit=1000)

    active_dialogues = sum(1 for d in dialogues if d.status.value == "active")
    completed = sum(1 for d in dialogues if d.status.value == "completed")
    goals_reached = sum(1 for d in dialogues if d.goal_reached)
    total_messages = sum(d.messages_count for d in dialogues)

    text = (
        f"📊 <b>Статистика аккаунта</b>\n\n"
        f"📱 {account.phone}\n"
        f"👤 @{account.username or '—'}\n\n"
        f"<b>Сегодня:</b>\n"
        f"• Сообщений: {account.hourly_messages_count}/{account.limits.max_messages_per_hour} (за час)\n"
        f"• Диалогов: {account.daily_conversations_count}/{account.limits.max_new_conversations_per_day} (за день)\n\n"
        f"<b>Всего:</b>\n"
        f"• Отправлено сообщений: {account.total_messages_sent}\n"
        f"• Начато диалогов: {account.total_conversations_started}\n\n"
        f"<b>Диалоги:</b>\n"
        f"• Активных: {active_dialogues}\n"
        f"• Завершено: {completed}\n"
        f"• Достигнута цель: {goals_reached}\n"
        f"• Всего сообщений: {total_messages}\n"
    )

    if goals_reached and completed:
        conv_rate = round(goals_reached / completed * 100, 1)
        text += f"\n<b>Конверсия:</b> {conv_rate}%"

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"account:view:{account_id}",
        )],
    ])

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


# =============================================================================
# Bulk Import (Multiple session+json in one ZIP)
# =============================================================================

@router.callback_query(F.data == "accounts:add:bulk")
async def bulk_import_start(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Start bulk import - uses all available proxies with rotation."""
    from src.infrastructure.database.repositories import PostgresProxyRepository

    proxy_repo = PostgresProxyRepository(session)
    proxies = await proxy_repo.list_available()

    if not proxies:
        await callback.message.edit_text(
            "📚 <b>Массовый импорт</b>\n\n"
            "⚠️ <b>Нет свободных прокси!</b>\n\n"
            "Все прокси уже назначены на аккаунты.\n"
            "Каждый прокси может использоваться только одним аккаунтом.\n\n"
            "Добавьте больше прокси в разделе 🌐 Прокси.",
            reply_markup=get_back_kb("accounts:menu"),
        )
        await callback.answer()
        return

    # Save all proxy IDs for rotation
    proxy_ids = [str(p.id) for p in proxies]
    await state.update_data(bulk_proxy_ids=proxy_ids)

    # Show delay selection
    delay_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚡ Без задержки", callback_data="bulk:delay:0"),
            InlineKeyboardButton(text="🕐 10 сек", callback_data="bulk:delay:10"),
        ],
        [
            InlineKeyboardButton(text="🕐 30 сек", callback_data="bulk:delay:30"),
            InlineKeyboardButton(text="🕐 60 сек", callback_data="bulk:delay:60"),
        ],
        [
            InlineKeyboardButton(text="🕐 2 мин", callback_data="bulk:delay:120"),
            InlineKeyboardButton(text="🕐 5 мин", callback_data="bulk:delay:300"),
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="accounts:menu")],
    ])

    await callback.message.edit_text(
        "📚 <b>Массовый импорт аккаунтов</b>\n\n"
        f"🌐 Прокси: <b>{len(proxies)} шт</b>\n\n"
        "<b>Выберите задержку между аккаунтами:</b>\n\n"
        "⚡ <b>Без задержки</b> - быстро, но выше риск заморозки\n"
        "🕐 <b>10-30 сек</b> - баланс скорости и безопасности\n"
        "🕐 <b>60+ сек</b> - безопасно, но долго\n\n"
        "💡 Рекомендуется 30-60 сек для новых аккаунтов",
        reply_markup=delay_kb,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("bulk:delay:"))
async def bulk_import_select_delay(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle delay selection for bulk import."""
    delay = int(callback.data.split(":")[-1])
    await state.update_data(bulk_delay=delay)
    await state.set_state(AccountStates.waiting_bulk_zip_file)

    delay_text = "без задержки" if delay == 0 else f"{delay} сек"

    await callback.message.edit_text(
        "📚 <b>Массовый импорт аккаунтов</b>\n\n"
        f"⏱ Задержка: <b>{delay_text}</b>\n\n"
        "<b>Отправьте ZIP-архив</b>\n\n"
        "<b>Формат архива:</b>\n\n"
        "<code>archive.zip/</code>\n"
        "  ├── 79001234567.session\n"
        "  ├── 79001234567.json\n"
        "  ├── 79009876543.session\n"
        "  ├── 79009876543.json\n"
        "  └── ...\n\n"
        "<b>JSON файл (опционально):</b>\n"
        "<code>{\n"
        '  "phone": "79001234567",\n'
        '  "id": 123456789,\n'
        '  "first_name": "Иван",\n'
        '  "twoFA": "password123"\n'
        "}</code>\n\n"
        "⚡ Каждый аккаунт получит свой прокси (ротация)",
    )
    await callback.message.answer(
        "Ожидаю ZIP-архив...",
        reply_markup=get_cancel_kb(),
    )
    await callback.answer()


@router.message(AccountStates.waiting_bulk_zip_file, F.document)
async def receive_bulk_zip_file(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Receive and process bulk ZIP archive with multiple session+json pairs."""
    import io
    import zipfile
    import tempfile
    import shutil
    import os
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import (
        SessionPasswordNeededError,
        AuthKeyDuplicatedError,
        PhoneNumberBannedError,
    )
    from src.config import get_settings
    from src.infrastructure.database.repositories import PostgresProxyRepository
    import python_socks

    doc = message.document

    if not doc.file_name.endswith(".zip"):
        await message.answer("❌ Отправьте файл с расширением .zip")
        return

    # Get proxy IDs and delay from state
    state_data = await state.get_data()
    proxy_ids = state_data.get("bulk_proxy_ids", [])
    import_delay = state_data.get("bulk_delay", 0)  # delay in seconds

    if not proxy_ids:
        await message.answer(
            "❌ Прокси не выбраны. Начните заново.",
            reply_markup=get_main_menu_kb(),
        )
        await state.clear()
        return

    # Load all proxies
    proxy_repo = PostgresProxyRepository(session)
    proxies = []
    for pid in proxy_ids:
        proxy = await proxy_repo.get_by_id(UUID(pid))
        if proxy:
            proxies.append(proxy)

    if not proxies:
        await message.answer(
            "❌ Прокси не найдены. Начните заново.",
            reply_markup=get_main_menu_kb(),
        )
        await state.clear()
        return

    delay_text = f", задержка: {import_delay} сек" if import_delay > 0 else ""
    status_msg = await message.answer(f"⏳ Распаковываю архив... (прокси: {len(proxies)} шт{delay_text})")

    temp_dir = None
    try:
        # Download ZIP file
        file = await message.bot.download(doc)
        zip_bytes = file.read()

        # Create temp directory for extraction
        temp_dir = tempfile.mkdtemp()

        # Extract ZIP
        with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zf:
            zf.extractall(temp_dir)

        # Find all session files
        session_files = []
        for root, dirs, files in os.walk(temp_dir):
            for f in files:
                if f.endswith('.session') and not f.startswith('__'):
                    session_files.append(os.path.join(root, f))

        if not session_files:
            await message.answer(
                "❌ В архиве не найдено .session файлов.",
                reply_markup=get_main_menu_kb(),
            )
            await state.clear()
            return

        # Check if we have enough proxies (1 proxy per account)
        if len(session_files) > len(proxies):
            await status_msg.edit_text(
                f"⚠️ <b>Недостаточно свободных прокси!</b>\n\n"
                f"📁 Аккаунтов в архиве: {len(session_files)}\n"
                f"🌐 Свободных прокси: {len(proxies)}\n\n"
                f"Каждый аккаунт требует отдельный прокси.\n"
                f"Добавьте ещё {len(session_files) - len(proxies)} прокси.",
                reply_markup=get_main_menu_kb(),
            )
            await state.clear()
            return

        await status_msg.edit_text(
            f"⏳ Найдено {len(session_files)} session файлов.\n"
            f"🌐 Прокси: {len(proxies)} шт (1 на аккаунт)\n"
            f"Начинаю обработку..."
        )

        # Process results
        success_count = 0
        error_count = 0
        skipped_count = 0
        results = []

        settings = get_settings()

        repo = PostgresAccountRepository(session)
        service = get_account_service(session)

        # Get TelegramApp credentials for validation (use least loaded or settings fallback)
        app_repo = PostgresTelegramAppRepository(session)
        available_apps = await app_repo.list_available(limit=100)

        for idx, session_file in enumerate(session_files, 1):
            client = None
            try:
                # Delay between accounts (except first one)
                if idx > 1 and import_delay > 0:
                    await status_msg.edit_text(
                        f"⏳ Ожидание {import_delay} сек перед аккаунтом {idx}/{len(session_files)}..."
                    )
                    await asyncio.sleep(import_delay)

                # Each account gets unique proxy (no sharing)
                current_proxy = proxies[idx - 1]
                proxy_dict = {
                    'proxy_type': python_socks.ProxyType.SOCKS5,
                    'addr': current_proxy.host,
                    'port': current_proxy.port,
                    'username': current_proxy.username,
                    'password': current_proxy.password,
                    'rdns': True,
                }

                # Generate unique device fingerprint for this account
                fingerprint = generate_random_fingerprint(prefer_android=True, lang_code="ru")

                # Update status
                await status_msg.edit_text(
                    f"⏳ Обрабатываю аккаунт {idx}/{len(session_files)}...\n"
                    f"🌐 Прокси: {current_proxy.host}:{current_proxy.port}\n"
                    f"📱 Device: {fingerprint.device_model}"
                )

                # Parse account data from corresponding JSON
                account_data = await _parse_bulk_account_data(session_file)
                phone = account_data.get("phone")

                # Check if account exists
                if phone:
                    existing = await repo.get_by_phone(phone if phone.startswith("+") else f"+{phone}")
                    if existing:
                        skipped_count += 1
                        results.append(f"⏭ {phone}: уже существует")
                        continue

                # Try to read and validate session
                session_string = await _convert_session_to_telethon_string(session_file)
                session_bytes = None

                if not session_string:
                    # Fallback to raw bytes
                    with open(session_file, 'rb') as f:
                        session_bytes = f.read()

                # Get API credentials: use TelegramApp if available, else settings
                # Rotate through available apps for load balancing
                if available_apps:
                    current_app = available_apps[(idx - 1) % len(available_apps)]
                    api_id = current_app.api_id
                    api_hash = current_app.api_hash
                else:
                    api_id = settings.telegram.api_id
                    api_hash = settings.telegram.api_hash.get_secret_value()

                if session_string:
                    client = TelegramClient(
                        StringSession(session_string),
                        api_id,
                        api_hash,
                        proxy=proxy_dict,
                        device_model=fingerprint.device_model,
                        system_version=fingerprint.system_version,
                        app_version=fingerprint.app_version,
                        lang_code=fingerprint.lang_code,
                        system_lang_code=fingerprint.system_lang_code,
                    )
                else:
                    # Use temp file session
                    temp_session_base = os.path.join(temp_dir, f"temp_session_{idx}")
                    with open(temp_session_base + ".session", 'wb') as f:
                        f.write(session_bytes)

                    client = TelegramClient(
                        temp_session_base,
                        api_id,
                        api_hash,
                        proxy=proxy_dict,
                        device_model=fingerprint.device_model,
                        system_version=fingerprint.system_version,
                        app_version=fingerprint.app_version,
                        lang_code=fingerprint.lang_code,
                        system_lang_code=fingerprint.system_lang_code,
                    )

                await client.connect()

                # Check authorization
                if not await client.is_user_authorized():
                    # Try 2FA if password available
                    twofa = account_data.get("twofa")
                    if twofa:
                        try:
                            await client.sign_in(password=twofa)
                        except Exception:
                            error_count += 1
                            results.append(f"❌ {phone or 'unknown'}: невалидная сессия/2FA")
                            continue
                    else:
                        error_count += 1
                        results.append(f"❌ {phone or 'unknown'}: невалидная сессия")
                        continue

                # Get user info
                me = await client.get_me()

                phone = f"+{me.phone}" if me.phone else account_data.get("phone", "")
                if phone and not phone.startswith("+"):
                    phone = f"+{phone}"

                if not phone:
                    error_count += 1
                    results.append(f"❌ unknown: не удалось получить номер")
                    continue

                # Check again after getting real phone
                existing = await repo.get_by_phone(phone)
                if existing:
                    skipped_count += 1
                    results.append(f"⏭ {phone}: уже существует")
                    continue

                # Get string session for storage
                if not session_string:
                    session_string = StringSession.save(client.session)

                # Encrypt session data
                from src.utils.crypto import get_session_encryption
                encryption = get_session_encryption()
                encrypted = encryption.encrypt(session_string.encode('utf-8'))

                # Create account
                account = await service.create_account(
                    phone=phone,
                    session_data=encrypted,
                    source=AccountSource.JSON_SESSION,
                )

                # Update with validated data
                account.telegram_id = me.id
                account.username = me.username
                account.first_name = me.first_name or ""
                account.last_name = me.last_name or ""
                account.proxy_id = current_proxy.id

                # Assign the TelegramApp that was used for validation
                if available_apps:
                    assigned_app = available_apps[(idx - 1) % len(available_apps)]
                    account.telegram_app_id = assigned_app.id
                    await app_repo.increment_account_count(assigned_app.id)

                await service.account_repo.save(account)

                success_count += 1
                name = f"@{me.username}" if me.username else me.first_name or phone
                results.append(f"✅ {phone}: {name}")

            except SessionPasswordNeededError:
                # Try using 2FA from JSON
                twofa = account_data.get("twofa")
                if twofa:
                    try:
                        await client.sign_in(password=twofa)
                        me = await client.get_me()

                        phone = f"+{me.phone}" if me.phone else account_data.get("phone", "")
                        if phone and not phone.startswith("+"):
                            phone = f"+{phone}"

                        existing = await repo.get_by_phone(phone)
                        if existing:
                            skipped_count += 1
                            results.append(f"⏭ {phone}: уже существует")
                            continue

                        if not session_string:
                            session_string = StringSession.save(client.session)

                        from src.utils.crypto import get_session_encryption
                        encryption = get_session_encryption()
                        encrypted = encryption.encrypt(session_string.encode('utf-8'))

                        account = await service.create_account(
                            phone=phone,
                            session_data=encrypted,
                            source=AccountSource.JSON_SESSION,
                        )

                        account.telegram_id = me.id
                        account.username = me.username
                        account.first_name = me.first_name or ""
                        account.last_name = me.last_name or ""
                        account.proxy_id = current_proxy.id

                        # Assign the TelegramApp that was used for validation
                        if available_apps:
                            assigned_app = available_apps[(idx - 1) % len(available_apps)]
                            account.telegram_app_id = assigned_app.id
                            await app_repo.increment_account_count(assigned_app.id)

                        await service.account_repo.save(account)

                        success_count += 1
                        name = f"@{me.username}" if me.username else me.first_name or phone
                        results.append(f"✅ {phone}: {name} (2FA)")

                    except Exception as e:
                        error_count += 1
                        results.append(f"❌ {phone or 'unknown'}: неверный 2FA пароль")
                else:
                    error_count += 1
                    results.append(f"❌ {phone or 'unknown'}: требуется 2FA (нет пароля в JSON)")

            except AuthKeyDuplicatedError:
                error_count += 1
                results.append(f"❌ {phone or 'unknown'}: сессия используется")

            except PhoneNumberBannedError:
                error_count += 1
                results.append(f"❌ {phone or 'unknown'}: аккаунт забанен")

            except Exception as e:
                error_count += 1
                phone_display = account_data.get("phone", "unknown") if 'account_data' in dir() else "unknown"
                results.append(f"❌ {phone_display}: {str(e)[:30]}")

            finally:
                if client:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass

        await state.clear()

        # Build result message
        result_text = (
            f"📚 <b>Массовый импорт завершён</b>\n\n"
            f"✅ Успешно: {success_count}\n"
            f"⏭ Пропущено: {skipped_count}\n"
            f"❌ Ошибок: {error_count}\n\n"
            f"🌐 Прокси: <code>{proxy.host}:{proxy.port}</code>\n\n"
        )

        # Add detailed results (limit to prevent message overflow)
        if results:
            result_text += "<b>Результаты:</b>\n"
            for r in results[:30]:  # Max 30 items
                result_text += f"{r}\n"
            if len(results) > 30:
                result_text += f"... и ещё {len(results) - 30}\n"

        await message.answer(
            result_text,
            reply_markup=get_main_menu_kb(),
        )

    except zipfile.BadZipFile:
        await message.answer(
            "❌ Некорректный ZIP-архив.",
            reply_markup=get_main_menu_kb(),
        )
        await state.clear()
    except Exception as e:
        import traceback
        traceback.print_exc()
        await message.answer(
            f"❌ Ошибка обработки архива: {e}",
            reply_markup=get_main_menu_kb(),
        )
        await state.clear()
    finally:
        # Cleanup temp directory
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


async def _parse_bulk_account_data(session_file: str) -> dict:
    """Parse account data from corresponding JSON file."""
    import os
    import json

    result = {
        "phone": None,
        "telegram_id": None,
        "username": None,
        "first_name": "",
        "last_name": "",
        "twofa": None,
        "is_premium": False,
    }

    # Get base name without extension
    base_path = session_file.rsplit('.session', 1)[0]
    json_file = base_path + '.json'

    # Also try with same directory but different casing
    session_dir = os.path.dirname(session_file)
    session_name = os.path.basename(session_file).replace('.session', '')

    # Extract phone from filename
    if session_name.isdigit() or (session_name.startswith('+') and session_name[1:].isdigit()):
        result["phone"] = session_name

    # Try to find and parse JSON
    if os.path.exists(json_file):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            result["phone"] = str(data.get("phone", result["phone"] or ""))
            result["telegram_id"] = data.get("id")
            result["username"] = data.get("username")
            result["first_name"] = data.get("first_name", "")
            result["last_name"] = data.get("last_name", "")
            result["is_premium"] = data.get("is_premium", False)

            if data.get("twoFA"):
                result["twofa"] = str(data.get("twoFA"))
            elif data.get("2fa"):
                result["twofa"] = str(data.get("2fa"))
            elif data.get("password"):
                result["twofa"] = str(data.get("password"))
        except Exception:
            pass

    # Also check for 2FA.txt or password.txt in same directory
    for twofa_name in ['2FA.txt', '2fa.txt', 'Password2FA.txt', 'password.txt']:
        twofa_path = os.path.join(session_dir, twofa_name)
        if os.path.exists(twofa_path) and not result["twofa"]:
            try:
                with open(twofa_path, 'r', encoding='utf-8') as f:
                    result["twofa"] = f.read().strip()
            except Exception:
                pass

    return result


# =============================================================================
# Multi-Archive Import (Multiple ZIP archives, each with folder containing json+session)
# =============================================================================

@router.callback_query(F.data == "accounts:add:multi_archive")
async def multi_archive_import_start(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Start multi-archive import - ask how many accounts."""
    from src.infrastructure.database.repositories import PostgresProxyRepository

    proxy_repo = PostgresProxyRepository(session)
    proxies = await proxy_repo.list_available()

    if not proxies:
        await callback.message.edit_text(
            "📂 <b>Импорт из нескольких архивов</b>\n\n"
            "⚠️ <b>Нет доступных прокси!</b>\n\n"
            "Для загрузки и проверки аккаунтов нужен прокси.\n"
            "Сначала добавьте прокси в разделе 🌐 Прокси.",
            reply_markup=get_back_kb("accounts:menu"),
        )
        await callback.answer()
        return

    # Save proxies count for display
    await state.update_data(multi_archive_proxies_count=len(proxies))
    await state.set_state(AccountStates.waiting_multi_archive_count)

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="accounts:add"))

    await callback.message.edit_text(
        "📂 <b>Импорт из нескольких архивов</b>\n\n"
        "Шаг 1/2: <b>Сколько аккаунтов планируете загрузить?</b>\n\n"
        f"🌐 Доступно прокси: {len(proxies)}\n\n"
        "Прокси будут автоматически распределены между аккаунтами.\n"
        "Каждому аккаунту назначится свой прокси (по кругу).\n\n"
        "Введите число (например: 10):",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.message(AccountStates.waiting_multi_archive_count)
async def multi_archive_count_received(message: Message, session: AsyncSession, state: FSMContext) -> None:
    """Received account count, now request files."""
    from src.infrastructure.database.repositories import PostgresProxyRepository

    text = message.text.strip() if message.text else ""

    if not text.isdigit() or int(text) <= 0:
        await message.answer(
            "⚠️ Введите положительное число.\n\n"
            "Например: 10",
        )
        return

    account_count = int(text)

    # Get available proxies
    proxy_repo = PostgresProxyRepository(session)
    proxies = await proxy_repo.list_available()

    if not proxies:
        await message.answer(
            "❌ Нет доступных прокси. Сначала добавьте прокси.",
            reply_markup=get_main_menu_kb(),
        )
        await state.clear()
        return

    # Save proxies list and count to state
    proxy_list = [{"id": str(p.id), "host": p.host, "port": p.port, "username": p.username, "password": p.password} for p in proxies]

    await state.update_data(
        multi_archive_count=account_count,
        multi_archive_proxies=proxy_list,
        multi_archive_files=[],
    )
    await state.set_state(AccountStates.waiting_multi_archive_files)

    await message.answer(
        f"📂 <b>Импорт из нескольких архивов</b>\n\n"
        f"Шаг 2/2: <b>Отправьте ZIP-архивы</b>\n\n"
        f"📊 Ожидается аккаунтов: {account_count}\n"
        f"🌐 Доступно прокси: {len(proxies)} (будут распределены по кругу)\n\n"
        "<b>Формат каждого архива:</b>\n\n"
        "<code>archive.zip/</code>\n"
        "  └── 📁 папка (любое имя)/\n"
        "        ├── *.session\n"
        "        └── *.json\n\n"
        "<b>Пример:</b>\n"
        "<code>79001234567.zip/</code>\n"
        "  └── 📁 79001234567/\n"
        "        ├── 79001234567.session\n"
        "        └── 79001234567.json\n\n"
        "📎 Отправьте архивы (можно несколько сразу).\n"
        "Когда закончите — нажмите <b>✅ Готово</b>",
    )

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="✅ Готово — начать импорт",
        callback_data="accounts:multi_archive:process",
    ))
    kb.row(InlineKeyboardButton(
        text="❌ Отмена",
        callback_data="accounts:add",
    ))

    await message.answer(
        "Ожидаю ZIP-архивы...\n\n"
        "Загружено: 0 архивов",
        reply_markup=kb.as_markup(),
    )


# Lock storage for multi-archive uploads (per user)
_multi_archive_locks: dict[int, "asyncio.Lock"] = {}


def _get_user_lock(user_id: int) -> "asyncio.Lock":
    """Get or create a lock for user to prevent race conditions."""
    import asyncio
    if user_id not in _multi_archive_locks:
        _multi_archive_locks[user_id] = asyncio.Lock()
    return _multi_archive_locks[user_id]


@router.message(AccountStates.waiting_multi_archive_files, F.document)
async def receive_multi_archive_file(
    message: Message,
    state: FSMContext,
) -> None:
    """Receive ZIP archive and add to collection."""
    doc = message.document

    if not doc.file_name.lower().endswith(".zip"):
        await message.answer("⚠️ Отправьте файл с расширением .zip")
        return

    new_file = {
        "file_id": doc.file_id,
        "file_name": doc.file_name,
        "file_size": doc.file_size,
    }

    # Use per-user lock for atomic update to avoid race conditions
    # when multiple files are sent simultaneously
    user_lock = _get_user_lock(message.from_user.id)
    async with user_lock:
        state_data = await state.get_data()
        files = list(state_data.get("multi_archive_files", []))  # Create a copy

        # Check if file already added (by file_id)
        if not any(f["file_id"] == new_file["file_id"] for f in files):
            files.append(new_file)
            await state.update_data(multi_archive_files=files)

        file_count = len(files)

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="✅ Готово — начать импорт",
        callback_data="accounts:multi_archive:process",
    ))
    kb.row(InlineKeyboardButton(
        text="❌ Отмена",
        callback_data="accounts:add",
    ))

    await message.answer(
        f"✅ Добавлен: {doc.file_name}\n\n"
        f"📦 Загружено архивов: {file_count}\n\n"
        "Отправьте ещё или нажмите <b>✅ Готово</b>",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data == "accounts:multi_archive:process", AccountStates.waiting_multi_archive_files)
async def process_multi_archive_files(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Process all collected ZIP archives with proxy distribution."""
    import io
    import zipfile
    import tempfile
    import shutil
    import os
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import (
        SessionPasswordNeededError,
        AuthKeyDuplicatedError,
        PhoneNumberBannedError,
    )
    from src.config import get_settings
    import python_socks

    state_data = await state.get_data()
    files = state_data.get("multi_archive_files", [])
    proxy_list = state_data.get("multi_archive_proxies", [])

    if not files:
        await callback.answer("❌ Не загружено ни одного архива", show_alert=True)
        return

    if not proxy_list:
        await callback.message.answer(
            "❌ Нет прокси для распределения. Начните заново.",
            reply_markup=get_main_menu_kb(),
        )
        await state.clear()
        return

    await callback.answer()

    status_msg = await callback.message.answer(
        f"⏳ Начинаю обработку {len(files)} архивов...\n"
        f"🌐 Прокси для распределения: {len(proxy_list)}"
    )

    # Process results
    total_success = 0
    total_errors = 0
    total_skipped = 0
    all_results = []
    proxy_distribution = {}  # Track which proxy was assigned to which account

    settings = get_settings()

    # Proxy index for round-robin distribution
    proxy_index = 0

    repo = PostgresAccountRepository(session)
    service = get_account_service(session)

    # Get TelegramApp credentials for validation (use least loaded or settings fallback)
    app_repo = PostgresTelegramAppRepository(session)
    available_apps = await app_repo.list_available(limit=100)
    app_index = 0  # Index for round-robin TelegramApp assignment

    for file_idx, file_info in enumerate(files, 1):
        file_id = file_info["file_id"]
        file_name = file_info["file_name"]

        temp_dir = None
        try:
            await status_msg.edit_text(
                f"⏳ Обрабатываю архив {file_idx}/{len(files)}: {file_name}..."
            )

            # Download ZIP file
            file = await callback.bot.download(file_id)
            zip_bytes = file.read()

            # Create temp directory for extraction
            temp_dir = tempfile.mkdtemp()

            # Extract ZIP
            with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zf:
                zf.extractall(temp_dir)

            # Find session files (including in subdirectories)
            session_files = []
            for root, dirs, dir_files in os.walk(temp_dir):
                for f in dir_files:
                    if f.endswith('.session') and not f.startswith('__'):
                        session_files.append(os.path.join(root, f))

            if not session_files:
                all_results.append(f"⚠️ {file_name}: нет .session файлов")
                total_errors += 1
                continue

            # Process each session in this archive
            for session_file in session_files:
                client = None
                try:
                    # Get current proxy from round-robin distribution
                    current_proxy = proxy_list[proxy_index % len(proxy_list)]
                    proxy_dict = {
                        'proxy_type': python_socks.ProxyType.SOCKS5,
                        'addr': current_proxy["host"],
                        'port': current_proxy["port"],
                        'username': current_proxy.get("username"),
                        'password': current_proxy.get("password"),
                        'rdns': True,
                    }

                    # Generate unique device fingerprint for this account
                    fingerprint = generate_random_fingerprint(prefer_android=True, lang_code="ru")

                    # Parse account data from corresponding JSON
                    account_data = await _parse_bulk_account_data(session_file)
                    phone = account_data.get("phone")

                    # Check if account exists
                    if phone:
                        check_phone = phone if phone.startswith("+") else f"+{phone}"
                        existing = await repo.get_by_phone(check_phone)
                        if existing:
                            total_skipped += 1
                            all_results.append(f"⏭ {phone}: уже существует")
                            continue

                    # Try to read and validate session
                    session_string = await _convert_session_to_telethon_string(session_file)
                    session_bytes = None

                    if not session_string:
                        # Fallback to raw bytes
                        with open(session_file, 'rb') as f:
                            session_bytes = f.read()

                    # Get API credentials: use TelegramApp if available, else settings
                    if available_apps:
                        current_app = available_apps[app_index % len(available_apps)]
                        api_id = current_app.api_id
                        api_hash = current_app.api_hash
                    else:
                        current_app = None
                        api_id = settings.telegram.api_id
                        api_hash = settings.telegram.api_hash.get_secret_value()

                    if session_string:
                        client = TelegramClient(
                            StringSession(session_string),
                            api_id,
                            api_hash,
                            proxy=proxy_dict,
                            device_model=fingerprint.device_model,
                            system_version=fingerprint.system_version,
                            app_version=fingerprint.app_version,
                            lang_code=fingerprint.lang_code,
                            system_lang_code=fingerprint.system_lang_code,
                        )
                    else:
                        # Use temp file session
                        temp_session_base = os.path.join(temp_dir, f"temp_session_{file_idx}")
                        with open(temp_session_base + ".session", 'wb') as f:
                            f.write(session_bytes)

                        client = TelegramClient(
                            temp_session_base,
                            api_id,
                            api_hash,
                            proxy=proxy_dict,
                            device_model=fingerprint.device_model,
                            system_version=fingerprint.system_version,
                            app_version=fingerprint.app_version,
                            lang_code=fingerprint.lang_code,
                            system_lang_code=fingerprint.system_lang_code,
                        )

                    await client.connect()

                    # Check authorization
                    if not await client.is_user_authorized():
                        twofa = account_data.get("twofa")
                        if twofa:
                            try:
                                await client.sign_in(password=twofa)
                            except Exception:
                                total_errors += 1
                                all_results.append(f"❌ {phone or 'unknown'}: невалидная сессия/2FA")
                                continue
                        else:
                            total_errors += 1
                            all_results.append(f"❌ {phone or 'unknown'}: невалидная сессия")
                            continue

                    # Get user info
                    me = await client.get_me()

                    phone = f"+{me.phone}" if me.phone else account_data.get("phone", "")
                    if phone and not phone.startswith("+"):
                        phone = f"+{phone}"

                    if not phone:
                        total_errors += 1
                        all_results.append(f"❌ unknown: не удалось получить номер")
                        continue

                    # Check again after getting real phone
                    existing = await repo.get_by_phone(phone)
                    if existing:
                        total_skipped += 1
                        all_results.append(f"⏭ {phone}: уже существует")
                        continue

                    # Get string session for storage
                    if not session_string:
                        session_string = StringSession.save(client.session)

                    # Encrypt session data
                    from src.utils.crypto import get_session_encryption
                    encryption = get_session_encryption()
                    encrypted = encryption.encrypt(session_string.encode('utf-8'))

                    # Create account
                    account = await service.create_account(
                        phone=phone,
                        session_data=encrypted,
                        source=AccountSource.JSON_SESSION,
                    )

                    # Update with validated data
                    account.telegram_id = me.id
                    account.username = me.username
                    account.first_name = me.first_name or ""
                    account.last_name = me.last_name or ""
                    account.proxy_id = UUID(current_proxy["id"])

                    # Assign the TelegramApp that was used for validation
                    if current_app:
                        account.telegram_app_id = current_app.id
                        await app_repo.increment_account_count(current_app.id)
                        app_index += 1  # Move to next app for load balancing

                    await service.account_repo.save(account)

                    total_success += 1
                    proxy_index += 1  # Move to next proxy for next account
                    proxy_host = f"{current_proxy['host']}:{current_proxy['port']}"
                    name = f"@{me.username}" if me.username else me.first_name or phone
                    all_results.append(f"✅ {phone}: {name} → {proxy_host}")

                except SessionPasswordNeededError:
                    twofa = account_data.get("twofa")
                    if twofa:
                        try:
                            await client.sign_in(password=twofa)
                            me = await client.get_me()

                            phone = f"+{me.phone}" if me.phone else account_data.get("phone", "")
                            if phone and not phone.startswith("+"):
                                phone = f"+{phone}"

                            existing = await repo.get_by_phone(phone)
                            if existing:
                                total_skipped += 1
                                all_results.append(f"⏭ {phone}: уже существует")
                                continue

                            if not session_string:
                                session_string = StringSession.save(client.session)

                            from src.utils.crypto import get_session_encryption
                            encryption = get_session_encryption()
                            encrypted = encryption.encrypt(session_string.encode('utf-8'))

                            account = await service.create_account(
                                phone=phone,
                                session_data=encrypted,
                                source=AccountSource.JSON_SESSION,
                            )

                            account.telegram_id = me.id
                            account.username = me.username
                            account.first_name = me.first_name or ""
                            account.last_name = me.last_name or ""
                            account.proxy_id = UUID(current_proxy["id"])

                            # Assign the TelegramApp that was used for validation
                            if current_app:
                                account.telegram_app_id = current_app.id
                                await app_repo.increment_account_count(current_app.id)
                                app_index += 1  # Move to next app for load balancing

                            await service.account_repo.save(account)

                            total_success += 1
                            proxy_index += 1  # Move to next proxy for next account
                            proxy_host = f"{current_proxy['host']}:{current_proxy['port']}"
                            name = f"@{me.username}" if me.username else me.first_name or phone
                            all_results.append(f"✅ {phone}: {name} (2FA) → {proxy_host}")

                        except Exception:
                            total_errors += 1
                            all_results.append(f"❌ {phone or 'unknown'}: неверный 2FA пароль")
                    else:
                        total_errors += 1
                        all_results.append(f"❌ {phone or 'unknown'}: требуется 2FA (нет пароля)")

                except AuthKeyDuplicatedError:
                    total_errors += 1
                    all_results.append(f"❌ {phone or 'unknown'}: сессия используется")

                except PhoneNumberBannedError:
                    total_errors += 1
                    all_results.append(f"❌ {phone or 'unknown'}: аккаунт забанен")

                except Exception as e:
                    total_errors += 1
                    phone_display = account_data.get("phone", "unknown") if 'account_data' in dir() else "unknown"
                    all_results.append(f"❌ {phone_display}: {str(e)[:30]}")

                finally:
                    if client:
                        try:
                            await client.disconnect()
                        except Exception:
                            pass

        except zipfile.BadZipFile:
            all_results.append(f"❌ {file_name}: некорректный архив")
            total_errors += 1

        except Exception as e:
            all_results.append(f"❌ {file_name}: {str(e)[:30]}")
            total_errors += 1

        finally:
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    await state.clear()

    # Build result message
    result_text = (
        f"📂 <b>Импорт завершён</b>\n\n"
        f"📦 Обработано архивов: {len(files)}\n\n"
        f"✅ Успешно: {total_success}\n"
        f"⏭ Пропущено: {total_skipped}\n"
        f"❌ Ошибок: {total_errors}\n\n"
        f"🌐 Использовано прокси: {len(proxy_list)} (распределение по кругу)\n\n"
    )

    # Add detailed results (limit to prevent message overflow)
    if all_results:
        result_text += "<b>Результаты:</b>\n"
        for r in all_results[:30]:
            result_text += f"{r}\n"
        if len(all_results) > 30:
            result_text += f"... и ещё {len(all_results) - 30}\n"

    await callback.message.answer(
        result_text,
        reply_markup=get_main_menu_kb(),
    )
