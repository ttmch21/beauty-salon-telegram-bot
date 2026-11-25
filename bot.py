"""
Точка входа для Telegram-бота салона красоты.
Этап 5 (финальный): Фоновые напоминания за день до записи.
"""

import logging

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import load_config
from database import Database
from handlers.admin import admin_command, handle_admin_callback
from handlers.booking import (
    build_booking_conversation_handler,
    handle_cancel_appointment_confirm,
    handle_cancel_appointment_request,
)
from handlers.menu import (
    handle_service_category,
    help_command,
    show_contacts,
    show_my_booking,
    show_services,
    start_command,
    unknown_text,
)
from handlers.reminders import handle_reminder_confirm, send_reminders_job
from keyboards import BTN_CONTACT, BTN_MY_BOOKING, BTN_SERVICES

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    """Инициализация базы данных и настройка меню команд при запуске бота."""
    db: Database = application.bot_data["db"]
    await db.init_db()
    logger.info("База данных SQLite готова к работе.")

    await application.bot.set_my_commands(
        [
            BotCommand("start", "Главное меню салона"),
            BotCommand("help", "Справка по работе бота"),
        ]
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Глобальный перехватчик ошибок."""
    logger.error("Ошибка при обработке обновления:", exc_info=context.error)

    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "Произошла техническая ошибка. Пожалуйста, попробуйте чуть позже."
            )
        except Exception as send_error:
            logger.error("Не удалось отправить сообщение об ошибке: %s", send_error)


def main() -> None:
    """Сборка и запуск приложения."""
    config = load_config()
    db = Database(config.db_path)

    application = (
        Application.builder()
        .token(config.bot_token)
        .post_init(post_init)
        .build()
    )

    application.bot_data["config"] = config
    application.bot_data["db"] = db

    # Диалог онлайн-записи
    application.add_handler(build_booking_conversation_handler())

    # Команды
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("admin", admin_command))

    # Кнопки главного меню
    application.add_handler(MessageHandler(filters.Text([BTN_SERVICES]), show_services))
    application.add_handler(MessageHandler(filters.Text([BTN_MY_BOOKING]), show_my_booking))
    application.add_handler(MessageHandler(filters.Text([BTN_CONTACT]), show_contacts))

    # Inline-кнопки интерактивного прайс-листа
    application.add_handler(
        CallbackQueryHandler(handle_service_category, pattern="^cat_")
    )

    # Inline-кнопки отмены записи клиентом
    application.add_handler(
        CallbackQueryHandler(handle_cancel_appointment_request, pattern="^cancel_ask_")
    )
    application.add_handler(
        CallbackQueryHandler(
            handle_cancel_appointment_confirm, pattern="^cancel_(yes_|no$)"
        )
    )

    # Inline-кнопка подтверждения визита из напоминания
    application.add_handler(
        CallbackQueryHandler(handle_reminder_confirm, pattern="^rem_confirm_")
    )

    # Inline-кнопки панели администратора
    application.add_handler(
        CallbackQueryHandler(handle_admin_callback, pattern="^adm_")
    )

    # Любой другой текст
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_text)
    )

    application.add_error_handler(error_handler)

    # Запускаем фоновую проверку напоминаний (первый запуск через 10 сек, далее каждую минуту)
    if application.job_queue:
        application.job_queue.run_repeating(
            send_reminders_job,
            interval=60,
            first=10,
        )
        logger.info("Планировщик напоминаний запущен.")
    else:
        logger.warning(
            "JobQueue недоступен! Установите: pip install \"python-telegram-bot[job-queue]\""
        )

    logger.info("Бот салона «%s» запущен...", config.salon_name)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    try:
        main()
    except ValueError as config_error:
        logger.critical("Ошибка конфигурации: %s", config_error)
    except Exception as fatal_error:
        logger.critical("Критическая ошибка запуска: %s", fatal_error)