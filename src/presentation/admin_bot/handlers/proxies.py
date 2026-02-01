"""
Proxy management handlers.
"""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.repositories import PostgresProxyRepository
from src.domain.entities import Proxy, ProxyType, ProxyStatus

from ..keyboards import (
    get_proxies_menu_kb,
    get_cancel_kb,
    get_main_menu_kb,
    get_back_kb,
)
from ..states import ProxyStates

router = Router(name="proxies")


@router.message(F.text == "🌐 Прокси")
async def proxies_menu(message: Message) -> None:
    """Show proxies menu."""
    await message.answer(
        "🌐 <b>Управление прокси</b>\n\n"
        "Выберите действие:",
        reply_markup=get_proxies_menu_kb(),
    )


@router.callback_query(F.data == "proxies:menu")
async def proxies_menu_callback(callback: CallbackQuery) -> None:
    """Show proxies menu via callback."""
    await callback.message.edit_text(
        "🌐 <b>Управление прокси</b>\n\n"
        "Выберите действие:",
        reply_markup=get_proxies_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "proxies:list")
async def proxies_list(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show list of proxies."""
    repo = PostgresProxyRepository(session)

    # Get proxies with assignment info
    proxies_with_assignment = await repo.list_all_with_assignment(limit=50)

    if not proxies_with_assignment:
        await callback.message.edit_text(
            "🌐 <b>Прокси</b>\n\n"
            "Список пуст. Добавьте прокси.",
            reply_markup=get_proxies_menu_kb(),
        )
        await callback.answer()
        return

    # Count by status and assignment
    by_status = {}
    assigned_count = 0
    for p, account_id in proxies_with_assignment:
        status = p.status.value
        by_status[status] = by_status.get(status, 0) + 1
        if account_id:
            assigned_count += 1

    available = await repo.count_available()
    total = len(proxies_with_assignment)

    text = (
        f"🌐 <b>Прокси</b> ({total})\n\n"
        f"<b>Свободно:</b> {available}\n"
        f"<b>Назначено:</b> {assigned_count}\n\n"
        f"<b>По статусам:</b>\n"
    )

    status_emoji = {
        "active": "🟢",
        "slow": "🟡",
        "unavailable": "🔴",
        "banned": "⛔",
        "unknown": "⚪",
    }

    for status, count in sorted(by_status.items()):
        emoji = status_emoji.get(status, "❓")
        text += f"  • {emoji} {status}: {count}\n"

    text += "\n<b>Список:</b>\n"

    for p, account_id in proxies_with_assignment[:10]:  # Show first 10
        emoji = status_emoji.get(p.status.value, "❓")
        assigned = " 📱" if account_id else " ✅"
        latency = f"{p.last_check_latency_ms}ms" if p.last_check_latency_ms else "—"
        text += f"{emoji} {p.host}:{p.port}{assigned} ({latency})\n"

    text += "\n<i>📱 = назначен, ✅ = свободен</i>"

    if total > 10:
        text += f"\n\n... и ещё {total - 10}"

    await callback.message.edit_text(
        text,
        reply_markup=get_proxies_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "proxies:add")
async def add_proxy_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start adding proxies."""
    await state.set_state(ProxyStates.waiting_proxy_list)
    
    await callback.message.edit_text(
        "➕ <b>Добавление прокси</b>\n\n"
        "Отправьте список прокси (каждый на новой строке).\n\n"
        "<b>Формат:</b>\n"
        "<code>type://host:port</code>\n"
        "<code>type://user:pass@host:port</code>\n\n"
        "<b>Поддерживаемые типы:</b>\n"
        "• socks5, socks4, http, https\n\n"
        "<i>Примеры:</i>\n"
        "<code>socks5://1.2.3.4:1080\n"
        "socks5://user:pass@1.2.3.4:1080\n"
        "http://proxy.example.com:8080</code>",
    )
    await callback.message.answer(
        "Ожидаю список прокси...",
        reply_markup=get_cancel_kb(),
    )
    await callback.answer()


@router.message(ProxyStates.waiting_proxy_list)
async def receive_proxy_list(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Receive and parse proxy list."""
    lines = message.text.strip().split("\n")
    
    proxies = []
    errors = []
    
    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        
        try:
            proxy = parse_proxy_url(line)
            proxies.append(proxy)
        except ValueError as e:
            errors.append(f"Строка {i}: {e}")
    
    if not proxies:
        await message.answer(
            "❌ Не удалось распознать ни одного прокси.\n\n"
            f"Ошибки:\n" + "\n".join(errors[:5]),
        )
        return
    
    # Save to database
    repo = PostgresProxyRepository(session)
    
    added = 0
    skipped = 0
    
    for proxy in proxies:
        existing = await repo.get_by_address(proxy.host, proxy.port)
        if existing:
            skipped += 1
            continue
        
        await repo.save(proxy)
        added += 1
    
    await state.clear()
    
    text = f"✅ <b>Прокси добавлены!</b>\n\n"
    text += f"Добавлено: {added}\n"
    
    if skipped:
        text += f"Пропущено (дубли): {skipped}\n"
    
    if errors:
        text += f"\nОшибки ({len(errors)}):\n"
        text += "\n".join(errors[:3])
        if len(errors) > 3:
            text += f"\n... и ещё {len(errors) - 3}"
    
    await message.answer(text, reply_markup=get_main_menu_kb())


@router.callback_query(F.data == "proxies:check")
async def check_proxies(callback: CallbackQuery, session: AsyncSession) -> None:
    """Start proxy health check."""
    from src.infrastructure.proxy.checker import get_proxy_checker
    
    repo = PostgresProxyRepository(session)
    proxies = await repo.list_all(limit=100)
    
    if not proxies:
        await callback.message.edit_text(
            "🌐 <b>Проверка прокси</b>\n\n"
            "Нет прокси для проверки.",
            reply_markup=get_proxies_menu_kb(),
        )
        await callback.answer()
        return
    
    # Show progress
    await callback.message.edit_text(
        f"🔄 <b>Проверка прокси...</b>\n\n"
        f"Проверяется: {len(proxies)} прокси\n"
        f"Подождите, это может занять до минуты...",
    )
    await callback.answer()
    
    # Run check with global checker
    checker = get_proxy_checker()
    results = await checker.check_all()
    
    # Update message with results
    await callback.message.edit_text(
        f"✅ <b>Проверка завершена!</b>\n\n"
        f"📊 <b>Результаты:</b>\n"
        f"• Всего: {results['total']}\n"
        f"• Работает: {results['passed']} ✅\n"
        f"• Недоступно: {results['failed']} ❌\n\n"
        f"<i>Статусы прокси обновлены.</i>",
        reply_markup=get_proxies_menu_kb(),
    )


def parse_proxy_url(url: str) -> Proxy:
    """
    Parse proxy URL into Proxy entity.
    
    Formats:
    - type://host:port
    - type://user:pass@host:port
    """
    import re
    
    # Pattern for proxy URL
    pattern = r'^(socks5|socks4|http|https)://(?:([^:]+):([^@]+)@)?([^:]+):(\d+)$'
    match = re.match(pattern, url.lower())
    
    if not match:
        raise ValueError(f"Неверный формат: {url}")
    
    proxy_type_str, username, password, host, port = match.groups()
    
    type_map = {
        "socks5": ProxyType.SOCKS5,
        "socks4": ProxyType.SOCKS4,
        "http": ProxyType.HTTP,
        "https": ProxyType.HTTPS,
    }
    
    return Proxy(
        host=host,
        port=int(port),
        proxy_type=type_map[proxy_type_str],
        username=username,
        password=password,
        status=ProxyStatus.UNKNOWN,
    )
