"""Account management handlers for comment bot."""

from uuid import UUID

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.errors import (
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PasswordHashInvalidError,
)

from src.commentbot.application.services import AccountService
from src.commentbot.domain.entities import AccountStatus
from src.commentbot.infrastructure.database.repository import AccountRepository
from src.commentbot.presentation.admin_bot.states import AccountStates
from src.commentbot.presentation.admin_bot.keyboards import (
    accounts_menu_keyboard,
    account_actions_keyboard,
    cancel_keyboard,
    confirm_delete_keyboard,
    back_to_accounts_keyboard,
)

router = Router()

# Store pending account IDs in FSM
PENDING_ACCOUNT_KEY = "pending_account_id"


def _get_status_emoji(status: AccountStatus) -> str:
    """Get emoji for account status."""
    return {
        AccountStatus.PENDING: "⏳",
        AccountStatus.AUTH_CODE: "📨",
        AccountStatus.AUTH_2FA: "🔐",
        AccountStatus.ACTIVE: "✅",
        AccountStatus.PAUSED: "⏸",
        AccountStatus.BANNED: "🚫",
        AccountStatus.ERROR: "❌",
    }.get(status, "❓")


# =========================================
# Menu Handlers
# =========================================


@router.message(F.text == "📱 Аккаунты")
async def accounts_menu(message: Message, session: AsyncSession):
    """Show accounts menu."""
    repo = AccountRepository(session)
    accounts = await repo.list_by_owner(message.from_user.id)

    active = sum(1 for a in accounts if a.status == AccountStatus.ACTIVE)
    total = len(accounts)

    await message.answer(
        f"📱 <b>Управление аккаунтами</b>\n\n"
        f"Всего аккаунтов: {total}\n"
        f"Активных: {active}",
        reply_markup=accounts_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "acc:menu")
async def accounts_menu_callback(callback: CallbackQuery, session: AsyncSession):
    """Show accounts menu (callback)."""
    repo = AccountRepository(session)
    accounts = await repo.list_by_owner(callback.from_user.id)

    active = sum(1 for a in accounts if a.status == AccountStatus.ACTIVE)
    total = len(accounts)

    await callback.message.edit_text(
        f"📱 <b>Управление аккаунтами</b>\n\n"
        f"Всего аккаунтов: {total}\n"
        f"Активных: {active}",
        reply_markup=accounts_menu_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


# =========================================
# Add Account (Phone)
# =========================================


@router.callback_query(F.data == "acc:add_phone")
async def start_add_phone(callback: CallbackQuery, state: FSMContext):
    """Start phone auth flow."""
    await callback.message.edit_text(
        "📱 <b>Добавление аккаунта по номеру</b>\n\n"
        "Отправьте номер телефона с кодом страны:\n"
        "Например: <code>+79991234567</code>",
        reply_markup=cancel_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(AccountStates.waiting_phone)
    await callback.answer()


@router.message(AccountStates.waiting_phone)
async def process_phone(message: Message, state: FSMContext, session: AsyncSession):
    """Process phone number input."""
    phone = message.text.strip()

    repo = AccountRepository(session)
    service = AccountService(repo)

    try:
        account = await service.start_phone_auth(
            phone=phone,
            owner_id=message.from_user.id,
        )
        await session.commit()

        await state.update_data({PENDING_ACCOUNT_KEY: str(account.id)})
        await state.set_state(AccountStates.waiting_code)

        await message.answer(
            f"📨 <b>Код отправлен!</b>\n\n"
            f"На номер {phone} отправлен код подтверждения.\n"
            f"Введите код:",
            reply_markup=cancel_keyboard(),
            parse_mode="HTML",
        )

    except ValueError as e:
        await message.answer(
            f"❌ Ошибка: {e}\n\n"
            f"Попробуйте ещё раз или нажмите Отмена.",
            reply_markup=cancel_keyboard(),
        )


@router.message(AccountStates.waiting_code)
async def process_code(message: Message, state: FSMContext, session: AsyncSession):
    """Process verification code."""
    code = message.text.strip().replace(" ", "").replace("-", "")

    data = await state.get_data()
    account_id = data.get(PENDING_ACCOUNT_KEY)
    if not account_id:
        await message.answer("❌ Сессия истекла, начните заново")
        await state.clear()
        return

    repo = AccountRepository(session)
    service = AccountService(repo)

    try:
        account = await service.verify_code(
            account_id=UUID(account_id),
            code=code,
        )
        await session.commit()

        if account.status == AccountStatus.AUTH_2FA:
            await state.set_state(AccountStates.waiting_2fa)
            await message.answer(
                "🔐 <b>Требуется 2FA</b>\n\n"
                "Введите пароль двухфакторной аутентификации:",
                reply_markup=cancel_keyboard(),
                parse_mode="HTML",
            )
        else:
            await state.clear()
            await message.answer(
                f"✅ <b>Аккаунт добавлен!</b>\n\n"
                f"Телефон: {account.phone}\n"
                f"Статус: Активен",
                reply_markup=back_to_accounts_keyboard(),
                parse_mode="HTML",
            )

    except PhoneCodeInvalidError:
        await message.answer(
            "❌ Неверный код!\n\n"
            "Проверьте код и попробуйте ещё раз.",
            reply_markup=cancel_keyboard(),
        )

    except PhoneCodeExpiredError:
        await state.clear()
        await message.answer(
            "❌ Код истёк!\n\n"
            "Начните авторизацию заново.",
            reply_markup=back_to_accounts_keyboard(),
        )


@router.message(AccountStates.waiting_2fa)
async def process_2fa(message: Message, state: FSMContext, session: AsyncSession):
    """Process 2FA password."""
    password = message.text.strip()

    data = await state.get_data()
    account_id = data.get(PENDING_ACCOUNT_KEY)
    if not account_id:
        await message.answer("❌ Сессия истекла, начните заново")
        await state.clear()
        return

    repo = AccountRepository(session)
    service = AccountService(repo)

    try:
        account = await service.verify_2fa(
            account_id=UUID(account_id),
            password=password,
        )
        await session.commit()

        await state.clear()
        await message.answer(
            f"✅ <b>Аккаунт добавлен!</b>\n\n"
            f"Телефон: {account.phone}\n"
            f"Статус: Активен",
            reply_markup=back_to_accounts_keyboard(),
            parse_mode="HTML",
        )

    except PasswordHashInvalidError:
        await message.answer(
            "❌ Неверный пароль!\n\n"
            "Проверьте пароль и попробуйте ещё раз.",
            reply_markup=cancel_keyboard(),
        )


# =========================================
# Add Account (tdata)
# =========================================


@router.callback_query(F.data == "acc:add_tdata")
async def start_add_tdata(callback: CallbackQuery, state: FSMContext):
    """Start tdata auth flow."""
    await callback.message.edit_text(
        "📁 <b>Добавление аккаунта через tdata</b>\n\n"
        "🚧 <i>В разработке...</i>\n\n"
        "Отправьте архив tdata.zip",
        reply_markup=cancel_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(AccountStates.waiting_tdata)
    await callback.answer()


@router.message(AccountStates.waiting_tdata)
async def process_tdata(message: Message, state: FSMContext):
    """Process tdata file."""
    # TODO: Implement tdata processing
    await message.answer(
        "🚧 <i>Функция в разработке</i>\n\n"
        "Пока доступна только авторизация по номеру телефона.",
        reply_markup=back_to_accounts_keyboard(),
        parse_mode="HTML",
    )
    await state.clear()


# =========================================
# List Accounts
# =========================================


@router.callback_query(F.data == "acc:list")
async def list_accounts(callback: CallbackQuery, session: AsyncSession):
    """Show accounts list."""
    repo = AccountRepository(session)
    accounts = await repo.list_by_owner(callback.from_user.id)

    if not accounts:
        await callback.message.edit_text(
            "📋 <b>Список аккаунтов</b>\n\n"
            "<i>Нет добавленных аккаунтов</i>",
            reply_markup=accounts_menu_keyboard(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    builder = InlineKeyboardBuilder()

    for acc in accounts:
        emoji = _get_status_emoji(acc.status)
        phone_display = acc.phone[:4] + "****" + acc.phone[-2:] if acc.phone else "N/A"
        builder.row(
            InlineKeyboardButton(
                text=f"{emoji} {phone_display}",
                callback_data=f"acc:view:{acc.id}",
            )
        )

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="acc:menu"),
    )

    await callback.message.edit_text(
        f"📋 <b>Список аккаунтов</b>\n\n"
        f"Всего: {len(accounts)}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


# =========================================
# View Account
# =========================================


@router.callback_query(F.data.startswith("acc:view:"))
async def view_account(callback: CallbackQuery, session: AsyncSession):
    """View account details."""
    account_id = callback.data.split(":")[2]

    repo = AccountRepository(session)
    account = await repo.get_by_id(UUID(account_id))

    if not account:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    emoji = _get_status_emoji(account.status)
    phone_display = account.phone if account.phone else "N/A"

    text = (
        f"📱 <b>Аккаунт</b>\n\n"
        f"Телефон: <code>{phone_display}</code>\n"
        f"Статус: {emoji} {account.status.value}\n"
        f"Комментариев сегодня: {account.comments_today}/{account.daily_limit}\n"
    )

    if account.error_message:
        text += f"\n⚠️ Ошибка: {account.error_message}"

    if account.last_used_at:
        text += f"\nПоследняя активность: {account.last_used_at.strftime('%d.%m.%Y %H:%M')}"

    await callback.message.edit_text(
        text,
        reply_markup=account_actions_keyboard(
            account_id=str(account.id),
            is_active=account.status == AccountStatus.ACTIVE,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


# =========================================
# Account Actions
# =========================================


@router.callback_query(F.data.startswith("acc:pause:"))
async def pause_account(callback: CallbackQuery, session: AsyncSession):
    """Pause account."""
    account_id = callback.data.split(":")[2]

    repo = AccountRepository(session)
    service = AccountService(repo)

    account = await service.pause_account(UUID(account_id))
    await session.commit()

    if account:
        await callback.answer("Аккаунт приостановлен")
        # Refresh view
        await view_account(callback, session)
    else:
        await callback.answer("Аккаунт не найден", show_alert=True)


@router.callback_query(F.data.startswith("acc:resume:"))
async def resume_account(callback: CallbackQuery, session: AsyncSession):
    """Resume account."""
    account_id = callback.data.split(":")[2]

    repo = AccountRepository(session)
    service = AccountService(repo)

    account = await service.resume_account(UUID(account_id))
    await session.commit()

    if account:
        await callback.answer("Аккаунт возобновлён")
        # Refresh view
        await view_account(callback, session)
    else:
        await callback.answer("Аккаунт не найден", show_alert=True)


@router.callback_query(F.data.startswith("acc:delete:"))
async def delete_account_confirm(callback: CallbackQuery):
    """Confirm account deletion."""
    account_id = callback.data.split(":")[2]

    await callback.message.edit_text(
        "🗑 <b>Удаление аккаунта</b>\n\n"
        "Вы уверены, что хотите удалить этот аккаунт?\n"
        "Это действие нельзя отменить.",
        reply_markup=confirm_delete_keyboard(account_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("acc:confirm_delete:"))
async def delete_account(callback: CallbackQuery, session: AsyncSession):
    """Delete account."""
    account_id = callback.data.split(":")[2]

    repo = AccountRepository(session)
    service = AccountService(repo)

    deleted = await service.delete_account(UUID(account_id))
    await session.commit()

    if deleted:
        await callback.answer("Аккаунт удалён")
        await list_accounts(callback, session)
    else:
        await callback.answer("Аккаунт не найден", show_alert=True)


# =========================================
# Cancel
# =========================================


@router.callback_query(F.data == "cancel")
async def cancel_action(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Cancel current action."""
    await state.clear()
    await accounts_menu_callback(callback, session)
