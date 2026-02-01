"""
Campaign management handlers.
"""

from uuid import UUID

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services import CampaignService
from src.infrastructure.database.repositories import (
    PostgresAccountRepository,
    PostgresCampaignRepository,
    PostgresUserTargetRepository,
)
from src.domain.entities import CampaignStatus

from ..keyboards import (
    get_campaigns_menu_kb,
    get_campaign_actions_kb,
    get_campaign_configure_kb,
    get_cancel_kb,
    get_main_menu_kb,
    get_back_kb,
    get_confirm_kb,
)
from ..states import CampaignStates

router = Router(name="campaigns")


def get_campaign_service(session: AsyncSession) -> CampaignService:
    """Create campaign service."""
    return CampaignService(
        campaign_repo=PostgresCampaignRepository(session),
        account_repo=PostgresAccountRepository(session),
        target_repo=PostgresUserTargetRepository(session),
    )


# =============================================================================
# Menu and List
# =============================================================================

async def _get_campaign_counts(session: AsyncSession) -> dict:
    """Get campaign counts by status."""
    repo = PostgresCampaignRepository(session)
    active = await repo.list_by_status(CampaignStatus.ACTIVE)
    paused = await repo.list_by_status(CampaignStatus.PAUSED)
    drafts = await repo.list_by_status(CampaignStatus.DRAFT)
    return {
        "active_count": len(active),
        "paused_count": len(paused),
        "draft_count": len(drafts),
    }


@router.message(F.text == "📢 Кампании")
async def campaigns_menu(message: Message, session: AsyncSession) -> None:
    """Show campaigns menu."""
    counts = await _get_campaign_counts(session)
    total = counts["active_count"] + counts["paused_count"] + counts["draft_count"]

    await message.answer(
        f"📢 <b>Кампании</b> ({total})\n\n"
        "Выберите действие:",
        reply_markup=get_campaigns_menu_kb(**counts),
    )


@router.callback_query(F.data == "campaigns:menu")
async def campaigns_menu_callback(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show campaigns menu via callback."""
    counts = await _get_campaign_counts(session)
    total = counts["active_count"] + counts["paused_count"] + counts["draft_count"]

    await callback.message.edit_text(
        f"📢 <b>Кампании</b> ({total})\n\n"
        "Выберите действие:",
        reply_markup=get_campaigns_menu_kb(**counts),
    )
    await callback.answer()


@router.callback_query(F.data == "campaigns:list")
async def campaigns_list(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show list of all campaigns."""
    repo = PostgresCampaignRepository(session)
    campaigns = await repo.list_all(limit=50)
    
    if not campaigns:
        await callback.message.edit_text(
            "📢 <b>Кампании</b>\n\n"
            "Список пуст. Создайте первую кампанию.",
            reply_markup=get_campaigns_menu_kb(),
        )
        await callback.answer()
        return
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    
    builder = InlineKeyboardBuilder()
    
    for campaign in campaigns:
        status_emoji = {
            "draft": "📝",
            "ready": "🔵",
            "active": "🟢",
            "paused": "🟡",
            "completed": "✅",
            "cancelled": "❌",
        }.get(campaign.status.value, "❓")
        
        builder.row(
            InlineKeyboardButton(
                text=f"{status_emoji} {campaign.name}",
                callback_data=f"campaign:view:{campaign.id}",
            ),
        )
    
    builder.row(
        InlineKeyboardButton(text="◀️ Меню кампаний", callback_data="campaigns:menu"),
    )
    
    await callback.message.edit_text(
        f"📢 <b>Кампании</b> ({len(campaigns)})\n\n"
        "📝 Черновик | 🔵 Готова | 🟢 Активна | 🟡 Пауза | ✅ Завершена",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "campaigns:active")
async def campaigns_active(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show active campaigns."""
    service = get_campaign_service(session)
    campaigns = await service.list_active_campaigns()
    
    if not campaigns:
        await callback.answer("Нет активных кампаний", show_alert=True)
        return
    
    text = f"🟢 <b>Активные кампании</b> ({len(campaigns)})\n\n"
    
    for c in campaigns:
        text += f"• <b>{c.name}</b>\n"
        text += f"  Таргетов: {c.stats.total_targets} | "
        text += f"Контактов: {c.stats.contacted} | "
        text += f"Конверсий: {c.stats.goals_reached}\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_kb("campaigns:list"),
    )
    await callback.answer()


# =============================================================================
# View Campaign
# =============================================================================

@router.callback_query(F.data.startswith("campaign:view:"))
async def view_campaign(callback: CallbackQuery, session: AsyncSession) -> None:
    """View campaign details."""
    campaign_id = UUID(callback.data.split(":")[-1])
    
    service = get_campaign_service(session)
    
    try:
        campaign = await service.get_campaign(campaign_id)
        stats = await service.get_campaign_stats(campaign_id)
    except Exception:
        await callback.answer("Кампания не найдена", show_alert=True)
        return
    
    status_text = {
        CampaignStatus.DRAFT: "📝 Черновик",
        CampaignStatus.READY: "🔵 Готова",
        CampaignStatus.ACTIVE: "🟢 Активна",
        CampaignStatus.PAUSED: "🟡 На паузе",
        CampaignStatus.COMPLETED: "✅ Завершена",
        CampaignStatus.CANCELLED: "❌ Отменена",
    }.get(campaign.status, "❓")
    
    text = (
        f"📢 <b>{campaign.name}</b>\n\n"
        f"<b>Статус:</b> {status_text}\n"
        f"<b>Описание:</b> {campaign.description or '—'}\n\n"
        f"<b>Статистика:</b>\n"
        f"• Таргетов: {stats['targets']['total']}\n"
        f"• В ожидании: {stats['targets']['pending']}\n"
        f"• Контактов: {stats['targets']['contacted']}\n"
        f"• В процессе: {stats['targets']['in_progress']}\n"
        f"• Конверсий: {stats['targets']['converted']}\n"
        f"• Провалов: {stats['targets']['failed']}\n\n"
        f"<b>Метрики:</b>\n"
        f"• Response rate: {stats['stats']['response_rate']:.1f}%\n"
        f"• Conversion rate: {stats['stats']['conversion_rate']:.1f}%\n"
        f"• Сообщений: {stats['stats']['total_messages']}\n\n"
        f"<b>Аккаунтов:</b> {stats['accounts']}\n"
    )
    
    if campaign.ai_model:
        text += f"<b>AI модель:</b> {campaign.ai_model}\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_campaign_actions_kb(campaign.id, campaign.status.value),
    )
    await callback.answer()


# =============================================================================
# Create Campaign
# =============================================================================

@router.callback_query(F.data == "campaigns:create")
async def create_campaign_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start campaign creation."""
    await state.set_state(CampaignStates.waiting_name)
    
    await callback.message.edit_text(
        "➕ <b>Создание кампании</b>\n\n"
        "Введите название кампании:",
    )
    await callback.message.answer(
        "Ожидаю название...",
        reply_markup=get_cancel_kb(),
    )
    await callback.answer()


@router.message(CampaignStates.waiting_name)
async def create_campaign_name(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    admin_user,
) -> None:
    """Receive campaign name."""
    name = message.text.strip()
    
    if len(name) < 3:
        await message.answer("❌ Название должно быть не менее 3 символов.")
        return
    
    service = get_campaign_service(session)
    
    try:
        campaign = await service.create_campaign(
            name=name,
            owner_telegram_id=admin_user.id,
        )
        
        await state.clear()
        await message.answer(
            f"✅ <b>Кампания создана!</b>\n\n"
            f"Название: {name}\n"
            f"ID: <code>{campaign.id}</code>\n\n"
            f"Теперь настройте кампанию:",
            reply_markup=get_main_menu_kb(),
        )
        
        # Show configure menu
        from aiogram.types import InlineKeyboardButton
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        
        await message.answer(
            "⚙️ <b>Настройка кампании</b>",
            reply_markup=get_campaign_configure_kb(campaign.id),
        )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


# =============================================================================
# Configure Campaign
# =============================================================================

@router.callback_query(F.data.startswith("campaign:configure:"))
async def configure_campaign(callback: CallbackQuery) -> None:
    """Show configuration menu."""
    campaign_id = UUID(callback.data.split(":")[-1])
    
    await callback.message.edit_text(
        "⚙️ <b>Настройка кампании</b>\n\n"
        "Выберите раздел:",
        reply_markup=get_campaign_configure_kb(campaign_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("campaign:cfg:prompt:"))
async def configure_prompt_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start prompt configuration."""
    campaign_id = callback.data.split(":")[-1]
    await state.update_data(campaign_id=campaign_id)
    await state.set_state(CampaignStates.waiting_system_prompt)
    
    await callback.message.edit_text(
        "📝 <b>Настройка промпта</b>\n\n"
        "Введите системный промпт для AI.\n\n"
        "Это основные инструкции для модели: стиль общения, "
        "персона, ограничения.\n\n"
        "<i>Пример:</i>\n"
        "<code>Ты дружелюбный собеседник. Общайся неформально, "
        "проявляй интерес к хобби собеседника. "
        "Постепенно подводи разговор к теме инвестиций.</code>",
    )
    await callback.message.answer(
        "Ожидаю системный промпт...",
        reply_markup=get_cancel_kb(),
    )
    await callback.answer()


@router.message(CampaignStates.waiting_system_prompt)
async def receive_system_prompt(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Receive system prompt."""
    prompt = message.text.strip()
    
    if len(prompt) < 20:
        await message.answer("❌ Промпт слишком короткий (минимум 20 символов).")
        return
    
    data = await state.get_data()
    campaign_id = UUID(data["campaign_id"])
    
    service = get_campaign_service(session)
    
    try:
        await service.configure_prompt(
            campaign_id=campaign_id,
            system_prompt=prompt,
        )
        
        await state.clear()
        await message.answer(
            "✅ <b>Промпт сохранён!</b>\n\n"
            f"Длина: {len(prompt)} символов",
            reply_markup=get_main_menu_kb(),
        )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@router.callback_query(F.data.startswith("campaign:cfg:goal:"))
async def configure_goal_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start goal configuration."""
    campaign_id = callback.data.split(":")[-1]
    await state.update_data(campaign_id=campaign_id)
    await state.set_state(CampaignStates.waiting_goal_message)
    
    await callback.message.edit_text(
        "🎯 <b>Настройка цели</b>\n\n"
        "Введите целевое сообщение — то, что AI должен "
        "в итоге донести до собеседника.\n\n"
        "<i>Пример:</i>\n"
        "<code>Кстати, есть отличный канал про инвестиции @example — "
        "там много полезного для начинающих.</code>",
    )
    await callback.message.answer(
        "Ожидаю целевое сообщение...",
        reply_markup=get_cancel_kb(),
    )
    await callback.answer()


@router.message(CampaignStates.waiting_goal_message)
async def receive_goal_message(
    message: Message,
    state: FSMContext,
) -> None:
    """Receive goal message, then ask for URL."""
    goal_message = message.text.strip()
    
    await state.update_data(goal_message=goal_message)
    await state.set_state(CampaignStates.waiting_goal_url)
    
    await message.answer(
        "🔗 <b>Ссылка для отправки</b>\n\n"
        "Теперь введите ссылку (или несколько через пробел), "
        "которую бот отправит после согласия пользователя.\n\n"
        "<i>Пример:</i>\n"
        "<code>https://t.me/your_channel</code>\n\n"
        "Или несколько:\n"
        "<code>https://t.me/channel1 https://t.me/channel2</code>",
        reply_markup=get_cancel_kb(),
    )


@router.message(CampaignStates.waiting_goal_url)
async def receive_goal_url(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Receive goal URL and save."""
    goal_url = message.text.strip()
    
    data = await state.get_data()
    campaign_id = UUID(data["campaign_id"])
    goal_message = data["goal_message"]
    
    service = get_campaign_service(session)
    
    try:
        await service.configure_goal(
            campaign_id=campaign_id,
            target_message=goal_message,
            target_url=goal_url,
        )
        
        await state.clear()
        await message.answer(
            "✅ <b>Цель сохранена!</b>\n\n"
            f"📝 Сообщение: <i>{goal_message[:50]}...</i>\n"
            f"🔗 Ссылка: <code>{goal_url}</code>",
            reply_markup=get_main_menu_kb(),
        )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


# =============================================================================
# Campaign Actions
# =============================================================================

@router.callback_query(F.data.startswith("campaign:start:"))
async def start_campaign(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Start a campaign - first check proxies."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.infrastructure.proxy.checker import get_proxy_checker
    from src.infrastructure.database.repositories import PostgresProxyRepository
    
    campaign_id = UUID(callback.data.split(":")[-1])
    
    # Save to state for subsequent handlers
    await state.update_data(current_campaign_id=str(campaign_id))
    
    account_repo = PostgresAccountRepository(session)
    proxy_repo = PostgresProxyRepository(session)
    campaign_repo = PostgresCampaignRepository(session)
    
    campaign = await campaign_repo.get_by_id(campaign_id)
    if not campaign:
        await callback.answer("❌ Кампания не найдена", show_alert=True)
        return
    
    # Get campaign accounts
    accounts = await account_repo.list_by_campaign(campaign_id)
    
    if not accounts:
        await callback.answer("❌ Нет аккаунтов в кампании", show_alert=True)
        return
    
    await callback.answer("⏳ Проверяю прокси аккаунтов...")
    
    # Check proxies
    checker = get_proxy_checker()
    problems = []
    ok_count = 0
    auto_fixed = 0  # Count of auto-fixed proxy issues

    for acc in accounts:
        if not acc.proxy_id:
            # Try to auto-assign a proxy
            available = await proxy_repo.list_available()
            if available:
                new_proxy = available[0]
                acc.proxy_id = new_proxy.id
                await account_repo.save(acc)
                ok_count += 1
                auto_fixed += 1
                continue

            problems.append({
                "account_id": str(acc.id),
                "phone": acc.phone,
                "issue": "no_proxy",
                "message": "Нет прокси"
            })
            continue

        proxy = await proxy_repo.get_by_id(acc.proxy_id)
        if not proxy:
            # Try to auto-assign a proxy
            available = await proxy_repo.list_available()
            if available:
                new_proxy = available[0]
                acc.proxy_id = new_proxy.id
                await account_repo.save(acc)
                ok_count += 1
                auto_fixed += 1
                continue

            problems.append({
                "account_id": str(acc.id),
                "phone": acc.phone,
                "issue": "proxy_missing",
                "message": "Прокси удалён"
            })
            continue

        # Quick check (outside session)
        is_working, latency, error = await checker.check_single(acc.proxy_id)

        if is_working:
            ok_count += 1
        else:
            # Auto-retry: try to find a working proxy
            max_retries = 3
            found_working = False
            tried_proxy_ids = [acc.proxy_id]
            current_proxy_id = acc.proxy_id

            for _ in range(max_retries):
                # Re-read proxy to get fresh version (avoid optimistic lock)
                fresh_proxy = await proxy_repo.get_by_id(current_proxy_id)
                if fresh_proxy:
                    fresh_proxy.mark_failed()
                    await proxy_repo.save(fresh_proxy)

                # Find another available proxy
                available = await proxy_repo.list_available()
                new_proxy = None
                for p in available:
                    if p.id not in tried_proxy_ids:
                        new_proxy = p
                        break

                if not new_proxy:
                    break  # No more proxies to try

                tried_proxy_ids.append(new_proxy.id)
                current_proxy_id = new_proxy.id

                # Check new proxy
                is_working, latency, error = await checker.check_single(new_proxy.id)
                if is_working:
                    # Re-read account to get fresh version
                    fresh_acc = await account_repo.get_by_id(acc.id)
                    if fresh_acc:
                        fresh_acc.proxy_id = new_proxy.id
                        await account_repo.save(fresh_acc)
                    ok_count += 1
                    auto_fixed += 1
                    found_working = True
                    break
                # If not working, loop continues and marks this proxy as failed

            if not found_working:
                problems.append({
                    "account_id": str(acc.id),
                    "phone": acc.phone,
                    "proxy_id": str(proxy.id),
                    "proxy_addr": f"{proxy.host}:{proxy.port}",
                    "issue": "proxy_failed",
                    "message": error or "Не отвечает"
                })
    
    # All OK - start immediately
    if not problems:
        service = get_campaign_service(session)
        try:
            await service.activate_campaign(campaign_id)
            auto_fixed_text = ""
            if auto_fixed > 0:
                auto_fixed_text = f"🔄 Автозамена прокси: {auto_fixed}\n"
            await callback.message.edit_text(
                f"✅ <b>Кампания запущена!</b>\n\n"
                f"📢 {campaign.name}\n"
                f"📱 Аккаунтов: {len(accounts)}\n"
                f"🌐 Все прокси работают\n"
                f"{auto_fixed_text}\n"
                f"Рассылка началась.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ К кампании", callback_data=f"campaign:view:{campaign_id}")]
                ])
            )
            return
        except Exception as e:
            await callback.answer(f"❌ {e}", show_alert=True)
            return

    # Has problems - show warning
    auto_fixed_text = ""
    if auto_fixed > 0:
        auto_fixed_text = f"🔄 Автозамена: {auto_fixed}\n"
    text = (
        f"⚠️ <b>Проблемы с прокси!</b>\n\n"
        f"📢 {campaign.name}\n"
        f"✅ Работает: {ok_count}/{len(accounts)}\n"
        f"❌ Проблемы: {len(problems)}\n"
        f"{auto_fixed_text}\n"
    )
    
    for p in problems[:5]:
        text += f"• <b>{p['phone']}</b>: {p['message']}\n"
    
    if len(problems) > 5:
        text += f"... и ещё {len(problems) - 5} проблем\n"
    
    text += "\n<b>Выберите действие:</b>"
    
    buttons = []
    
    # Quick fix buttons for first 3 problems (use short callbacks)
    for p in problems[:3]:
        if p["issue"] in ["no_proxy", "proxy_failed", "proxy_missing"]:
            buttons.append([InlineKeyboardButton(
                text=f"🔄 Заменить для {p['phone']}",
                callback_data=f"cfp:{p['account_id'][:18]}",  # Short: campaign fix proxy (18 chars of UUID)
            )])
    
    buttons.extend([
        [InlineKeyboardButton(
            text="⚡ Запустить всё равно",
            callback_data=f"campaign:forcestart:{campaign_id}",
        )],
        [InlineKeyboardButton(
            text="❌ Отмена",
            callback_data=f"campaign:view:{campaign_id}",
        )],
    ])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("campaign:forcestart:"))
async def force_start_campaign(callback: CallbackQuery, session: AsyncSession) -> None:
    """Force start campaign ignoring proxy issues."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    campaign_id = UUID(callback.data.split(":")[-1])
    service = get_campaign_service(session)
    
    try:
        await service.activate_campaign(campaign_id)
        
        # Show success with back button
        await callback.message.edit_text(
            "✅ <b>Кампания запущена!</b>\n\n"
            "Рассылка началась. Воркеры начнут отправку сообщений.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ К кампании", callback_data=f"campaign:view:{campaign_id}")]
            ])
        )
        await callback.answer()
        
    except Exception as e:
        await callback.answer(f"❌ {str(e)[:100]}", show_alert=True)


@router.callback_query(F.data.startswith("cfp:"))
async def fix_account_proxy(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Show available proxies to replace failed one (short callback)."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.infrastructure.database.repositories import PostgresProxyRepository
    
    # Get campaign_id from state
    data = await state.get_data()
    campaign_id_str = data.get("current_campaign_id")
    if not campaign_id_str:
        await callback.answer("❌ Сессия истекла", show_alert=True)
        return
    
    campaign_id = UUID(campaign_id_str)
    
    # Account ID prefix from callback, find full account
    account_id_prefix = callback.data.split(":")[1]
    
    account_repo = PostgresAccountRepository(session)
    proxy_repo = PostgresProxyRepository(session)
    
    # Find account by prefix
    accounts = await account_repo.list_by_campaign(campaign_id)
    account = None
    for acc in accounts:
        if str(acc.id).startswith(account_id_prefix):
            account = acc
            break
    
    if not account:
        await callback.answer("❌ Аккаунт не найден", show_alert=True)
        return
    
    # Save account_id to state
    await state.update_data(current_account_id=str(account.id))
    
    # Get available (unassigned) proxies
    available = await proxy_repo.list_available()
    
    if not available:
        await callback.answer("❌ Нет свободных прокси!", show_alert=True)
        return
    
    text = (
        f"🔄 <b>Замена прокси</b>\n\n"
        f"📱 Аккаунт: {account.phone}\n\n"
        f"Выберите новый прокси:"
    )
    
    buttons = []
    
    for proxy in available[:8]:
        latency = f" ({proxy.last_check_latency_ms}ms)" if proxy.last_check_latency_ms else ""
        status = "✅" if proxy.status.value == "active" else "⚪"
        buttons.append([InlineKeyboardButton(
            text=f"{status} {proxy.host}:{proxy.port}{latency}",
            callback_data=f"csp:{proxy.id}",  # Short: campaign set proxy
        )])
    
    buttons.append([InlineKeyboardButton(
        text="◀️ Назад",
        callback_data=f"campaign:start:{campaign_id}",
    )])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("csp:"))
async def set_account_proxy(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Assign new proxy to account (short callback)."""
    proxy_id = UUID(callback.data.split(":")[1])
    
    # Get from state
    data = await state.get_data()
    campaign_id_str = data.get("current_campaign_id")
    account_id_str = data.get("current_account_id")
    
    if not campaign_id_str or not account_id_str:
        await callback.answer("❌ Сессия истекла", show_alert=True)
        return
    
    campaign_id = UUID(campaign_id_str)
    account_id = UUID(account_id_str)
    
    account_repo = PostgresAccountRepository(session)
    
    account = await account_repo.get_by_id(account_id)
    if not account:
        await callback.answer("❌ Аккаунт не найден", show_alert=True)
        return
    
    # Update proxy
    account.proxy_id = proxy_id
    await account_repo.save(account)
    
    # Show success with button to re-check
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    await callback.message.edit_text(
        "✅ <b>Прокси назначен!</b>\n\n"
        "Нажмите кнопку чтобы повторить проверку.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Проверить и запустить", callback_data=f"campaign:start:{campaign_id}")],
            [InlineKeyboardButton(text="◀️ К кампании", callback_data=f"campaign:view:{campaign_id}")]
        ])
    )
    await callback.answer()


@router.callback_query(F.data.startswith("campaign:pause:"))
async def pause_campaign(callback: CallbackQuery, session: AsyncSession) -> None:
    """Pause a campaign."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    campaign_id = UUID(callback.data.split(":")[-1])
    service = get_campaign_service(session)
    
    try:
        await service.pause_campaign(campaign_id)
        
        await callback.message.edit_text(
            "⏸ <b>Кампания на паузе</b>\n\n"
            "Рассылка приостановлена.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ К кампании", callback_data=f"campaign:view:{campaign_id}")]
            ])
        )
        await callback.answer()
        
    except Exception as e:
        await callback.answer(f"❌ {str(e)[:100]}", show_alert=True)


# =============================================================================
# Load Targets
# =============================================================================

@router.callback_query(F.data.startswith("campaign:cfg:targets:"))
async def load_targets_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start targets loading."""
    campaign_id = callback.data.split(":")[-1]
    await state.update_data(campaign_id=campaign_id)
    await state.set_state(CampaignStates.waiting_targets_file)
    
    await callback.message.edit_text(
        "👥 <b>Загрузка таргетов</b>\n\n"
        "Отправьте файл со списком пользователей.\n\n"
        "<b>Поддерживаемые форматы:</b>\n"
        "• TXT — один username или user_id на строку\n"
        "• CSV — колонки: username, telegram_id, first_name\n\n"
        "<i>Пример TXT:</i>\n"
        "<code>username1\n"
        "username2\n"
        "123456789</code>",
    )
    await callback.message.answer(
        "Ожидаю файл...",
        reply_markup=get_cancel_kb(),
    )
    await callback.answer()


@router.message(CampaignStates.waiting_targets_file, F.document)
async def receive_targets_file(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Receive and process targets file."""
    import os
    from pathlib import Path

    doc = message.document

    if not doc.file_name.endswith((".txt", ".csv")):
        await message.answer("❌ Поддерживаются только .txt и .csv файлы")
        return

    data = await state.get_data()
    campaign_id = UUID(data["campaign_id"])

    # Download file
    file = await message.bot.download(doc)
    content = file.read().decode("utf-8")

    # Save file to data/targets/ for later cleanup
    targets_dir = Path("data/targets")
    targets_dir.mkdir(parents=True, exist_ok=True)
    saved_file_path = targets_dir / f"{campaign_id}_{doc.file_name}"

    with open(saved_file_path, "w", encoding="utf-8") as f:
        f.write(content)

    # Parse targets
    targets = []
    lines = content.strip().split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Try to parse as user_id
        if line.isdigit():
            targets.append({"telegram_id": int(line)})
        else:
            # Treat as username
            username = line.lstrip("@")
            targets.append({"username": username})

    if not targets:
        await message.answer("❌ Не найдено ни одного таргета в файле.")
        return

    # Add to campaign
    service = get_campaign_service(session)

    try:
        count = await service.add_targets(
            campaign_id=campaign_id,
            targets=targets,
            source=doc.file_name,
        )

        # Save targets file path to campaign
        campaign_repo = PostgresCampaignRepository(session)
        campaign = await campaign_repo.get_by_id(campaign_id)
        if campaign:
            campaign.sending.targets_file_path = str(saved_file_path)
            await campaign_repo.save(campaign)

        await state.clear()
        await message.answer(
            f"✅ <b>Таргеты загружены!</b>\n\n"
            f"Добавлено: {count}\n"
            f"Источник: {doc.file_name}",
            reply_markup=get_main_menu_kb(),
        )

    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


# =============================================================================
# Campaign Dialogues
# =============================================================================

@router.callback_query(F.data.startswith("campaign:dialogues:"))
async def campaign_dialogues(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show campaign dialogues."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.infrastructure.database.repositories import PostgresDialogueRepository
    
    campaign_id = UUID(callback.data.split(":")[-1])
    
    dialogue_repo = PostgresDialogueRepository(session)
    campaign_repo = PostgresCampaignRepository(session)
    
    campaign = await campaign_repo.get_by_id(campaign_id)
    if not campaign:
        await callback.answer("Кампания не найдена", show_alert=True)
        return
    
    dialogues = await dialogue_repo.list_by_campaign(campaign_id, limit=100)
    
    if not dialogues:
        await callback.message.edit_text(
            f"💬 <b>Диалоги кампании</b>\n\n"
            f"📢 {campaign.name}\n\n"
            f"Диалогов пока нет.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data=f"campaign:view:{campaign_id}",
                )],
            ]),
        )
        await callback.answer()
        return
    
    # Count by status
    by_status = {}
    for d in dialogues:
        status = d.status.value
        by_status[status] = by_status.get(status, 0) + 1
    
    goals_reached = sum(1 for d in dialogues if d.goal_reached)
    
    text = (
        f"💬 <b>Диалоги кампании</b>\n\n"
        f"📢 {campaign.name}\n\n"
        f"<b>Всего:</b> {len(dialogues)}\n"
        f"<b>Достигнута цель:</b> {goals_reached}\n\n"
        f"<b>По статусам:</b>\n"
    )
    
    status_emoji = {
        "pending": "⏳",
        "active": "🟢",
        "waiting": "🔵",
        "completed": "✅",
        "failed": "❌",
        "blocked": "⛔",
    }
    
    for status, count in sorted(by_status.items()):
        emoji = status_emoji.get(status, "❓")
        text += f"  {emoji} {status}: {count}\n"
    
    text += "\n<b>Последние диалоги:</b>\n"
    
    # Show last 5 dialogues
    for d in dialogues[:5]:
        emoji = status_emoji.get(d.status.value, "❓")
        goal = "🎯" if d.goal_reached else ""
        username = f"@{d.target_username}" if d.target_username else str(d.target_telegram_id)
        text += f"{emoji}{goal} {username} — {d.messages_count} сообщ.\n"
    
    buttons = [
        [InlineKeyboardButton(
            text="🟢 Активные",
            callback_data=f"campaign:dialogues:active:{campaign_id}",
        )],
        [InlineKeyboardButton(
            text="🎯 С достигнутой целью",
            callback_data=f"campaign:dialogues:goal:{campaign_id}",
        )],
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"campaign:view:{campaign_id}",
        )],
    ]
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("campaign:dialogues:active:"))
async def campaign_dialogues_active(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show active dialogues for campaign."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.infrastructure.database.repositories import PostgresDialogueRepository
    from src.domain.entities import DialogueStatus
    
    campaign_id = UUID(callback.data.split(":")[-1])
    
    dialogue_repo = PostgresDialogueRepository(session)
    dialogues = await dialogue_repo.list_by_campaign(campaign_id, limit=100)
    
    active = [d for d in dialogues if d.status == DialogueStatus.ACTIVE]
    
    if not active:
        await callback.answer("Нет активных диалогов", show_alert=True)
        return
    
    text = f"🟢 <b>Активные диалоги</b> ({len(active)})\n\n"
    
    for d in active[:10]:
        username = f"@{d.target_username}" if d.target_username else str(d.target_telegram_id)
        last_msg = d.last_message_at.strftime("%H:%M %d.%m") if d.last_message_at else "—"
        text += f"• {username} — {d.messages_count} сообщ. ({last_msg})\n"
    
    if len(active) > 10:
        text += f"\n... и ещё {len(active) - 10}"
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="◀️ Назад",
                callback_data=f"campaign:dialogues:{campaign_id}",
            )],
        ]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("campaign:dialogues:goal:"))
async def campaign_dialogues_goal(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show dialogues where goal was reached."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.infrastructure.database.repositories import PostgresDialogueRepository
    
    campaign_id = UUID(callback.data.split(":")[-1])
    
    dialogue_repo = PostgresDialogueRepository(session)
    dialogues = await dialogue_repo.list_by_campaign(campaign_id, limit=100)
    
    with_goal = [d for d in dialogues if d.goal_reached]
    
    if not with_goal:
        await callback.answer("Нет диалогов с достигнутой целью", show_alert=True)
        return
    
    text = f"🎯 <b>Достигнута цель</b> ({len(with_goal)})\n\n"
    
    for d in with_goal[:10]:
        username = f"@{d.target_username}" if d.target_username else str(d.target_telegram_id)
        goal_at = d.goal_reached_at.strftime("%H:%M %d.%m") if d.goal_reached_at else "—"
        text += f"• {username} — {d.messages_count} сообщ. (цель: {goal_at})\n"
    
    if len(with_goal) > 10:
        text += f"\n... и ещё {len(with_goal) - 10}"
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="◀️ Назад",
                callback_data=f"campaign:dialogues:{campaign_id}",
            )],
        ]),
    )
    await callback.answer()


# =============================================================================
# Campaign Accounts Management
# =============================================================================

@router.callback_query(F.data.startswith("campaign:accounts:"))
async def campaign_accounts(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Show and manage campaign accounts."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    campaign_id = UUID(callback.data.split(":")[-1])
    
    # Save campaign_id to state for subsequent handlers
    await state.update_data(current_campaign_id=str(campaign_id))
    
    campaign_repo = PostgresCampaignRepository(session)
    account_repo = PostgresAccountRepository(session)
    
    campaign = await campaign_repo.get_by_id(campaign_id)
    if not campaign:
        await callback.answer("Кампания не найдена", show_alert=True)
        return
    
    # Get assigned accounts
    assigned_accounts = await account_repo.list_by_campaign(campaign_id)
    
    # Get available accounts (not assigned to any campaign)
    all_accounts = await account_repo.list_all(limit=100)
    available = [a for a in all_accounts if not a.campaign_id]
    
    text = (
        f"📱 <b>Аккаунты кампании</b>\n\n"
        f"📢 {campaign.name}\n\n"
        f"<b>Назначено:</b> {len(assigned_accounts)}\n"
        f"<b>Доступно:</b> {len(available)}\n\n"
    )
    
    if assigned_accounts:
        text += "<b>Назначенные аккаунты:</b>\n"
        for acc in assigned_accounts[:5]:
            status_emoji = {
                "active": "🟢", "ready": "🔵", "paused": "🟡",
                "error": "🔴", "banned": "⛔"
            }.get(acc.status.value, "⚪")
            text += f"{status_emoji} {acc.phone}\n"
        if len(assigned_accounts) > 5:
            text += f"... и ещё {len(assigned_accounts) - 5}\n"
    
    buttons = []
    
    # Add group button first
    from src.infrastructure.database.repositories import AccountGroupRepository
    group_repo = AccountGroupRepository(session)
    groups = await group_repo.get_all()
    groups_with_accounts = [g for g in groups if g.account_count > 0]

    if groups_with_accounts:
        buttons.append([InlineKeyboardButton(
            text=f"📁 Добавить группу ({len(groups_with_accounts)})",
            callback_data=f"cag:{campaign_id}",  # Short: campaign add group
        )])

    # Add available accounts buttons (short callback - only acc.id)
    if available:
        text += "\n<b>Добавить аккаунт:</b>"
        for acc in available[:5]:
            buttons.append([InlineKeyboardButton(
                text=f"➕ {acc.phone}",
                callback_data=f"caa:{acc.id}",  # Short: campaign add account
            )])

    # Remove buttons for assigned accounts
    if assigned_accounts:
        buttons.append([InlineKeyboardButton(
            text="➖ Убрать аккаунт",
            callback_data=f"cra:{campaign_id}",  # Short: campaign remove account
        )])
    
    buttons.append([InlineKeyboardButton(
        text="◀️ Назад",
        callback_data=f"campaign:view:{campaign_id}",
    )])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("caa:"))
async def campaign_add_account(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Add account to campaign (short callback)."""
    account_id = UUID(callback.data.split(":")[1])
    
    # Get campaign_id from state
    data = await state.get_data()
    campaign_id_str = data.get("current_campaign_id")
    
    if not campaign_id_str:
        await callback.answer("❌ Сессия истекла, откройте кампанию заново", show_alert=True)
        return
    
    campaign_id = UUID(campaign_id_str)
    service = get_campaign_service(session)
    
    try:
        await service.add_account_to_campaign(campaign_id, account_id)
        await callback.answer("✅ Аккаунт добавлен!", show_alert=True)
        
        # Inline refresh - rebuild the accounts view
        await _show_campaign_accounts(callback.message, session, campaign_id, state)
        
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)[:100]}", show_alert=True)


@router.callback_query(F.data.startswith("cag:"))
async def campaign_add_group_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Show available groups to add to campaign."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.infrastructure.database.repositories import AccountGroupRepository

    campaign_id = UUID(callback.data.split(":")[1])
    await state.update_data(current_campaign_id=str(campaign_id))

    group_repo = AccountGroupRepository(session)
    groups = await group_repo.get_all()

    # Filter groups with available accounts (not already in a campaign)
    account_repo = PostgresAccountRepository(session)
    available_groups = []

    for group in groups:
        if group.account_count > 0:
            # Check how many accounts from this group are available
            available_count = 0
            for acc_id in group.account_ids:
                acc = await account_repo.get_by_id(acc_id)
                if acc and not acc.campaign_id:
                    available_count += 1
            if available_count > 0:
                available_groups.append((group, available_count))

    buttons = []
    for group, available_count in available_groups:
        buttons.append([InlineKeyboardButton(
            text=f"📁 {group.name} ({available_count} доступно)",
            callback_data=f"cagc:{group.id}",  # campaign add group confirm
        )])

    buttons.append([InlineKeyboardButton(
        text="◀️ Назад",
        callback_data=f"campaign:accounts:{campaign_id}",
    )])

    if not available_groups:
        text = (
            "📁 <b>Добавить группу</b>\n\n"
            "Нет доступных групп с свободными аккаунтами.\n\n"
            "Все аккаунты из групп уже назначены на кампании."
        )
    else:
        text = (
            "📁 <b>Выберите группу для добавления</b>\n\n"
            "Все свободные аккаунты из группы будут добавлены в кампанию."
        )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cagc:"))
async def campaign_add_group_confirm(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Add all available accounts from group to campaign."""
    from src.infrastructure.database.repositories import AccountGroupRepository

    group_id = UUID(callback.data.split(":")[1])

    data = await state.get_data()
    campaign_id_str = data.get("current_campaign_id")
    if not campaign_id_str:
        await callback.answer("❌ Сессия истекла", show_alert=True)
        return

    campaign_id = UUID(campaign_id_str)

    group_repo = AccountGroupRepository(session)
    account_repo = PostgresAccountRepository(session)

    group = await group_repo.get_by_id(group_id)
    if not group:
        await callback.answer("❌ Группа не найдена", show_alert=True)
        return

    service = get_campaign_service(session)
    added_count = 0
    errors = 0

    for acc_id in group.account_ids:
        acc = await account_repo.get_by_id(acc_id)
        if acc and not acc.campaign_id:
            try:
                await service.add_account_to_campaign(campaign_id, acc_id)
                added_count += 1
            except Exception:
                errors += 1

    await callback.answer(
        f"✅ Добавлено {added_count} аккаунтов" + (f" ({errors} ошибок)" if errors else ""),
        show_alert=True,
    )

    # Refresh accounts view
    await _show_campaign_accounts(callback.message, session, campaign_id, state)


async def _show_campaign_accounts(message, session: AsyncSession, campaign_id: UUID, state: FSMContext) -> None:
    """Helper to show campaign accounts (used by multiple handlers)."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    # Save campaign_id to state
    await state.update_data(current_campaign_id=str(campaign_id))
    
    campaign_repo = PostgresCampaignRepository(session)
    account_repo = PostgresAccountRepository(session)
    
    campaign = await campaign_repo.get_by_id(campaign_id)
    if not campaign:
        return
    
    assigned_accounts = await account_repo.list_by_campaign(campaign_id)
    all_accounts = await account_repo.list_all(limit=100)
    available = [a for a in all_accounts if not a.campaign_id]
    
    text = (
        f"📱 <b>Аккаунты кампании</b>\n\n"
        f"📢 {campaign.name}\n\n"
        f"<b>Назначено:</b> {len(assigned_accounts)}\n"
        f"<b>Доступно:</b> {len(available)}\n\n"
    )
    
    if assigned_accounts:
        text += "<b>Назначенные аккаунты:</b>\n"
        for acc in assigned_accounts[:5]:
            status_emoji = {
                "active": "🟢", "ready": "🔵", "paused": "🟡",
                "error": "🔴", "banned": "⛔"
            }.get(acc.status.value, "⚪")
            text += f"{status_emoji} {acc.phone}\n"
        if len(assigned_accounts) > 5:
            text += f"... и ещё {len(assigned_accounts) - 5}\n"
    
    buttons = []

    # Add group button first
    from src.infrastructure.database.repositories import AccountGroupRepository
    group_repo = AccountGroupRepository(session)
    groups = await group_repo.get_all()
    groups_with_accounts = [g for g in groups if g.account_count > 0]

    if groups_with_accounts:
        buttons.append([InlineKeyboardButton(
            text=f"📁 Добавить группу ({len(groups_with_accounts)})",
            callback_data=f"cag:{campaign_id}",
        )])

    if available:
        text += "\n<b>Добавить аккаунт:</b>"
        for acc in available[:5]:
            buttons.append([InlineKeyboardButton(
                text=f"➕ {acc.phone}",
                callback_data=f"caa:{acc.id}",
            )])

    if assigned_accounts:
        buttons.append([InlineKeyboardButton(
            text="➖ Убрать аккаунт",
            callback_data=f"cra:{campaign_id}",
        )])

    buttons.append([InlineKeyboardButton(
        text="◀️ Назад",
        callback_data=f"campaign:view:{campaign_id}",
    )])

    await message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("cra:"))
async def campaign_remove_account_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Show menu to remove account from campaign (short callback)."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    campaign_id = UUID(callback.data.split(":")[1])
    
    # Save to state
    await state.update_data(current_campaign_id=str(campaign_id))
    
    account_repo = PostgresAccountRepository(session)
    assigned = await account_repo.list_by_campaign(campaign_id)
    
    if not assigned:
        await callback.answer("Нет назначенных аккаунтов", show_alert=True)
        return
    
    buttons = []
    for acc in assigned:
        buttons.append([InlineKeyboardButton(
            text=f"➖ {acc.phone}",
            callback_data=f"cdr:{acc.id}",  # Short: campaign do remove
        )])
    
    buttons.append([InlineKeyboardButton(
        text="◀️ Назад",
        callback_data=f"campaign:accounts:{campaign_id}",
    )])
    
    await callback.message.edit_text(
        "➖ <b>Выберите аккаунт для удаления:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cdr:"))
async def campaign_do_remove_account(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Remove account from campaign (short callback)."""
    account_id = UUID(callback.data.split(":")[1])

    # Get campaign_id from state
    data = await state.get_data()
    campaign_id_str = data.get("current_campaign_id")

    if not campaign_id_str:
        await callback.answer("❌ Сессия истекла", show_alert=True)
        return

    campaign_id = UUID(campaign_id_str)
    service = get_campaign_service(session)

    try:
        await service.remove_account_from_campaign(campaign_id, account_id)
        await callback.answer("✅ Аккаунт убран!", show_alert=True)

        # Inline refresh
        await _show_campaign_accounts(callback.message, session, campaign_id, state)

    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)[:100]}", show_alert=True)


# =============================================================================
# Sending Settings (Batch First Messages)
# =============================================================================

@router.callback_query(F.data.startswith("campaign:cfg:sending:"))
async def configure_sending_start(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show current sending settings."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    campaign_id = UUID(callback.data.split(":")[-1])
    campaign_repo = PostgresCampaignRepository(session)

    campaign = await campaign_repo.get_by_id(campaign_id)
    if not campaign:
        await callback.answer("Кампания не найдена", show_alert=True)
        return

    sending = campaign.sending
    next_batch = "сейчас" if sending.can_send_batch() else f"через ~{sending.send_interval_hours}ч"
    follow_up_status = "✅ Вкл" if sending.follow_up_enabled else "❌ Выкл"

    text = (
        "⏱ <b>Настройки рассылки</b>\n\n"
        f"📢 {campaign.name}\n\n"
        f"<b>Интервал:</b> раз в {sending.send_interval_hours} часов\n"
        f"<b>Сообщений за раз:</b> {sending.messages_per_batch}\n"
        f"<b>Интервал между сообщениями:</b> {sending.message_delay_min}-{sending.message_delay_max} сек\n"
        f"<b>Follow-up:</b> {follow_up_status}\n\n"
        f"<b>Следующая рассылка:</b> {next_batch}\n"
    )

    if sending.last_batch_at:
        text += f"<b>Последняя рассылка:</b> {sending.last_batch_at.strftime('%H:%M %d.%m')}\n"

    follow_up_btn_text = "🔕 Выключить Follow-up" if sending.follow_up_enabled else "🔔 Включить Follow-up"

    buttons = [
        [InlineKeyboardButton(
            text="⏰ Изменить интервал",
            callback_data=f"campaign:sending:interval:{campaign_id}",
        )],
        [InlineKeyboardButton(
            text="📊 Сообщений за раз",
            callback_data=f"campaign:sending:batch:{campaign_id}",
        )],
        [InlineKeyboardButton(
            text="⏳ Интервал между сообщениями",
            callback_data=f"campaign:sending:delay:{campaign_id}",
        )],
        [InlineKeyboardButton(
            text=follow_up_btn_text,
            callback_data=f"campaign:sending:followup:{campaign_id}",
        )],
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"campaign:configure:{campaign_id}",
        )],
    ]

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("campaign:sending:interval:"))
async def sending_interval_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start setting send interval."""
    campaign_id = callback.data.split(":")[-1]
    await state.update_data(campaign_id=campaign_id)
    await state.set_state(CampaignStates.waiting_send_interval)

    await callback.message.edit_text(
        "⏰ <b>Интервал рассылки</b>\n\n"
        "Введите интервал в часах между рассылками первых сообщений.\n\n"
        "<i>Например: 13 (раз в 13 часов)</i>",
    )
    await callback.message.answer(
        "Введите число часов:",
        reply_markup=get_cancel_kb(),
    )
    await callback.answer()


@router.message(CampaignStates.waiting_send_interval)
async def receive_send_interval(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Receive send interval."""
    try:
        hours = float(message.text.strip().replace(",", "."))
        if hours <= 0 or hours > 168:  # max 1 week
            raise ValueError("Invalid range")
    except ValueError:
        await message.answer("❌ Введите число от 0.5 до 168 (часов)")
        return

    data = await state.get_data()
    campaign_id = UUID(data["campaign_id"])

    campaign_repo = PostgresCampaignRepository(session)
    campaign = await campaign_repo.get_by_id(campaign_id)

    if campaign:
        campaign.sending.send_interval_hours = hours
        await campaign_repo.save(campaign)

    await state.clear()
    await message.answer(
        f"✅ <b>Интервал установлен!</b>\n\n"
        f"Рассылка первых сообщений будет происходить раз в {hours} часов.",
        reply_markup=get_main_menu_kb(),
    )


@router.callback_query(F.data.startswith("campaign:sending:batch:"))
async def sending_batch_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start setting messages per batch."""
    campaign_id = callback.data.split(":")[-1]
    await state.update_data(campaign_id=campaign_id)
    await state.set_state(CampaignStates.waiting_messages_per_batch)

    await callback.message.edit_text(
        "📊 <b>Сообщений за рассылку</b>\n\n"
        "Введите количество первых сообщений за одну рассылку.\n\n"
        "<i>Например: 10</i>",
    )
    await callback.message.answer(
        "Введите число:",
        reply_markup=get_cancel_kb(),
    )
    await callback.answer()


@router.message(CampaignStates.waiting_messages_per_batch)
async def receive_messages_per_batch(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Receive messages per batch."""
    try:
        count = int(message.text.strip())
        if count <= 0 or count > 100:
            raise ValueError("Invalid range")
    except ValueError:
        await message.answer("❌ Введите число от 1 до 100")
        return

    data = await state.get_data()
    campaign_id = UUID(data["campaign_id"])

    campaign_repo = PostgresCampaignRepository(session)
    campaign = await campaign_repo.get_by_id(campaign_id)

    if campaign:
        campaign.sending.messages_per_batch = count
        await campaign_repo.save(campaign)

    await state.clear()
    await message.answer(
        f"✅ <b>Количество установлено!</b>\n\n"
        f"За одну рассылку будет отправляться {count} первых сообщений.",
        reply_markup=get_main_menu_kb(),
    )


@router.callback_query(F.data.startswith("campaign:sending:delay:"))
async def sending_delay_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start setting message delay range."""
    campaign_id = callback.data.split(":")[-1]
    await state.update_data(campaign_id=campaign_id)
    await state.set_state(CampaignStates.waiting_message_delay)

    await callback.message.edit_text(
        "⏳ <b>Интервал между сообщениями</b>\n\n"
        "Введите минимальный и максимальный интервал в секундах между отправкой сообщений.\n\n"
        "<i>Формат: мин,макс</i>\n"
        "<i>Например: 17,23</i>",
    )
    await callback.message.answer(
        "Введите диапазон (мин,макс):",
        reply_markup=get_cancel_kb(),
    )
    await callback.answer()


@router.message(CampaignStates.waiting_message_delay)
async def receive_message_delay(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Receive message delay range."""
    try:
        parts = message.text.strip().replace(" ", "").split(",")
        if len(parts) != 2:
            raise ValueError("Need two values")
        delay_min = int(parts[0])
        delay_max = int(parts[1])
        if delay_min <= 0 or delay_max <= 0 or delay_min > delay_max:
            raise ValueError("Invalid range")
        if delay_max > 300:  # max 5 minutes
            raise ValueError("Too large")
    except ValueError:
        await message.answer("❌ Введите два числа через запятую (например: 17,23)")
        return

    data = await state.get_data()
    campaign_id = UUID(data["campaign_id"])

    campaign_repo = PostgresCampaignRepository(session)
    campaign = await campaign_repo.get_by_id(campaign_id)

    if campaign:
        campaign.sending.message_delay_min = delay_min
        campaign.sending.message_delay_max = delay_max
        await campaign_repo.save(campaign)

    await state.clear()
    await message.answer(
        f"✅ <b>Интервал установлен!</b>\n\n"
        f"Между отправкой сообщений будет {delay_min}-{delay_max} секунд.",
        reply_markup=get_main_menu_kb(),
    )


@router.callback_query(F.data.startswith("campaign:sending:followup:"))
async def toggle_follow_up(callback: CallbackQuery, session: AsyncSession) -> None:
    """Toggle follow-up messages for campaign."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    campaign_id = UUID(callback.data.split(":")[-1])
    campaign_repo = PostgresCampaignRepository(session)

    campaign = await campaign_repo.get_by_id(campaign_id)
    if not campaign:
        await callback.answer("Кампания не найдена", show_alert=True)
        return

    # Toggle the setting
    campaign.sending.follow_up_enabled = not campaign.sending.follow_up_enabled
    await campaign_repo.save(campaign)

    new_status = "включены" if campaign.sending.follow_up_enabled else "выключены"
    await callback.answer(f"Follow-up {new_status}!", show_alert=True)

    # Refresh the sending settings page
    sending = campaign.sending
    next_batch = "сейчас" if sending.can_send_batch() else f"через ~{sending.send_interval_hours}ч"
    follow_up_status = "✅ Вкл" if sending.follow_up_enabled else "❌ Выкл"

    text = (
        "⏱ <b>Настройки рассылки</b>\n\n"
        f"📢 {campaign.name}\n\n"
        f"<b>Интервал:</b> раз в {sending.send_interval_hours} часов\n"
        f"<b>Сообщений за раз:</b> {sending.messages_per_batch}\n"
        f"<b>Интервал между сообщениями:</b> {sending.message_delay_min}-{sending.message_delay_max} сек\n"
        f"<b>Follow-up:</b> {follow_up_status}\n\n"
        f"<b>Следующая рассылка:</b> {next_batch}\n"
    )

    if sending.last_batch_at:
        text += f"<b>Последняя рассылка:</b> {sending.last_batch_at.strftime('%H:%M %d.%m')}\n"

    follow_up_btn_text = "🔕 Выключить Follow-up" if sending.follow_up_enabled else "🔔 Включить Follow-up"

    buttons = [
        [InlineKeyboardButton(
            text="⏰ Изменить интервал",
            callback_data=f"campaign:sending:interval:{campaign_id}",
        )],
        [InlineKeyboardButton(
            text="📊 Сообщений за раз",
            callback_data=f"campaign:sending:batch:{campaign_id}",
        )],
        [InlineKeyboardButton(
            text="⏳ Интервал между сообщениями",
            callback_data=f"campaign:sending:delay:{campaign_id}",
        )],
        [InlineKeyboardButton(
            text=follow_up_btn_text,
            callback_data=f"campaign:sending:followup:{campaign_id}",
        )],
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"campaign:configure:{campaign_id}",
        )],
    ]

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


# =============================================================================
# Restart Campaign (for testing)
# =============================================================================

@router.callback_query(F.data.startswith("campaign:restart:"))
async def restart_campaign_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show restart confirmation."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    campaign_id = UUID(callback.data.split(":")[-1])
    campaign_repo = PostgresCampaignRepository(session)

    campaign = await campaign_repo.get_by_id(campaign_id)
    if not campaign:
        await callback.answer("Кампания не найдена", show_alert=True)
        return

    text = (
        "⚠️ <b>Рестарт кампании</b>\n\n"
        f"📢 {campaign.name}\n\n"
        "Это действие:\n"
        "• Удалит все диалоги\n"
        "• Сбросит статус всех таргетов на pending\n"
        "• Обнулит статистику\n\n"
        "<b>Вы уверены?</b>"
    )

    buttons = [
        [InlineKeyboardButton(
            text="✅ Да, рестартнуть",
            callback_data=f"campaign:dorestart:{campaign_id}",
        )],
        [InlineKeyboardButton(
            text="❌ Отмена",
            callback_data=f"campaign:view:{campaign_id}",
        )],
    ]

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("campaign:dorestart:"))
async def restart_campaign_execute(callback: CallbackQuery, session: AsyncSession) -> None:
    """Execute campaign restart - delete dialogues, reset targets."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.infrastructure.database.repositories import PostgresDialogueRepository
    from src.domain.entities import UserTargetStatus

    campaign_id = UUID(callback.data.split(":")[-1])

    campaign_repo = PostgresCampaignRepository(session)
    dialogue_repo = PostgresDialogueRepository(session)
    target_repo = PostgresUserTargetRepository(session)

    campaign = await campaign_repo.get_by_id(campaign_id)
    if not campaign:
        await callback.answer("Кампания не найдена", show_alert=True)
        return

    await callback.answer("⏳ Рестартую кампанию...")

    try:
        # 1. Delete all dialogues for this campaign
        dialogues = await dialogue_repo.list_by_campaign(campaign_id, limit=10000)
        deleted_dialogues = 0
        for dialogue in dialogues:
            await dialogue_repo.delete(dialogue.id)
            deleted_dialogues += 1

        # 2. Reset all targets to pending status
        targets = await target_repo.list_by_campaign(campaign_id, limit=10000)
        reset_targets = 0
        for target in targets:
            target.status = UserTargetStatus.PENDING
            target.assigned_account_id = None
            target.dialogue_id = None
            target.contact_attempts = 0
            target.last_contact_attempt = None
            target.fail_reason = None
            await target_repo.save(target)
            reset_targets += 1

        # 3. Reset campaign stats
        campaign.stats.total_targets = reset_targets
        campaign.stats.contacted = 0
        campaign.stats.in_progress = 0
        campaign.stats.goals_reached = 0
        campaign.stats.failed = 0
        campaign.stats.total_messages_sent = 0
        campaign.stats.total_messages_received = 0

        # 4. Reset sending batch time to allow immediate sending
        campaign.sending.last_batch_at = None

        await campaign_repo.save(campaign)

        # 5. Reset daily counters for campaign accounts
        account_repo = PostgresAccountRepository(session)
        accounts = await account_repo.list_by_campaign(campaign_id)
        for account in accounts:
            account.daily_conversations_count = 0
            account.daily_messages_count = 0
            await account_repo.save(account)

        text = (
            "✅ <b>Кампания рестартнута!</b>\n\n"
            f"📢 {campaign.name}\n\n"
            f"• Удалено диалогов: {deleted_dialogues}\n"
            f"• Сброшено таргетов: {reset_targets}\n"
            f"• Аккаунтов сброшено: {len(accounts)}\n"
            f"• Статистика обнулена\n\n"
            "Теперь можно запустить кампанию заново."
        )

        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="▶️ Запустить",
                    callback_data=f"campaign:start:{campaign_id}",
                )],
                [InlineKeyboardButton(
                    text="◀️ К кампании",
                    callback_data=f"campaign:view:{campaign_id}",
                )],
            ]),
        )

    except Exception as e:
        await callback.message.edit_text(
            f"❌ <b>Ошибка при рестарте:</b>\n\n{str(e)[:200]}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data=f"campaign:view:{campaign_id}",
                )],
            ]),
        )


# =============================================================================
# Bulk Account Limits Update
# =============================================================================

@router.callback_query(F.data.startswith("campaign:cfg:limits:"))
async def configure_account_limits(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show current account limits and options to update them."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    campaign_id = UUID(callback.data.split(":")[-1])

    campaign_repo = PostgresCampaignRepository(session)
    account_repo = PostgresAccountRepository(session)

    campaign = await campaign_repo.get_by_id(campaign_id)
    if not campaign:
        await callback.answer("Кампания не найдена", show_alert=True)
        return

    accounts = await account_repo.list_by_campaign(campaign_id)

    if not accounts:
        await callback.message.edit_text(
            "📊 <b>Лимиты аккаунтов</b>\n\n"
            f"📢 {campaign.name}\n\n"
            "❌ Нет назначенных аккаунтов.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data=f"campaign:configure:{campaign_id}",
                )],
            ]),
        )
        await callback.answer()
        return

    # Calculate stats on current limits
    max_convs = [a.limits.max_new_conversations_per_day for a in accounts]
    avg_max = sum(max_convs) / len(max_convs)
    min_max = min(max_convs)
    max_max = max(max_convs)

    text = (
        "📊 <b>Лимиты аккаунтов</b>\n\n"
        f"📢 {campaign.name}\n"
        f"📱 Аккаунтов: {len(accounts)}\n\n"
        f"<b>Макс. новых диалогов в день:</b>\n"
        f"• Мин: {min_max}\n"
        f"• Макс: {max_max}\n"
        f"• Среднее: {avg_max:.1f}\n\n"
        f"<b>Суммарная ёмкость:</b> {sum(max_convs)} диалогов/день\n\n"
        "Выберите действие:"
    )

    buttons = [
        [InlineKeyboardButton(
            text="📝 Изменить макс. диалогов/день",
            callback_data=f"campaign:limits:maxconv:{campaign_id}",
        )],
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"campaign:configure:{campaign_id}",
        )],
    ]

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("campaign:limits:maxconv:"))
async def bulk_max_conversations_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start bulk max conversations update."""
    campaign_id = callback.data.split(":")[-1]
    await state.update_data(campaign_id=campaign_id)
    await state.set_state(CampaignStates.waiting_bulk_max_conversations)

    await callback.message.edit_text(
        "📝 <b>Изменить лимит диалогов</b>\n\n"
        "Введите новое значение максимального количества "
        "новых диалогов в день для <b>всех аккаунтов</b> этой кампании.\n\n"
        "<i>Например: 25</i>\n\n"
        "Это изменит значение max_new_conversations_per_day "
        "для всех привязанных аккаунтов.",
    )
    await callback.message.answer(
        "Введите число:",
        reply_markup=get_cancel_kb(),
    )
    await callback.answer()


@router.message(CampaignStates.waiting_bulk_max_conversations)
async def receive_bulk_max_conversations(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Receive and apply bulk max conversations update."""
    try:
        value = int(message.text.strip())
        if value <= 0 or value > 1000:
            raise ValueError("Invalid range")
    except ValueError:
        await message.answer("❌ Введите число от 1 до 1000")
        return

    data = await state.get_data()
    campaign_id = UUID(data["campaign_id"])

    account_repo = PostgresAccountRepository(session)
    accounts = await account_repo.list_by_campaign(campaign_id)

    if not accounts:
        await state.clear()
        await message.answer(
            "❌ Нет аккаунтов в кампании.",
            reply_markup=get_main_menu_kb(),
        )
        return

    # Update all accounts
    updated_count = 0
    for account in accounts:
        account.limits.max_new_conversations_per_day = value
        await account_repo.save(account)
        updated_count += 1

    await state.clear()
    await message.answer(
        f"✅ <b>Лимиты обновлены!</b>\n\n"
        f"Обновлено аккаунтов: {updated_count}\n"
        f"Новое значение: {value} диалогов/день\n\n"
        f"Суммарная ёмкость: {updated_count * value} диалогов/день",
        reply_markup=get_main_menu_kb(),
    )
