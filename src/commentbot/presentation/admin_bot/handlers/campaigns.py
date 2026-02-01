"""Campaign management handlers for comment bot."""

from uuid import UUID

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from src.commentbot.domain.entities import Campaign, CampaignStatus, Channel, ChannelStatus
from src.commentbot.infrastructure.database.repository import (
    CampaignRepository,
    ChannelRepository,
    AccountRepository,
    ChannelAssignmentRepository,
)
from src.commentbot.application.services import ChannelDistributor, ProfileCopier

router = Router()


class CampaignStates(StatesGroup):
    """FSM states for campaign management."""

    waiting_name = State()
    waiting_channels = State()
    waiting_templates = State()
    waiting_initial_message = State()


# =========================================
# Keyboards
# =========================================


def campaigns_menu_keyboard() -> InlineKeyboardMarkup:
    """Campaigns menu."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Создать кампанию", callback_data="camp:create"),
    )
    builder.row(
        InlineKeyboardButton(text="📋 Список кампаний", callback_data="camp:list"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main"),
    )
    return builder.as_markup()


def campaign_actions_keyboard(campaign_id: str, is_active: bool) -> InlineKeyboardMarkup:
    """Actions for specific campaign."""
    builder = InlineKeyboardBuilder()

    if is_active:
        builder.row(
            InlineKeyboardButton(text="⏸ Пауза", callback_data=f"camp:pause:{campaign_id}"),
        )
    else:
        builder.row(
            InlineKeyboardButton(text="▶️ Запустить", callback_data=f"camp:start:{campaign_id}"),
        )

    builder.row(
        InlineKeyboardButton(text="📺 Каналы", callback_data=f"camp:channels:{campaign_id}"),
        InlineKeyboardButton(text="➕ Добавить каналы", callback_data=f"camp:add_channels:{campaign_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="📝 Шаблоны", callback_data=f"camp:templates:{campaign_id}"),
        InlineKeyboardButton(text="💬 Начальное сообщение", callback_data=f"camp:initial_msg:{campaign_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Распределить", callback_data=f"camp:distribute:{campaign_id}"),
        InlineKeyboardButton(text="📊 Статистика", callback_data=f"camp:stats:{campaign_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="🔀 Cross-Swap", callback_data=f"camp:crossswap:{campaign_id}"),
        InlineKeyboardButton(text="👤 Копировать профили", callback_data=f"camp:copyprofiles:{campaign_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"camp:delete:{campaign_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ К списку", callback_data="camp:list"),
    )
    return builder.as_markup()


def cancel_keyboard() -> InlineKeyboardMarkup:
    """Cancel keyboard."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="camp:menu"),
    )
    return builder.as_markup()


def back_to_campaign_keyboard(campaign_id: str) -> InlineKeyboardMarkup:
    """Back to campaign view."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data=f"camp:view:{campaign_id}"),
    )
    return builder.as_markup()


def _get_status_emoji(status: CampaignStatus) -> str:
    """Get emoji for campaign status."""
    return {
        CampaignStatus.DRAFT: "📝",
        CampaignStatus.ACTIVE: "✅",
        CampaignStatus.PAUSED: "⏸",
        CampaignStatus.COMPLETED: "🏁",
    }.get(status, "❓")


# =========================================
# Menu Handler
# =========================================


@router.message(F.text == "💬 Комментарии")
async def campaigns_menu(message: Message, session: AsyncSession):
    """Show campaigns menu."""
    repo = CampaignRepository(session)
    campaigns = await repo.list_by_owner(message.from_user.id)

    active = sum(1 for c in campaigns if c.status == CampaignStatus.ACTIVE)

    await message.answer(
        f"💬 <b>Кампании комментариев</b>\n\n"
        f"Всего кампаний: {len(campaigns)}\n"
        f"Активных: {active}",
        reply_markup=campaigns_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "camp:menu")
async def campaigns_menu_callback(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Show campaigns menu (callback)."""
    await state.clear()

    repo = CampaignRepository(session)
    campaigns = await repo.list_by_owner(callback.from_user.id)

    active = sum(1 for c in campaigns if c.status == CampaignStatus.ACTIVE)

    await callback.message.edit_text(
        f"💬 <b>Кампании комментариев</b>\n\n"
        f"Всего кампаний: {len(campaigns)}\n"
        f"Активных: {active}",
        reply_markup=campaigns_menu_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


# =========================================
# Create Campaign
# =========================================


@router.callback_query(F.data == "camp:create")
async def start_create_campaign(callback: CallbackQuery, state: FSMContext):
    """Start campaign creation."""
    await callback.message.edit_text(
        "📝 <b>Создание кампании</b>\n\n"
        "Введите название кампании:",
        reply_markup=cancel_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CampaignStates.waiting_name)
    await callback.answer()


@router.message(CampaignStates.waiting_name)
async def process_campaign_name(message: Message, state: FSMContext, session: AsyncSession):
    """Process campaign name."""
    name = message.text.strip()

    if len(name) < 2:
        await message.answer(
            "❌ Название слишком короткое. Минимум 2 символа.",
            reply_markup=cancel_keyboard(),
        )
        return

    # Create campaign
    campaign = Campaign(
        name=name,
        owner_id=message.from_user.id,
    )

    repo = CampaignRepository(session)
    await repo.save(campaign)
    await session.commit()

    await state.update_data(campaign_id=str(campaign.id))
    await state.set_state(CampaignStates.waiting_channels)

    await message.answer(
        f"✅ Кампания <b>{name}</b> создана!\n\n"
        f"Теперь добавьте каналы для комментирования.\n"
        f"Отправьте ссылки на каналы (по одной на строку):\n\n"
        f"Пример:\n"
        f"<code>@channel1\n"
        f"t.me/channel2\n"
        f"https://t.me/channel3</code>",
        reply_markup=cancel_keyboard(),
        parse_mode="HTML",
    )


@router.message(CampaignStates.waiting_channels)
async def process_channels(message: Message, state: FSMContext, session: AsyncSession):
    """Process channel links."""
    data = await state.get_data()
    campaign_id = UUID(data["campaign_id"])

    lines = message.text.strip().split("\n")
    channel_repo = ChannelRepository(session)

    added = 0
    errors = []

    for line in lines:
        link = line.strip()
        if not link:
            continue

        username = Channel.parse_link(link)
        if not username:
            errors.append(f"❌ {link} - неверный формат")
            continue

        channel = Channel(
            campaign_id=campaign_id,
            link=link,
            username=username,
            owner_id=message.from_user.id,
        )
        await channel_repo.save(channel)
        added += 1

    await session.commit()

    result_text = f"✅ Добавлено каналов: {added}"
    if errors:
        result_text += "\n\n" + "\n".join(errors[:5])
        if len(errors) > 5:
            result_text += f"\n...и ещё {len(errors) - 5} ошибок"

    result_text += "\n\nТеперь добавьте шаблоны комментариев (по одному на строку):"

    await state.set_state(CampaignStates.waiting_templates)

    await message.answer(
        result_text,
        reply_markup=cancel_keyboard(),
        parse_mode="HTML",
    )


@router.message(CampaignStates.waiting_templates)
async def process_templates(message: Message, state: FSMContext, session: AsyncSession):
    """Process comment templates."""
    data = await state.get_data()
    campaign_id = UUID(data["campaign_id"])

    lines = message.text.strip().split("\n")
    templates = [line.strip() for line in lines if line.strip()]

    if not templates:
        await message.answer(
            "❌ Отправьте хотя бы один шаблон комментария.",
            reply_markup=cancel_keyboard(),
        )
        return

    repo = CampaignRepository(session)
    campaign = await repo.get_by_id(campaign_id)

    if campaign:
        campaign.comment_templates = templates
        await repo.save(campaign)
        await session.commit()

    await state.clear()

    await message.answer(
        f"✅ <b>Кампания настроена!</b>\n\n"
        f"Добавлено шаблонов: {len(templates)}\n\n"
        f"Теперь распределите каналы по аккаунтам и запустите кампанию.",
        reply_markup=back_to_campaign_keyboard(str(campaign_id)),
        parse_mode="HTML",
    )


# =========================================
# List Campaigns
# =========================================


@router.callback_query(F.data == "camp:list")
async def list_campaigns(callback: CallbackQuery, session: AsyncSession):
    """Show campaigns list."""
    repo = CampaignRepository(session)
    campaigns = await repo.list_by_owner(callback.from_user.id)

    if not campaigns:
        await callback.message.edit_text(
            "📋 <b>Список кампаний</b>\n\n"
            "<i>Нет созданных кампаний</i>",
            reply_markup=campaigns_menu_keyboard(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    builder = InlineKeyboardBuilder()

    for camp in campaigns:
        emoji = _get_status_emoji(camp.status)
        builder.row(
            InlineKeyboardButton(
                text=f"{emoji} {camp.name}",
                callback_data=f"camp:view:{camp.id}",
            )
        )

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="camp:menu"),
    )

    await callback.message.edit_text(
        f"📋 <b>Список кампаний</b>\n\n"
        f"Всего: {len(campaigns)}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


# =========================================
# View Campaign
# =========================================


@router.callback_query(F.data.startswith("camp:view:"))
async def view_campaign(callback: CallbackQuery, session: AsyncSession):
    """View campaign details."""
    campaign_id = callback.data.split(":")[2]

    camp_repo = CampaignRepository(session)
    channel_repo = ChannelRepository(session)

    campaign = await camp_repo.get_by_id(UUID(campaign_id))
    if not campaign:
        await callback.answer("Кампания не найдена", show_alert=True)
        return

    channels = await channel_repo.list_by_campaign(UUID(campaign_id))
    active_channels = [c for c in channels if c.status == ChannelStatus.ACTIVE]

    emoji = _get_status_emoji(campaign.status)

    text = (
        f"{emoji} <b>{campaign.name}</b>\n\n"
        f"Статус: {campaign.status.value}\n"
        f"Каналов: {len(channels)} (активных: {len(active_channels)})\n"
        f"Шаблонов: {len(campaign.comment_templates)}\n\n"
        f"📊 <b>Статистика</b>\n"
        f"Всего комментов: {campaign.total_comments}\n"
        f"Успешных: {campaign.successful_comments}\n"
        f"Ошибок: {campaign.failed_comments}"
    )

    await callback.message.edit_text(
        text,
        reply_markup=campaign_actions_keyboard(
            campaign_id=str(campaign.id),
            is_active=campaign.status == CampaignStatus.ACTIVE,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


# =========================================
# Campaign Actions
# =========================================


@router.callback_query(F.data.startswith("camp:start:"))
async def start_campaign(callback: CallbackQuery, session: AsyncSession):
    """Start campaign."""
    campaign_id = callback.data.split(":")[2]

    repo = CampaignRepository(session)
    campaign = await repo.get_by_id(UUID(campaign_id))

    if campaign:
        campaign.activate()
        await repo.save(campaign)
        await session.commit()

        await callback.answer("Кампания запущена!")
        await view_campaign(callback, session)
    else:
        await callback.answer("Кампания не найдена", show_alert=True)


@router.callback_query(F.data.startswith("camp:pause:"))
async def pause_campaign(callback: CallbackQuery, session: AsyncSession):
    """Pause campaign."""
    campaign_id = callback.data.split(":")[2]

    repo = CampaignRepository(session)
    campaign = await repo.get_by_id(UUID(campaign_id))

    if campaign:
        campaign.pause()
        await repo.save(campaign)
        await session.commit()

        await callback.answer("Кампания приостановлена")
        await view_campaign(callback, session)
    else:
        await callback.answer("Кампания не найдена", show_alert=True)


@router.callback_query(F.data.startswith("camp:distribute:"))
async def distribute_channels(callback: CallbackQuery, session: AsyncSession):
    """Distribute channels across accounts."""
    campaign_id = callback.data.split(":")[2]

    account_repo = AccountRepository(session)
    channel_repo = ChannelRepository(session)
    assignment_repo = ChannelAssignmentRepository(session)
    campaign_repo = CampaignRepository(session)

    distributor = ChannelDistributor(
        account_repo, channel_repo, assignment_repo, campaign_repo
    )

    result = await distributor.distribute_channels(
        campaign_id=UUID(campaign_id),
        owner_id=callback.from_user.id,
    )
    await session.commit()

    if "error" in result:
        await callback.answer(result["error"], show_alert=True)
    else:
        await callback.answer(
            f"Распределено: {result['assigned']} каналов на {result.get('accounts_used', 0)} аккаунтов"
        )

    await view_campaign(callback, session)


@router.callback_query(F.data.startswith("camp:crossswap:"))
async def crossswap_accounts(callback: CallbackQuery, session: AsyncSession):
    """Perform cross-swap between blocked accounts."""
    campaign_id = callback.data.split(":")[2]

    account_repo = AccountRepository(session)
    channel_repo = ChannelRepository(session)
    assignment_repo = ChannelAssignmentRepository(session)
    campaign_repo = CampaignRepository(session)

    distributor = ChannelDistributor(
        account_repo, channel_repo, assignment_repo, campaign_repo
    )

    result = await distributor.perform_cross_swap(
        campaign_id=UUID(campaign_id),
        owner_id=callback.from_user.id,
    )
    await session.commit()

    await callback.answer(
        f"Cross-swap: {result['swaps']} обменов выполнено"
    )
    await view_campaign(callback, session)


@router.callback_query(F.data.startswith("camp:copyprofiles:"))
async def copy_profiles(callback: CallbackQuery, session: AsyncSession):
    """Copy channel profiles to assigned accounts."""
    campaign_id = callback.data.split(":")[2]

    await callback.answer("Копирование профилей... Это может занять время")

    account_repo = AccountRepository(session)
    channel_repo = ChannelRepository(session)
    assignment_repo = ChannelAssignmentRepository(session)

    copier = ProfileCopier(account_repo, channel_repo)

    result = await copier.copy_for_all_assignments(
        campaign_id=UUID(campaign_id),
        owner_id=callback.from_user.id,
        assignment_repo=assignment_repo,
    )
    await session.commit()

    await callback.message.edit_text(
        f"👤 <b>Копирование профилей</b>\n\n"
        f"Всего аккаунтов: {result['total']}\n"
        f"Успешно: {result['copied']}\n"
        f"Ошибок: {result['failed']}",
        reply_markup=back_to_campaign_keyboard(campaign_id),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("camp:stats:"))
async def show_stats(callback: CallbackQuery, session: AsyncSession):
    """Show distribution statistics."""
    campaign_id = callback.data.split(":")[2]

    account_repo = AccountRepository(session)
    channel_repo = ChannelRepository(session)
    assignment_repo = ChannelAssignmentRepository(session)
    campaign_repo = CampaignRepository(session)

    distributor = ChannelDistributor(
        account_repo, channel_repo, assignment_repo, campaign_repo
    )

    stats = await distributor.get_distribution_stats(
        campaign_id=UUID(campaign_id),
        owner_id=callback.from_user.id,
    )

    text = (
        f"📊 <b>Статистика распределения</b>\n\n"
        f"Аккаунтов: {stats['total_accounts']}\n"
        f"Каналов: {stats['total_channels']}\n\n"
        f"Распределено: {stats['assigned']}\n"
        f"Заблокировано: {stats['blocked']}\n"
        f"Не распределено: {stats['unassigned']}\n\n"
        f"<b>По аккаунтам:</b>\n"
    )

    for acc_id, acc_stats in stats.get("per_account", {}).items():
        text += f"• {acc_stats['phone']}: {acc_stats['assigned']} каналов"
        if acc_stats['blocked']:
            text += f" (🚫 {acc_stats['blocked']})"
        text += "\n"

    await callback.message.edit_text(
        text,
        reply_markup=back_to_campaign_keyboard(campaign_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("camp:channels:"))
async def show_channels(callback: CallbackQuery, session: AsyncSession):
    """Show campaign channels."""
    campaign_id = callback.data.split(":")[2]

    channel_repo = ChannelRepository(session)
    channels = await channel_repo.list_by_campaign(UUID(campaign_id))

    if not channels:
        await callback.message.edit_text(
            "📺 <b>Каналы кампании</b>\n\n"
            "<i>Нет добавленных каналов</i>",
            reply_markup=back_to_campaign_keyboard(campaign_id),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    text = f"📺 <b>Каналы кампании</b> ({len(channels)})\n\n"

    status_emoji = {
        ChannelStatus.PENDING: "⏳",
        ChannelStatus.ACTIVE: "✅",
        ChannelStatus.NO_ACCESS: "🚫",
        ChannelStatus.NO_COMMENTS: "💬❌",
        ChannelStatus.ERROR: "❌",
    }

    for ch in channels[:20]:
        emoji = status_emoji.get(ch.status, "❓")
        name = ch.title or ch.username or ch.link[:20]
        text += f"{emoji} {name}\n"

    if len(channels) > 20:
        text += f"\n...и ещё {len(channels) - 20} каналов"

    await callback.message.edit_text(
        text,
        reply_markup=back_to_campaign_keyboard(campaign_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("camp:add_channels:"))
async def add_more_channels(callback: CallbackQuery, state: FSMContext):
    """Add more channels to campaign."""
    campaign_id = callback.data.split(":")[2]

    await state.update_data(campaign_id=campaign_id)
    await state.set_state(CampaignStates.waiting_channels)

    await callback.message.edit_text(
        "➕ <b>Добавление каналов</b>\n\n"
        "Отправьте ссылки на каналы (по одной на строку):",
        reply_markup=back_to_campaign_keyboard(campaign_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("camp:templates:"))
async def show_templates(callback: CallbackQuery, session: AsyncSession):
    """Show comment templates."""
    campaign_id = callback.data.split(":")[2]

    repo = CampaignRepository(session)
    campaign = await repo.get_by_id(UUID(campaign_id))

    if not campaign:
        await callback.answer("Кампания не найдена", show_alert=True)
        return

    if not campaign.comment_templates:
        text = "📝 <b>Шаблоны комментариев</b>\n\n<i>Нет шаблонов</i>"
    else:
        text = f"📝 <b>Шаблоны комментариев</b> ({len(campaign.comment_templates)})\n\n"
        for i, tpl in enumerate(campaign.comment_templates[:10], 1):
            text += f"{i}. {tpl[:50]}{'...' if len(tpl) > 50 else ''}\n"

        if len(campaign.comment_templates) > 10:
            text += f"\n...и ещё {len(campaign.comment_templates) - 10}"

    await callback.message.edit_text(
        text,
        reply_markup=back_to_campaign_keyboard(campaign_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("camp:delete:"))
async def delete_campaign_confirm(callback: CallbackQuery):
    """Confirm campaign deletion."""
    campaign_id = callback.data.split(":")[2]

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"camp:confirm_delete:{campaign_id}"),
        InlineKeyboardButton(text="❌ Нет", callback_data=f"camp:view:{campaign_id}"),
    )

    await callback.message.edit_text(
        "🗑 <b>Удаление кампании</b>\n\n"
        "Вы уверены? Все каналы и назначения будут удалены.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("camp:confirm_delete:"))
async def delete_campaign(callback: CallbackQuery, session: AsyncSession):
    """Delete campaign."""
    campaign_id = callback.data.split(":")[2]

    repo = CampaignRepository(session)
    deleted = await repo.delete(UUID(campaign_id))
    await session.commit()

    if deleted:
        await callback.answer("Кампания удалена")
        await list_campaigns(callback, session)
    else:
        await callback.answer("Кампания не найдена", show_alert=True)


# =========================================
# Initial Message Handlers
# =========================================


@router.callback_query(F.data.startswith("camp:initial_msg:"))
async def show_initial_message(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Show/edit initial message."""
    campaign_id = callback.data.split(":")[2]

    repo = CampaignRepository(session)
    campaign = await repo.get_by_id(UUID(campaign_id))

    if not campaign:
        await callback.answer("Кампания не найдена", show_alert=True)
        return

    current_msg = campaign.initial_message or "<i>Не установлено</i>"

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✏️ Изменить", callback_data=f"camp:set_initial_msg:{campaign_id}"),
    )
    if campaign.initial_message:
        builder.row(
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"camp:clear_initial_msg:{campaign_id}"),
        )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data=f"camp:view:{campaign_id}"),
    )

    await callback.message.edit_text(
        f"💬 <b>Начальное сообщение</b>\n\n"
        f"Это сообщение будет отправлено под последний пост канала "
        f"после копирования профиля.\n\n"
        f"<b>Текущее сообщение:</b>\n{current_msg}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("camp:set_initial_msg:"))
async def set_initial_message_start(callback: CallbackQuery, state: FSMContext):
    """Start setting initial message."""
    campaign_id = callback.data.split(":")[2]

    await state.update_data(campaign_id=campaign_id)
    await state.set_state(CampaignStates.waiting_initial_message)

    await callback.message.edit_text(
        "💬 <b>Установка начального сообщения</b>\n\n"
        "Отправьте текст сообщения, которое будет отправляться "
        "под последний пост канала после смены профиля:",
        reply_markup=back_to_campaign_keyboard(campaign_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(CampaignStates.waiting_initial_message)
async def set_initial_message_complete(message: Message, state: FSMContext, session: AsyncSession):
    """Complete setting initial message."""
    data = await state.get_data()
    campaign_id = data.get("campaign_id")

    if not campaign_id:
        await state.clear()
        return

    initial_message = message.text.strip()

    repo = CampaignRepository(session)
    campaign = await repo.get_by_id(UUID(campaign_id))

    if not campaign:
        await message.answer("Кампания не найдена")
        await state.clear()
        return

    campaign.initial_message = initial_message
    await repo.save(campaign)
    await session.commit()

    await state.clear()

    await message.answer(
        f"✅ <b>Начальное сообщение установлено</b>\n\n"
        f"{initial_message[:200]}{'...' if len(initial_message) > 200 else ''}",
        reply_markup=back_to_campaign_keyboard(campaign_id),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("camp:clear_initial_msg:"))
async def clear_initial_message(callback: CallbackQuery, session: AsyncSession):
    """Clear initial message."""
    campaign_id = callback.data.split(":")[2]

    repo = CampaignRepository(session)
    campaign = await repo.get_by_id(UUID(campaign_id))

    if not campaign:
        await callback.answer("Кампания не найдена", show_alert=True)
        return

    campaign.initial_message = None
    await repo.save(campaign)
    await session.commit()

    await callback.answer("Начальное сообщение удалено")
    await show_initial_message(callback, session, None)
