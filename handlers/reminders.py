"""
Фоновые напоминания клиентам за день (24 часа) до визита
и обработка подтверждения визита по кнопке из напоминания.
"""

from datetime import datetime, timedelta
import html
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import Config
from database import Database

logger = logging.getLogger(__name__)


async def send_reminders_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Периодическая задача: проверяет записи, до которых осталось <= 24 часов,
    и отправляет клиенту напоминание (1 раз).
    """
    db: Database = context.bot_data["db"]
    config: Config = context.bot_data["config"]

    appointments = await db.get_unreminded_upcoming_appointments()
    now = datetime.now()

    for app in appointments:
        appt_dt = datetime.strptime(
            f"{app['appointment_date']} {app['appointment_time']}",
            "%Y-%m-%d %H:%M",
        )
        time_left = appt_dt - now

        # Отправляем напоминание, если визит в будущем и до него осталось <= 24 часов
        if timedelta(0) < time_left <= timedelta(hours=24):
            formatted_date = appt_dt.strftime("%d.%m.%Y")
            client_name = html.escape(app.get("full_name") or "Гость")
            service_name = html.escape(app["service_name"])

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ Буду, подтверждаю",
                            callback_data=f"rem_confirm_{app['id']}",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "❌ Отменить запись",
                            callback_data=f"cancel_ask_{app['id']}",
                        )
                    ],
                ]
            )

            try:
                await context.bot.send_message(
                    chat_id=app["client_id"],
                    text=(
                        f"🔔 <b>Напоминание о визите в {html.escape(config.salon_name)}</b>\n\n"
                        f"Здравствуйте, <b>{client_name}</b>! Ждём вас совсем скоро:\n\n"
                        "<blockquote>"
                        f"💅 <b>Услуга:</b> {service_name}\n"
                        f"📅 <b>Дата:</b> {formatted_date}\n"
                        f"🕒 <b>Время:</b> {app['appointment_time']}\n"
                        f"📍 <b>Адрес:</b> <code>{html.escape(config.salon_address)}</code>"
                        "</blockquote>\n"
                        "Пожалуйста, подтвердите ваш визит или отмените запись, если планы изменились:"
                    ),
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )
                await db.mark_reminded(app["id"])
                logger.info("Отправлено напоминание по записи №%s", app["id"])
            except Exception as err:
                logger.warning(
                    "Не удалось отправить напоминание по записи №%s: %s",
                    app["id"],
                    err,
                )


async def handle_reminder_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Клиент нажал «✅ Буду, подтверждаю» в сообщении-напоминании."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer("Спасибо, ждём вас!")
    app_id = int(query.data.replace("rem_confirm_", ""))

    db: Database = context.bot_data["db"]
    config: Config = context.bot_data["config"]
    app = await db.get_appointment_by_id(app_id)

    await query.edit_message_text(
        f"✅ <b>Отлично! Визит по записи №{app_id} подтверждён.</b>\n\n"
        f"Ждём вас в студии <b>{html.escape(config.salon_name)}</b>!\n"
        f"📍 <code>{html.escape(config.salon_address)}</code>",
        parse_mode=ParseMode.HTML,
    )

    if config.admin_id and app:
        try:
            await context.bot.send_message(
                chat_id=config.admin_id,
                text=(
                    f"✅ <b>Клиент подтвердил визит (Запись №{app_id})</b>\n\n"
                    "<blockquote>"
                    f"👤 {html.escape(app.get('full_name') or 'Клиент')}\n"
                    f"💅 {html.escape(app['service_name'])}\n"
                    f"🕒 {app['appointment_date']} в {app['appointment_time']}"
                    "</blockquote>"
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception as notify_err:
            logger.warning("Не удалось уведомить админа о подтверждении: %s", notify_err)