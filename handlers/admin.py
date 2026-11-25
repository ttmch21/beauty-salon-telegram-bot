"""
Панель администратора салона (/admin):
просмотр записей, база клиентов и управление записями.
"""

from datetime import datetime, timedelta
import html
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from config import Config
from database import Database

logger = logging.getLogger(__name__)


def _is_admin(update: Update, config: Config) -> bool:
    """Проверяет, является ли пользователь администратором из .env."""
    user = update.effective_user
    if not user or config.admin_id is None:
        return False
    return user.id == config.admin_id


def _format_date_ru(date_str: str) -> str:
    return datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")


def _admin_dashboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📅 На сегодня", callback_data="adm_today"),
                InlineKeyboardButton("📆 На завтра", callback_data="adm_tomorrow"),
            ],
            [
                InlineKeyboardButton(
                    "📋 Все ближайшие записи", callback_data="adm_upcoming"
                )
            ],
            [
                InlineKeyboardButton("👥 База клиентов", callback_data="adm_clients"),
                InlineKeyboardButton("🔄 Обновить", callback_data="adm_refresh"),
            ],
        ]
    )


async def _build_dashboard_text(db: Database, config: Config) -> str:
    stats = await db.get_admin_stats()
    return (
        f"🔐 <b>Панель администратора · {html.escape(config.salon_name)}</b>\n\n"
        "<blockquote>"
        f"📅 Записей на сегодня: <b>{stats['today_count']}</b>\n"
        f"🗓 Всего предстоящих записей: <b>{stats['upcoming_count']}</b>\n"
        f"👥 Клиентов в базе: <b>{stats['clients_count']}</b>"
        "</blockquote>\n"
        "👇 <i>Выберите нужный раздел:</i>"
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Открывает панель администратора по команде /admin."""
    if not update.message:
        return

    config: Config = context.bot_data["config"]
    if not _is_admin(update, config):
        if config.admin_id is None:
            logger.warning("Попытка входа в /admin, но ADMIN_ID не задан в .env.")
        await update.message.reply_text("⛔ У вас нет доступа к панели администратора.")
        return

    db: Database = context.bot_data["db"]
    text = await _build_dashboard_text(db, config)
    await update.message.reply_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=_admin_dashboard_keyboard(),
    )


def _format_appointments_list(
    title: str, appointments: list[dict]
) -> tuple[str, InlineKeyboardMarkup]:
    """Формирует красивый список записей с кнопками отмены для админа."""
    if not appointments:
        text = f"{title}\n\n<blockquote>Активных записей нет.</blockquote>"
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("← Назад в админку", callback_data="adm_back")]]
        )
        return text, keyboard

    lines = [f"{title}\n"]
    buttons = []

    for app in appointments[:15]:
        name = html.escape(app.get("full_name") or "Без имени")
        phone = html.escape(app.get("phone") or "не указан")
        service = html.escape(app["service_name"])
        price = html.escape(app["price"])
        username = f" (@{html.escape(app['username'])})" if app.get("username") else ""
        date_ru = _format_date_ru(app["appointment_date"])

        lines.append(
            "<blockquote>"
            f"📌 <b>№{app['id']}</b> · <b>{date_ru} в {app['appointment_time']}</b>\n"
            f"💅 {service} (<code>{price}</code>)\n"
            f"👤 {name}{username}\n"
            f"📱 <code>{phone}</code>"
            "</blockquote>"
        )
        buttons.append(
            [
                InlineKeyboardButton(
                    f"❌ Отменить №{app['id']} ({app['appointment_time']} · {name})",
                    callback_data=f"adm_cancel_ask_{app['id']}",
                )
            ]
        )

    buttons.append([InlineKeyboardButton("← Назад в админку", callback_data="adm_back")])
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


async def handle_admin_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Обрабатывает все нажатия кнопок внутри панели администратора."""
    query = update.callback_query
    if not query or not query.data:
        return

    config: Config = context.bot_data["config"]
    if not _is_admin(update, config):
        await query.answer("⛔ Доступ запрещён.", show_alert=True)
        return

    db: Database = context.bot_data["db"]
    data = query.data

    if data in ("adm_back", "adm_refresh"):
        text = await _build_dashboard_text(db, config)
        try:
            await query.edit_message_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=_admin_dashboard_keyboard(),
            )
            await query.answer("🔄 Обновлено" if data == "adm_refresh" else None)
        except BadRequest as err:
            if "Message is not modified" in str(err):
                await query.answer("✅ Данные уже актуальны")
            else:
                raise
        return

    await query.answer()

    if data == "adm_today":
        today = datetime.now().strftime("%Y-%m-%d")
        apps = await db.get_appointments_by_date(today)
        text, kb = _format_appointments_list(
            f"📅 <b>Записи на сегодня ({_format_date_ru(today)})</b>", apps
        )
        await query.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    if data == "adm_tomorrow":
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        apps = await db.get_appointments_by_date(tomorrow)
        text, kb = _format_appointments_list(
            f"📆 <b>Записи на завтра ({_format_date_ru(tomorrow)})</b>", apps
        )
        await query.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    if data == "adm_upcoming":
        apps = await db.get_upcoming_appointments()
        text, kb = _format_appointments_list("📋 <b>Все ближайшие записи</b>", apps)
        await query.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    if data == "adm_clients":
        clients = await db.get_all_clients()
        if not clients:
            text = "👥 <b>База клиентов</b>\n\n<blockquote>Клиентов пока нет.</blockquote>"
        else:
            lines = [f"👥 <b>База клиентов (всего: {len(clients)})</b>\n"]
            for cl in clients[:20]:
                name = html.escape(cl.get("full_name") or "Гость")
                phone = html.escape(cl.get("phone") or "телефон не указан")
                username = (
                    f" · @{html.escape(cl['username'])}" if cl.get("username") else ""
                )
                lines.append(
                    "<blockquote>"
                    f"👤 <b>{name}</b>{username}\n"
                    f"📱 <code>{phone}</code>\n"
                    f"📊 Активных записей: <b>{cl['active_count']}</b> (всего: {cl['total_count']})"
                    "</blockquote>"
                )
            text = "\n".join(lines)

        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("← Назад в админку", callback_data="adm_back")]]
        )
        await query.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    if data.startswith("adm_cancel_ask_"):
        app_id = int(data.replace("adm_cancel_ask_", ""))
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Да, отменить запись", callback_data=f"adm_cancel_yes_{app_id}"
                    ),
                    InlineKeyboardButton("← Назад", callback_data="adm_upcoming"),
                ]
            ]
        )
        await query.edit_message_text(
            f"❓ Отменить запись <b>№{app_id}</b>? Клиент получит уведомление об отмене.",
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
        return

    if data.startswith("adm_cancel_yes_"):
        app_id = int(data.replace("adm_cancel_yes_", ""))
        app = await db.get_appointment_by_id(app_id)
        cancelled = await db.cancel_appointment(app_id)

        if cancelled and app:
            try:
                await context.bot.send_message(
                    chat_id=app["client_id"],
                    text=(
                        f"ℹ️ <b>Запись №{app_id} отменена администратором</b>\n\n"
                        "<blockquote>"
                        f"💅 Услуга: {html.escape(app['service_name'])}\n"
                        f"📅 Дата: {_format_date_ru(app['appointment_date'])} в {app['appointment_time']}"
                        "</blockquote>\n"
                        "Если вы хотите перенести визит на другое время, выберите удобное окно "
                        "через кнопку <b>«🗓 Записаться»</b> или свяжитесь с нами."
                    ),
                    parse_mode=ParseMode.HTML,
                )
            except Exception as notify_err:
                logger.warning(
                    "Не удалось уведомить клиента %s: %s", app["client_id"], notify_err
                )

            msg = f"✅ Запись <b>№{app_id}</b> отменена, клиент уведомлён."
        else:
            msg = "Запись уже была отменена или не найдена."

        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📋 К записям", callback_data="adm_upcoming")],
                [InlineKeyboardButton("← В админку", callback_data="adm_back")],
            ]
        )
        await query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=kb)