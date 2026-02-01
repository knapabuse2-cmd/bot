"""
Comment Bot module.

Отдельный бот для управления комментариями в Telegram каналах.

Структура:
- domain/ - Сущности (Account, CommentTask)
- infrastructure/ - БД, Telegram клиент
- application/ - Сервисы (авторизация, постинг)
- presentation/ - Telegram бот для управления

Запуск:
    python -m src.commentbot.presentation.admin_bot.main
"""
