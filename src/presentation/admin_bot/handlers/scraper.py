"""
Scraper handlers for admin bot.

Handles target collection from Telegram channels/chats.
"""

import asyncio
from uuid import UUID
from typing import Optional

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

import structlog

from src.domain.entities import (
    Account,
    AccountStatus,
    ScrapeTask,
    ScrapeTaskStatus,
    UserTarget,
    TargetStatus,
)
from src.application.services import ScraperService, ParallelScraperService, create_targets_from_usernames
from src.infrastructure.database.repositories import (
    PostgresAccountRepository,
    PostgresCampaignRepository,
    PostgresUserTargetRepository,
)

from ..states import ScraperStates
from ..keyboards import (
    get_main_menu_kb,
    get_cancel_kb,
    get_scraper_menu_kb,
    get_scraper_accounts_kb,
    get_scraper_accounts_multi_kb,
    get_scraper_campaign_select_kb,
    get_scraper_progress_kb,
    get_scraper_result_kb,
)

logger = structlog.get_logger(__name__)
router = Router(name="scraper")

# Store active scraper tasks (in-memory, for simplicity)
_active_scrapers: dict[int, ScraperService] = {}  # user_id -> scraper
_active_parallel_scrapers: dict[int, ParallelScraperService] = {}  # user_id -> parallel scraper
_active_tasks: dict[int, ScrapeTask] = {}  # user_id -> task


# =============================================================================
# Menu
# =============================================================================

@router.message(F.text == "🔍 Парсер")
async def scraper_menu(message: Message) -> None:
    """Show scraper menu."""
    await message.answer(
        "🔍 <b>Парсер таргетов</b>\n\n"
        "Соберите username пользователей из каналов и чатов.\n\n"
        "Бот зайдёт в указанные каналы, соберёт username всех, "
        "кто писал сообщения или комментарии, и добавит их как таргеты.",
        reply_markup=get_scraper_menu_kb(),
    )


@router.callback_query(F.data == "scraper:menu")
async def scraper_menu_callback(callback: CallbackQuery) -> None:
    """Show scraper menu (callback)."""
    await callback.message.edit_text(
        "🔍 <b>Парсер таргетов</b>\n\n"
        "Соберите username пользователей из каналов и чатов.\n\n"
        "Бот зайдёт в указанные каналы, соберёт username всех, "
        "кто писал сообщения или комментарии, и добавит их как таргеты.",
        reply_markup=get_scraper_menu_kb(),
    )
    await callback.answer()


# =============================================================================
# Start Scraping Flow
# =============================================================================

@router.callback_query(F.data == "scraper:start")
async def start_scraping(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Start scraping flow - select account."""
    account_repo = PostgresAccountRepository(session)

    # Get accounts that can be used for scraping (ready or paused, not active in campaigns)
    all_accounts = await account_repo.list_all(limit=100)

    # Filter: prefer ready/paused accounts, also allow active if needed
    accounts = [
        a for a in all_accounts
        if a.status in (AccountStatus.READY, AccountStatus.PAUSED, AccountStatus.ACTIVE)
        and a.session_data  # Must have session
    ]

    if not accounts:
        await callback.message.edit_text(
            "❌ <b>Нет доступных аккаунтов</b>\n\n"
            "Добавьте аккаунт для парсинга в разделе 📱 Аккаунты.",
            reply_markup=get_scraper_menu_kb(),
        )
        await callback.answer()
        return

    await state.set_state(ScraperStates.selecting_account)

    await callback.message.edit_text(
        "📱 <b>Выберите аккаунт для парсинга</b>\n\n"
        "Этот аккаунт зайдёт в каналы и соберёт username.\n\n"
        "⚠️ Рекомендуется использовать отдельный аккаунт для парсинга, "
        "чтобы не нагружать рабочие аккаунты.",
        reply_markup=get_scraper_accounts_kb(accounts),
    )
    await callback.answer()


# =============================================================================
# Parallel Scraping Flow
# =============================================================================

@router.callback_query(F.data == "scraper:start_parallel")
async def start_parallel_scraping(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Start parallel scraping flow - multi-select accounts."""
    account_repo = PostgresAccountRepository(session)

    all_accounts = await account_repo.list_all(limit=100)
    accounts = [
        a for a in all_accounts
        if a.status in (AccountStatus.READY, AccountStatus.PAUSED, AccountStatus.ACTIVE)
        and a.session_data
    ]

    if len(accounts) < 2:
        await callback.message.edit_text(
            "❌ <b>Недостаточно аккаунтов</b>\n\n"
            "Для параллельного парсинга нужно минимум 2 аккаунта.\n"
            f"Доступно: {len(accounts)}",
            reply_markup=get_scraper_menu_kb(),
        )
        await callback.answer()
        return

    await state.update_data(selected_accounts=[], parallel_mode=True)
    await state.set_state(ScraperStates.selecting_account)

    await callback.message.edit_text(
        "⚡ <b>Параллельный парсинг</b>\n\n"
        "Выберите несколько аккаунтов для парсинга.\n"
        "Каналы будут распределены между аккаунтами.\n\n"
        f"📱 Доступно аккаунтов: {len(accounts)}",
        reply_markup=get_scraper_accounts_multi_kb(accounts, set()),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("scraper:toggle:"), ScraperStates.selecting_account)
async def toggle_account_selection(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Toggle account selection for parallel scraping."""
    account_id = callback.data.split(":")[-1]

    data = await state.get_data()
    selected = set(data.get("selected_accounts", []))

    if account_id in selected:
        selected.discard(account_id)
    else:
        selected.add(account_id)

    await state.update_data(selected_accounts=list(selected))

    # Refresh keyboard
    account_repo = PostgresAccountRepository(session)
    all_accounts = await account_repo.list_all(limit=100)
    accounts = [
        a for a in all_accounts
        if a.status in (AccountStatus.READY, AccountStatus.PAUSED, AccountStatus.ACTIVE)
        and a.session_data
    ]

    await callback.message.edit_reply_markup(
        reply_markup=get_scraper_accounts_multi_kb(accounts, selected),
    )
    await callback.answer()


@router.callback_query(F.data == "scraper:select_all", ScraperStates.selecting_account)
async def select_all_accounts(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Select all accounts."""
    account_repo = PostgresAccountRepository(session)
    all_accounts = await account_repo.list_all(limit=100)
    accounts = [
        a for a in all_accounts
        if a.status in (AccountStatus.READY, AccountStatus.PAUSED, AccountStatus.ACTIVE)
        and a.session_data
    ]

    selected = {str(a.id) for a in accounts}
    await state.update_data(selected_accounts=list(selected))

    await callback.message.edit_reply_markup(
        reply_markup=get_scraper_accounts_multi_kb(accounts, selected),
    )
    await callback.answer(f"Выбрано {len(selected)} аккаунтов")


@router.callback_query(F.data == "scraper:select_none", ScraperStates.selecting_account)
async def select_no_accounts(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Deselect all accounts."""
    await state.update_data(selected_accounts=[])

    account_repo = PostgresAccountRepository(session)
    all_accounts = await account_repo.list_all(limit=100)
    accounts = [
        a for a in all_accounts
        if a.status in (AccountStatus.READY, AccountStatus.PAUSED, AccountStatus.ACTIVE)
        and a.session_data
    ]

    await callback.message.edit_reply_markup(
        reply_markup=get_scraper_accounts_multi_kb(accounts, set()),
    )
    await callback.answer("Выбор сброшен")


@router.callback_query(F.data == "scraper:parallel:continue", ScraperStates.selecting_account)
async def parallel_continue_to_file(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Continue to file upload for parallel scraping."""
    data = await state.get_data()
    selected = data.get("selected_accounts", [])

    if len(selected) < 2:
        await callback.answer("Выберите минимум 2 аккаунта", show_alert=True)
        return

    await state.set_state(ScraperStates.waiting_channels_file)

    await callback.message.edit_text(
        f"⚡ <b>Параллельный парсинг</b>\n\n"
        f"📱 Выбрано аккаунтов: {len(selected)}\n\n"
        "📁 <b>Отправьте txt файл со списком каналов</b>\n\n"
        "Каналы будут автоматически распределены между аккаунтами.",
    )
    await callback.message.answer(
        "Отправьте txt файл:",
        reply_markup=get_cancel_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("scraper:account:"), ScraperStates.selecting_account)
async def select_account(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Account selected - ask for channels file."""
    account_id = UUID(callback.data.split(":")[-1])

    account_repo = PostgresAccountRepository(session)
    account = await account_repo.get_by_id(account_id)

    if not account:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    await state.update_data(account_id=str(account_id))
    await state.set_state(ScraperStates.waiting_channels_file)

    await callback.message.edit_text(
        f"📱 Аккаунт: <b>{account.username or account.phone}</b>\n\n"
        "📁 <b>Отправьте txt файл со списком каналов</b>\n\n"
        "Формат файла - по одной ссылке на строку:\n"
        "<code>https://t.me/channel1\n"
        "https://t.me/channel2\n"
        "@channel3</code>\n\n"
        "Поддерживаются форматы:\n"
        "• https://t.me/username\n"
        "• t.me/username\n"
        "• @username",
    )
    await callback.message.answer(
        "Отправьте txt файл:",
        reply_markup=get_cancel_kb(),
    )
    await callback.answer()


@router.message(ScraperStates.waiting_channels_file, F.document)
async def receive_channels_file(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Receive channels file and ask for campaign."""
    if not message.document.file_name.endswith(".txt"):
        await message.answer("❌ Отправьте txt файл")
        return

    # Download and parse file
    try:
        file = await message.bot.get_file(message.document.file_id)
        file_content = await message.bot.download_file(file.file_path)
        content = file_content.read().decode("utf-8")

        # Parse channels
        channels = []
        for line in content.strip().split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                channels.append(line)

        if not channels:
            await message.answer("❌ Файл пустой или не содержит ссылок")
            return

        await state.update_data(channels=channels)

        # Ask for campaign
        campaign_repo = PostgresCampaignRepository(session)
        campaigns = await campaign_repo.list_all(limit=50)

        await state.set_state(ScraperStates.selecting_campaign)

        await message.answer(
            f"✅ Загружено каналов: <b>{len(channels)}</b>\n\n"
            "📢 <b>Куда добавить собранные таргеты?</b>\n\n"
            "Выберите кампанию или соберите без добавления в кампанию.",
            reply_markup=get_scraper_campaign_select_kb(campaigns),
        )

    except Exception as e:
        logger.error("Error parsing channels file", error=str(e))
        await message.answer(f"❌ Ошибка чтения файла: {e}")


@router.callback_query(F.data.startswith("scraper:campaign:"), ScraperStates.selecting_campaign)
async def select_campaign_and_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Campaign selected - start scraping."""
    campaign_part = callback.data.split(":")[-1]
    campaign_id = None if campaign_part == "none" else UUID(campaign_part)

    data = await state.get_data()
    channels = data["channels"]
    parallel_mode = data.get("parallel_mode", False)
    selected_accounts = data.get("selected_accounts", [])

    account_repo = PostgresAccountRepository(session)

    if parallel_mode and len(selected_accounts) >= 2:
        # Parallel mode - multiple accounts
        accounts = []
        for acc_id_str in selected_accounts:
            acc = await account_repo.get_by_id(UUID(acc_id_str))
            if acc:
                accounts.append(acc)

        if len(accounts) < 2:
            await callback.answer("Недостаточно доступных аккаунтов", show_alert=True)
            await state.clear()
            return

        # Create scrape task
        task = ScrapeTask(
            account_id=accounts[0].id,  # Primary account for tracking
            campaign_id=campaign_id,
            sources=channels,
        )

        await state.update_data(campaign_id=str(campaign_id) if campaign_id else None)
        await state.set_state(ScraperStates.scraping)

        # Show progress
        await callback.message.edit_text(
            "⚡ <b>Запуск параллельного парсинга...</b>\n\n"
            f"📱 Аккаунтов: {len(accounts)}\n"
            f"📋 Каналов: {len(channels)}\n"
            f"📢 Кампания: {campaign_id or 'Без кампании'}\n\n"
            "⏳ Подключение аккаунтов...",
            reply_markup=get_scraper_progress_kb(str(task.id)),
        )
        await callback.answer()

        # Run parallel scraping in background
        user_id = callback.from_user.id
        asyncio.create_task(
            _run_parallel_scraping(
                user_id=user_id,
                accounts=accounts,
                task=task,
                message=callback.message,
                state=state,
            )
        )
    else:
        # Single account mode
        account_id = UUID(data["account_id"])
        account = await account_repo.get_by_id(account_id)

        if not account:
            await callback.answer("Аккаунт не найден", show_alert=True)
            await state.clear()
            return

        # Create scrape task
        task = ScrapeTask(
            account_id=account_id,
            campaign_id=campaign_id,
            sources=channels,
        )

        await state.update_data(campaign_id=str(campaign_id) if campaign_id else None)
        await state.set_state(ScraperStates.scraping)

        # Show progress
        await callback.message.edit_text(
            "🔍 <b>Запуск парсинга...</b>\n\n"
            f"📱 Аккаунт: {account.username or account.phone}\n"
            f"📋 Каналов: {len(channels)}\n"
            f"📢 Кампания: {campaign_id or 'Без кампании'}\n\n"
            "⏳ Подключение...",
            reply_markup=get_scraper_progress_kb(str(task.id)),
        )
        await callback.answer()

        # Run scraping in background
        user_id = callback.from_user.id
        asyncio.create_task(
            _run_scraping(
                user_id=user_id,
                account=account,
                task=task,
                message=callback.message,
                state=state,
                session_factory=session,
            )
        )


async def _run_scraping(
    user_id: int,
    account: Account,
    task: ScrapeTask,
    message: Message,
    state: FSMContext,
    session_factory,
) -> None:
    """Run scraping in background."""
    scraper = None
    try:
        # Load existing usernames from DB to avoid duplicates
        from src.infrastructure.database import get_session
        existing_usernames: set[str] = set()

        async with get_session() as session:
            target_repo = PostgresUserTargetRepository(session)
            existing_usernames = await target_repo.get_all_existing_usernames()
            logger.info(
                "Loaded existing usernames for deduplication",
                count=len(existing_usernames),
            )

        # Create progress callback
        async def update_progress(t: ScrapeTask):
            try:
                progress_text = (
                    f"🔍 <b>Парсинг...</b>\n\n"
                    f"📱 Аккаунт: {account.username or account.phone}\n"
                    f"📋 Прогресс: {t.processed_sources}/{t.total_sources}\n"
                    f"👥 Найдено: {len(t.collected_usernames)}\n"
                    f"🚫 В базе: {len(existing_usernames)} (пропускаются)\n"
                )
                if t.current_source:
                    progress_text += f"🔄 Текущий: {t.current_source[:30]}...\n"

                await message.edit_text(
                    progress_text,
                    reply_markup=get_scraper_progress_kb(str(t.id)),
                )
            except Exception:
                pass

        # Start scraper with existing usernames for filtering
        scraper = ScraperService(
            account=account,
            on_progress=lambda t: asyncio.create_task(update_progress(t)),
            existing_usernames=existing_usernames,
        )
        _active_scrapers[user_id] = scraper
        _active_tasks[user_id] = task

        await scraper.start()

        # Run scraping
        task = await scraper.run_scrape_task(task)

        # Save targets to campaign if specified
        from src.infrastructure.database import get_session
        import io
        from aiogram.types import BufferedInputFile

        async with get_session() as session:
            if task.campaign_id and task.collected_usernames:
                target_repo = PostgresUserTargetRepository(session)

                # Check for existing usernames
                existing = set()
                for username in task.collected_usernames:
                    existing_target = await target_repo.get_by_username(
                        task.campaign_id, username
                    )
                    if existing_target:
                        existing.add(username)

                # Create new targets
                new_usernames = [u for u in task.collected_usernames if u not in existing]
                targets = create_targets_from_usernames(
                    usernames=new_usernames,
                    campaign_id=task.campaign_id,
                    source="scraper",
                )

                for target in targets:
                    await target_repo.save(target)

                await session.commit()

                task.users_added = len(targets)
                task.users_skipped = len(existing)

        # Show results
        result_text = (
            f"✅ <b>Парсинг завершён!</b>\n\n"
            f"📋 Каналов обработано: {task.processed_sources}/{task.total_sources}\n"
            f"👥 Найдено пользователей: {len(task.collected_usernames)}\n"
        )

        if task.campaign_id:
            result_text += (
                f"✅ Добавлено в кампанию: {task.users_added}\n"
                f"⏭ Пропущено (дубли): {task.users_skipped}\n"
            )

        if task.failed_sources:
            result_text += f"\n⚠️ Ошибок: {len(task.failed_sources)}"

        try:
            await message.edit_text(
                result_text,
                reply_markup=get_scraper_result_kb(task.campaign_id),
            )
        except Exception as edit_err:
            logger.warning("Failed to edit message with results", error=str(edit_err))
            # Try sending new message instead
            await message.answer(result_text, reply_markup=get_scraper_result_kb(task.campaign_id))

        # Send txt file with usernames if no campaign selected
        if not task.campaign_id and task.collected_usernames:
            file_content = "\n".join(task.collected_usernames)
            file_bytes = file_content.encode("utf-8")
            input_file = BufferedInputFile(
                file_bytes,
                filename=f"usernames_{len(task.collected_usernames)}.txt",
            )
            await message.answer_document(
                input_file,
                caption=f"📄 Собранные username ({len(task.collected_usernames)} шт.)",
            )

    except Exception as e:
        logger.error("Scraping failed", error=str(e), exc_info=True)
        try:
            await message.edit_text(
                f"❌ <b>Ошибка парсинга</b>\n\n{str(e)[:200]}",
                reply_markup=get_scraper_menu_kb(),
            )
        except Exception:
            await message.answer(
                f"❌ <b>Ошибка парсинга</b>\n\n{str(e)[:200]}",
                reply_markup=get_scraper_menu_kb(),
            )

    finally:
        # Cleanup
        if scraper:
            await scraper.stop()
        _active_scrapers.pop(user_id, None)
        _active_tasks.pop(user_id, None)
        await state.clear()


async def _run_parallel_scraping(
    user_id: int,
    accounts: list[Account],
    task: ScrapeTask,
    message: Message,
    state: FSMContext,
) -> None:
    """Run parallel scraping with multiple accounts."""
    scraper = None
    try:
        # Load existing usernames from DB
        from src.infrastructure.database import get_session
        import io
        from aiogram.types import BufferedInputFile

        existing_usernames: set[str] = set()
        async with get_session() as session:
            target_repo = PostgresUserTargetRepository(session)
            existing_usernames = await target_repo.get_all_existing_usernames()
            logger.info(
                "Parallel: Loaded existing usernames",
                count=len(existing_usernames),
            )

        # Progress callback
        async def update_progress(t: ScrapeTask):
            try:
                progress_text = (
                    f"⚡ <b>Параллельный парсинг...</b>\n\n"
                    f"📱 Аккаунтов: {len(accounts)}\n"
                    f"📋 Прогресс: {t.processed_sources}/{t.total_sources}\n"
                    f"👥 Найдено: {len(t.collected_usernames)}\n"
                    f"🚫 В базе: {len(existing_usernames)} (пропускаются)\n"
                )
                if t.current_source:
                    progress_text += f"🔄 Текущий: {t.current_source[:30]}...\n"

                await message.edit_text(
                    progress_text,
                    reply_markup=get_scraper_progress_kb(str(t.id)),
                )
            except Exception:
                pass

        # Create parallel scraper
        scraper = ParallelScraperService(
            accounts=accounts,
            on_progress=lambda t: asyncio.create_task(update_progress(t)),
            existing_usernames=existing_usernames,
        )
        _active_parallel_scrapers[user_id] = scraper
        _active_tasks[user_id] = task

        # Connect all accounts
        connected = await scraper.start()
        logger.info("Parallel scraper: connected accounts", count=connected)

        if connected < 2:
            await message.edit_text(
                f"❌ <b>Недостаточно аккаунтов</b>\n\n"
                f"Подключено только {connected} из {len(accounts)}",
                reply_markup=get_scraper_menu_kb(),
            )
            return

        # Run scraping
        task = await scraper.run_scrape_task(task)

        # Save targets to campaign if specified
        async with get_session() as session:
            if task.campaign_id and task.collected_usernames:
                target_repo = PostgresUserTargetRepository(session)

                existing = await target_repo.get_existing_usernames(
                    list(task.collected_usernames),
                    task.campaign_id,
                )

                new_usernames = [u for u in task.collected_usernames if u not in existing]
                targets = create_targets_from_usernames(
                    usernames=new_usernames,
                    campaign_id=task.campaign_id,
                    source="parallel_scraper",
                )

                for target in targets:
                    await target_repo.save(target)

                await session.commit()

                task.users_added = len(targets)
                task.users_skipped = len(existing)

        # Show results
        result_text = (
            f"✅ <b>Параллельный парсинг завершён!</b>\n\n"
            f"📱 Использовано аккаунтов: {len(accounts)}\n"
            f"📋 Каналов обработано: {task.processed_sources}/{task.total_sources}\n"
            f"👥 Найдено пользователей: {len(task.collected_usernames)}\n"
        )

        if task.campaign_id:
            result_text += (
                f"✅ Добавлено в кампанию: {task.users_added}\n"
                f"⏭ Пропущено (дубли): {task.users_skipped}\n"
            )

        if task.failed_sources:
            result_text += f"\n⚠️ Ошибок: {len(task.failed_sources)}"

        try:
            await message.edit_text(
                result_text,
                reply_markup=get_scraper_result_kb(task.campaign_id),
            )
        except Exception:
            await message.answer(result_text, reply_markup=get_scraper_result_kb(task.campaign_id))

        # Send txt file if no campaign
        if not task.campaign_id and task.collected_usernames:
            file_content = "\n".join(task.collected_usernames)
            file_bytes = file_content.encode("utf-8")
            input_file = BufferedInputFile(
                file_bytes,
                filename=f"usernames_{len(task.collected_usernames)}.txt",
            )
            await message.answer_document(
                input_file,
                caption=f"📄 Собранные username ({len(task.collected_usernames)} шт.)",
            )

    except Exception as e:
        logger.error("Parallel scraping failed", error=str(e), exc_info=True)
        try:
            await message.edit_text(
                f"❌ <b>Ошибка парсинга</b>\n\n{str(e)[:200]}",
                reply_markup=get_scraper_menu_kb(),
            )
        except Exception:
            await message.answer(
                f"❌ <b>Ошибка парсинга</b>\n\n{str(e)[:200]}",
                reply_markup=get_scraper_menu_kb(),
            )

    finally:
        if scraper:
            await scraper.stop()
        _active_parallel_scrapers.pop(user_id, None)
        _active_tasks.pop(user_id, None)
        await state.clear()


# =============================================================================
# Cancel / Stop
# =============================================================================

@router.callback_query(F.data == "scraper:cancel")
async def cancel_scraping(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel scraping flow."""
    user_id = callback.from_user.id

    # Stop active scraper if any
    scraper = _active_scrapers.get(user_id)
    if scraper:
        scraper.cancel()

    parallel_scraper = _active_parallel_scrapers.get(user_id)
    if parallel_scraper:
        parallel_scraper.cancel()

    await state.clear()
    await callback.message.edit_text(
        "❌ Парсинг отменён",
        reply_markup=get_scraper_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("scraper:stop:"))
async def stop_scraping(callback: CallbackQuery, state: FSMContext) -> None:
    """Stop active scraping."""
    user_id = callback.from_user.id

    scraper = _active_scrapers.get(user_id)
    parallel_scraper = _active_parallel_scrapers.get(user_id)

    if scraper:
        scraper.cancel()
        await callback.answer("Останавливаем...")
    elif parallel_scraper:
        parallel_scraper.cancel()
        await callback.answer("Останавливаем параллельный парсинг...")
    else:
        await callback.answer("Парсинг не запущен", show_alert=True)


@router.message(F.text == "❌ Отмена", ScraperStates)
async def cancel_scraping_text(message: Message, state: FSMContext) -> None:
    """Cancel via text button."""
    user_id = message.from_user.id

    scraper = _active_scrapers.get(user_id)
    if scraper:
        scraper.cancel()

    await state.clear()
    await message.answer(
        "❌ Парсинг отменён",
        reply_markup=get_main_menu_kb(),
    )
