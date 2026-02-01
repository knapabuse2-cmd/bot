# Telegram Outreach System - Natural Dialogue

Система автоматизированного общения с естественным поведением.

## Ключевые возможности

### Естественное поведение
- **Message Batching** — ждёт пока user закончит печатать (3 сек пауза)
- **Read Receipts** — отмечает сообщения прочитанными (✓✓)
- **Typing Simulation** — показывает "печатает..." пропорционально длине
- **Message Splitting** — разбивает ответ на несколько сообщений по `|||`

### Спецкоманды AI
| Команда | Действие |
|---------|----------|
| `[SEND_LINKS]` | Отправляет ссылки из campaign, помечает goal_reached |
| `[NEGATIVE_FINISH]` | Завершает диалог (отказ/грубость/оффтоп) |
| `[CREATIVE_SENT]` | Помечает что креатив отправлен |
| `[HANDOFF]` | Ставит на паузу для ручной проверки |

## Структура

```
src/
├── application/
│   ├── prompts.py                    # Промпты (CRYPTO_TRADER_PROMPT)
│   └── services/
│       ├── dialogue_processor.py     # Parser, Batcher, Typing
│       └── account_auth.py           # 2FA авторизация
├── infrastructure/
│   ├── telegram/
│   │   └── client.py                 # Telegram клиент (read/typing)
│   ├── database/repositories/
│   │   ├── dialogue_repo.py          # Репозиторий диалогов
│   │   └── ...
│   └── redis/
│       └── locks.py                  # Distributed locks
└── workers/
    └── natural_worker.py             # Основной worker
```

## Flow диалога

```
User sends messages
        │
        ▼
┌───────────────────┐
│  MessageBatcher   │  ← Ждёт 3 сек после последнего
└───────────────────┘
        │
        ▼
┌───────────────────┐
│  mark_as_read()   │  ← Галочки ✓✓
└───────────────────┘
        │
        ▼
┌───────────────────┐
│  Reading delay    │  ← 1-8 сек (по длине текста)
└───────────────────┘
        │
        ▼
┌───────────────────┐
│  AI Generation    │  ← Генерация ответа
└───────────────────┘
        │
        ▼
┌───────────────────┐
│  ResponseParser   │  ← Split по ||| + extract command
└───────────────────┘
        │
        ▼
┌───────────────────┐
│  type_and_wait()  │  ← "печатает..." 1-12 сек
└───────────────────┘
        │
        ▼
┌───────────────────┐
│  send_message()   │  ← Отправка
└───────────────────┘
        │
   (repeat for each message)
        │
        ▼
┌───────────────────┐
│  Handle Action    │  ← SEND_LINKS / NEGATIVE_FINISH / etc
└───────────────────┘
```

## Пример диалога

```
[00:00] BOT → "ты на фьючах торгуешь или спот?"
        
[00:15] USER → "только спот пока"
        ├─ Batcher ждёт 3 сек
        ├─ Mark as read ✓✓
        ├─ Reading delay 2 сек
        ├─ AI: "понял ||| а давно в крипте?"
        ├─ Typing 3 сек → Send "понял"
        ├─ Pause 1.5 сек
        └─ Typing 4 сек → Send "а давно в крипте?"

[01:00] USER → "слушай а есть норм каналы?"
        ├─ AI: "есть пара ||| сам долго искал ||| хочешь скину?" [CREATIVE_SENT]
        ├─ Send 3 messages
        └─ dialogue.creative_sent = True

[01:30] USER → "давай"
        ├─ AI: "лови [SEND_LINKS]"
        ├─ Send "лови"
        ├─ Send campaign links
        └─ dialogue.status = GOAL_REACHED ✓
```

## Использование

```python
from src.application.prompts import get_crypto_trader_prompt

# Получить промпт
prompt = get_crypto_trader_prompt(
    links="https://t.me/channel1\nhttps://t.me/channel2"
)

# Или кастомный
from src.application.prompts import build_custom_prompt

prompt = build_custom_prompt(
    role="Ты инвестор с 5-летним опытом...",
    goal="Привести к подписке на канал",
    links="https://t.me/mychannel",
)
```

## Установка

```bash
tar -xzf telegram-outreach-fixes.tar.gz
cp -r telegram-outreach-fixes/* /path/to/project/

# Миграции
alembic upgrade head

# Запуск
python -m src.workers.main
```

## Исправленные проблемы

- ✅ Session lifecycle (fresh session per operation)
- ✅ Race conditions (distributed locks + FOR UPDATE)
- ✅ Memory leaks (proper task cleanup)
- ✅ Redis connection leaks
- ✅ Optimistic locking
- ✅ 2FA support
- ✅ Natural dialogue (batching, typing, splitting)

### 🔴 Критические исправления

#### 1. Session Lifecycle в WorkerManager
**Проблема**: Session закрывалась после выхода из `async with`, но worker продолжал работать.

**Решение**: Реализован паттерн Session Factory — каждый worker получает функцию для создания сессий per-operation.

**Файл**: `src/workers/manager.py`

#### 2. Race Condition в Target Distribution
**Проблема**: Два concurrent вызова могли назначить один target разным accounts.

**Решение**: 
- Добавлен `DistributedLock` через Redis
- Метод `list_pending_for_update()` использует `SELECT ... FOR UPDATE SKIP LOCKED`

**Файлы**: 
- `src/infrastructure/redis/locks.py`
- `src/infrastructure/database/repositories/target_repo.py`

#### 3. Memory Leak в AccountWorker
**Проблема**: При повторном вызове `start()` старый task терялся.

**Решение**: Добавлена проверка и отмена существующего task перед созданием нового.

**Файл**: `src/workers/account_worker.py`

#### 4. Redis Connection не закрывалась
**Проблема**: В `on_shutdown` отсутствовал вызов `close_redis()`.

**Решение**: Добавлен вызов `close_redis()` во все точки выхода.

**Файл**: `src/presentation/admin_bot/main.py`

---

### 🟡 Серьёзные исправления

#### 5. Optimistic Locking
**Проблема**: Поле `version` не проверялось при save.

**Решение**: Реализована проверка в `BaseRepository.save()`.

**Файл**: `src/infrastructure/database/repositories/base.py`

#### 6. Thread-Safe AI Provider Singleton
**Проблема**: Race condition при инициализации singleton.

**Решение**: Добавлен `asyncio.Lock` для thread-safe инициализации.

**Файл**: `src/infrastructure/ai/openai_provider.py`

#### 7. Отсутствовала обработка 2FA
**Проблема**: `SessionPasswordNeededError` не обрабатывалась.

**Решение**: Создан полноценный `AccountAuthService` с поддержкой всех этапов авторизации.

**Файл**: `src/application/services/account_auth.py`

---

## 📁 Структура исправлений

```
telegram-outreach-fixes/
├── src/
│   ├── config/
│   │   └── settings.py              # Обновленные настройки
│   ├── workers/
│   │   ├── __init__.py
│   │   ├── main.py                  # Entry point для worker manager
│   │   ├── manager.py               # Исправленный manager
│   │   └── account_worker.py        # Исправленный worker
│   ├── infrastructure/
│   │   ├── database/
│   │   │   └── repositories/
│   │   │       ├── base.py          # С optimistic locking
│   │   │       ├── account_repo.py  # С counter reset methods
│   │   │       └── target_repo.py   # С FOR UPDATE
│   │   ├── redis/
│   │   │   ├── __init__.py
│   │   │   └── locks.py             # Distributed locks
│   │   └── ai/
│   │       └── openai_provider.py   # Thread-safe singleton
│   ├── application/
│   │   └── services/
│   │       └── account_auth.py      # 2FA support
│   └── presentation/
│       └── admin_bot/
│           └── main.py              # Proper shutdown
├── migrations/
│   ├── env.py                       # Alembic environment
│   └── script.py.mako               # Migration template
├── tests/
│   ├── conftest.py                  # Pytest fixtures
│   └── unit/
│       ├── domain/
│       │   └── test_entities.py     # Domain tests
│       └── infrastructure/
│           └── test_locks.py        # Lock tests
└── README.md
```

---

## 🚀 Инструкция по применению

### 1. Скопируйте файлы

```bash
# Скопируйте все файлы из telegram-outreach-fixes в ваш проект
cp -r telegram-outreach-fixes/* /path/to/your/project/
```

### 2. Добавьте недостающие зависимости

```bash
# Добавьте в pyproject.toml если отсутствует
pip install aiosqlite  # для тестов
```

### 3. Создайте начальную миграцию

```bash
cd /path/to/your/project

# Создайте директорию для миграций
mkdir -p migrations/versions

# Сгенерируйте миграцию
alembic revision --autogenerate -m "Initial migration"

# Примените миграцию
alembic upgrade head
```

### 4. Запустите тесты

```bash
# Установите dev зависимости
pip install -e ".[dev]"

# Запустите тесты
pytest tests/ -v

# С coverage
pytest tests/ -v --cov=src --cov-report=html
```

### 5. Запустите систему

```bash
# Через Docker
docker-compose up -d

# Или локально (в разных терминалах)
python -m src.presentation.admin_bot.main  # Admin Bot
python -m src.workers.main                  # Worker Manager
```

---

## ⚠️ Breaking Changes

### WorkerManager.start_worker()
**Было**: Принимал `Account` entity
**Стало**: Принимает `UUID` account_id

```python
# Было
await manager.start_worker(account)

# Стало
await manager.start_worker(account.id)
```

### AccountWorker.__init__()
**Было**: Принимал готовые services
**Стало**: Принимает session_factory

```python
# Было
worker = AccountWorker(
    account=account,
    account_service=account_service,
    dialogue_service=dialogue_service,
)

# Стало
worker = AccountWorker(
    account=account,
    session_factory=get_session,
    ai_provider=get_ai_provider(),
)
```

---

## 📊 Покрытие тестами

| Модуль | Покрытие |
|--------|----------|
| Domain Entities | ✅ 90%+ |
| Redis Locks | ✅ 85%+ |
| Repositories | ⏳ To Do |
| Services | ⏳ To Do |
| Workers | ⏳ To Do |

---

## 🔜 Рекомендации на будущее

1. **Добавить integration tests** с реальными PostgreSQL/Redis через testcontainers
2. **Реализовать circuit breaker** для OpenAI provider
3. **Добавить metrics** (Prometheus/Grafana)
4. **Настроить CI/CD** с GitHub Actions
5. **Добавить rate limiter** для REST API

---

## 📝 Changelog

### v1.0.0 (2024-XX-XX)
- ✅ Fixed session lifecycle in WorkerManager
- ✅ Added distributed locks for target assignment
- ✅ Fixed memory leak in AccountWorker
- ✅ Added proper shutdown sequence
- ✅ Implemented optimistic locking
- ✅ Thread-safe AI provider singleton
- ✅ Full 2FA support
- ✅ Added unit tests
- ✅ Added Alembic migrations setup
