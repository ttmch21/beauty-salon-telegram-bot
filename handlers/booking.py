"""
Пошаговая онлайн-запись на процедуры (ConversationHandler) и отмена записи.
Включает уведомления администратора о новых записях и отменах.
"""

from datetime import datetime, timedelta
import html
import logging
import re

import aiosqlite
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import Config
from database import Database
from handlers.menu import (
    help_command,
    show_contacts,
    show_my_booking,
    show_services,
    start_command,
)
from keyboards import (
    BTN_BOOK,
    BTN_CONTACT,
    BTN_MY_BOOKING,
    BTN_SERVICES,
    get_main_menu_keyboard,
)

logger = logging.getLogger(__name__)

(
    SELECT_CATEGORY,
    SELECT_SERVICE,
    SELECT_DATE,
    SELECT_TIME,
    ASK_SAVED_PROFILE,
    ENTER_NAME,
    ENTER_PHONE,
    CONFIRM_BOOKING,
) = range(8)

CATALOG = {
    "nails": {
        "title": "💅 Ногтевой сервис",
        "services": {
            "nails_1": ("Маникюр + гель-лак", "2 200 ₽"),
            "nails_2": ("Смарт-педикюр", "2 800 ₽"),
            "nails_3": ("Укрепление / Наращивание", "от 3 200 ₽"),
        },
    },
    "hair": {
        "title": "💇‍♀️ Волосы",
        "services": {
            "hair_1": ("Женская стрижка + укладка", "2 500 ₽"),
            "hair_2": ("Сложное окрашивание", "от 6 500 ₽"),
            "hair_3": ("Спа-уход для волос", "3 400 ₽"),
        },
    },
    "brows": {
        "title": "✨ Брови и ресницы",
        "services": {
            "brows_1": ("Архитектура и окрашивание бровей", "1 400 ₽"),
            "brows_2": ("Долговременная укладка бровей", "2 100 ₽"),
            "brows_3": ("Ламинирование ресниц", "2 400 ₽"),
        },
    },
}

TIME_SLOTS = ["10:00", "11:30", "13:00", "14:30", "16:00", "17:30", "19:00"]
WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _format_date_ru(date_str: str) -> str:
    """Преобразует YYYY-MM-DD в удобный формат вроде 'Чт, 26.11.2026'."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    weekday = WEEKDAYS_RU[dt.weekday()]
    return f"{weekday}, {dt.strftime('%d.%m.%Y')}"


def _categories_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(cat["title"], callback_data=f"bk_cat_{key}")]
        for key, cat in CATALOG.items()
    ]
    buttons.append([InlineKeyboardButton("✖️ Отмена", callback_data="bk_cancel")])
    return InlineKeyboardMarkup(buttons)


def _services_keyboard(cat_key: str) -> InlineKeyboardMarkup:
    services = CATALOG[cat_key]["services"]
    buttons = [
        [
            InlineKeyboardButton(
                f"{name} · {price}",
                callback_data=f"bk_srv_{srv_id}",
            )
        ]
        for srv_id, (name, price) in services.items()
    ]
    buttons.append(
        [
            InlineKeyboardButton("← Назад", callback_data="bk_back_cats"),
            InlineKeyboardButton("✖️ Отмена", callback_data="bk_cancel"),
        ]
    )
    return InlineKeyboardMarkup(buttons)


def _dates_keyboard() -> InlineKeyboardMarkup:
    """Генерирует кнопки на 7 ближайших дней по 2 в ряд."""
    today = datetime.now().date()
    buttons = []
    row = []

    for offset in range(7):
        day = today + timedelta(days=offset)
        date_str = day.strftime("%Y-%m-%d")
        if offset == 0:
            label = f"Сегодня ({day.strftime('%d.%m')})"
        elif offset == 1:
            label = f"Завтра ({day.strftime('%d.%m')})"
        else:
            label = f"{WEEKDAYS_RU[day.weekday()]}, {day.strftime('%d.%m')}"

        row.append(InlineKeyboardButton(label, callback_data=f"bk_date_{date_str}"))
        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append(
        [
            InlineKeyboardButton("← Назад", callback_data="bk_back_srvs"),
            InlineKeyboardButton("✖️ Отмена", callback_data="bk_cancel"),
        ]
    )
    return InlineKeyboardMarkup(buttons)


async def _times_keyboard(db: Database, date_str: str) -> tuple[InlineKeyboardMarkup, int]:
    """Формирует кнопки только со свободными слотами на выбранную дату."""
    booked = set(await db.get_booked_times(date_str))
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    available_slots = []
    for slot in TIME_SLOTS:
        if slot in booked:
            continue
        if date_str == today_str:
            slot_dt = datetime.strptime(f"{date_str} {slot}", "%Y-%m-%d %H:%M")
            if slot_dt <= now + timedelta(minutes=30):
                continue
        available_slots.append(slot)

    buttons = []
    row = []
    for slot in available_slots:
        row.append(InlineKeyboardButton(f"🕒 {slot}", callback_data=f"bk_time_{slot}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append(
        [
            InlineKeyboardButton("← Другая дата", callback_data="bk_back_dates"),
            InlineKeyboardButton("✖️ Отмена", callback_data="bk_cancel"),
        ]
    )
    return InlineKeyboardMarkup(buttons), len(available_slots)


async def start_booking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Точка входа в запись (через кнопку меню или inline-кнопку)."""
    context.user_data["booking"] = {}

    text = (
        "🗓 <b>Онлайн-запись · Шаг 1 из 5</b>\n\n"
        "Выберите категорию процедуры:"
    )

    if update.callback_query:
        await update.callback_query.answer()
        if update.callback_query.message:
            await update.callback_query.message.reply_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=_categories_keyboard(),
            )
    elif update.message:
        await update.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=_categories_keyboard(),
        )

    return SELECT_CATEGORY


async def select_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор категории и показ услуг в ней."""
    query = update.callback_query
    if not query or not query.data:
        return SELECT_CATEGORY

    await query.answer()

    if query.data == "bk_back_cats":
        await query.edit_message_text(
            "🗓 <b>Онлайн-запись · Шаг 1 из 5</b>\n\nВыберите категорию процедуры:",
            parse_mode=ParseMode.HTML,
            reply_markup=_categories_keyboard(),
        )
        return SELECT_CATEGORY

    cat_key = query.data.replace("bk_cat_", "")
    if cat_key not in CATALOG:
        return SELECT_CATEGORY

    context.user_data.setdefault("booking", {})["cat_key"] = cat_key
    cat_title = CATALOG[cat_key]["title"]

    await query.edit_message_text(
        f"🗓 <b>Онлайн-запись · Шаг 2 из 5</b>\n"
        f"Категория: <b>{cat_title}</b>\n\n"
        "Выберите нужную услугу:",
        parse_mode=ParseMode.HTML,
        reply_markup=_services_keyboard(cat_key),
    )
    return SELECT_SERVICE


async def select_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор услуги и переход к выбору даты."""
    query = update.callback_query
    if not query or not query.data:
        return SELECT_SERVICE

    await query.answer()

    if query.data == "bk_back_cats":
        await query.edit_message_text(
            "🗓 <b>Онлайн-запись · Шаг 1 из 5</b>\n\nВыберите категорию процедуры:",
            parse_mode=ParseMode.HTML,
            reply_markup=_categories_keyboard(),
        )
        return SELECT_CATEGORY

    if query.data == "bk_back_srvs":
        cat_key = context.user_data.get("booking", {}).get("cat_key", "nails")
        await query.edit_message_text(
            f"🗓 <b>Онлайн-запись · Шаг 2 из 5</b>\n"
            f"Категория: <b>{CATALOG[cat_key]['title']}</b>\n\n"
            "Выберите нужную услугу:",
            parse_mode=ParseMode.HTML,
            reply_markup=_services_keyboard(cat_key),
        )
        return SELECT_SERVICE

    srv_id = query.data.replace("bk_srv_", "")
    cat_key = context.user_data.get("booking", {}).get("cat_key")
    if not cat_key or srv_id not in CATALOG[cat_key]["services"]:
        return SELECT_SERVICE

    service_name, price = CATALOG[cat_key]["services"][srv_id]
    booking = context.user_data["booking"]
    booking["service_name"] = service_name
    booking["price"] = price

    await query.edit_message_text(
        f"🗓 <b>Онлайн-запись · Шаг 3 из 5</b>\n"
        f"Услуга: <b>{service_name}</b> (<code>{price}</code>)\n\n"
        "Выберите удобную дату:",
        parse_mode=ParseMode.HTML,
        reply_markup=_dates_keyboard(),
    )
    return SELECT_DATE


async def select_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор даты и показ свободных временных окон."""
    query = update.callback_query
    if not query or not query.data:
        return SELECT_DATE

    await query.answer()

    if query.data == "bk_back_srvs":
        cat_key = context.user_data.get("booking", {}).get("cat_key", "nails")
        await query.edit_message_text(
            f"🗓 <b>Онлайн-запись · Шаг 2 из 5</b>\n"
            f"Категория: <b>{CATALOG[cat_key]['title']}</b>\n\n"
            "Выберите нужную услугу:",
            parse_mode=ParseMode.HTML,
            reply_markup=_services_keyboard(cat_key),
        )
        return SELECT_SERVICE

    if query.data == "bk_back_dates":
        booking = context.user_data.get("booking", {})
        await query.edit_message_text(
            f"🗓 <b>Онлайн-запись · Шаг 3 из 5</b>\n"
            f"Услуга: <b>{booking.get('service_name', '')}</b> "
            f"(<code>{booking.get('price', '')}</code>)\n\n"
            "Выберите удобную дату:",
            parse_mode=ParseMode.HTML,
            reply_markup=_dates_keyboard(),
        )
        return SELECT_DATE

    date_str = query.data.replace("bk_date_", "")
    booking = context.user_data.setdefault("booking", {})
    booking["date"] = date_str

    db: Database = context.bot_data["db"]
    keyboard, free_count = await _times_keyboard(db, date_str)

    if free_count == 0:
        await query.edit_message_text(
            f"😔 На <b>{_format_date_ru(date_str)}</b> свободных окон уже нет.\n\n"
            "Пожалуйста, выберите другой день:",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
        return SELECT_TIME

    await query.edit_message_text(
        f"🗓 <b>Онлайн-запись · Шаг 4 из 5</b>\n"
        f"Услуга: <b>{booking['service_name']}</b>\n"
        f"Дата: <b>{_format_date_ru(date_str)}</b>\n\n"
        "Выберите свободное время:",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
    return SELECT_TIME


async def select_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор времени и проверка, есть ли уже сохранённые контакты клиента."""
    query = update.callback_query
    if not query or not query.data:
        return SELECT_TIME

    await query.answer()

    if query.data == "bk_back_dates":
        booking = context.user_data.get("booking", {})
        await query.edit_message_text(
            f"🗓 <b>Онлайн-запись · Шаг 3 из 5</b>\n"
            f"Услуга: <b>{booking.get('service_name', '')}</b> "
            f"(<code>{booking.get('price', '')}</code>)\n\n"
            "Выберите удобную дату:",
            parse_mode=ParseMode.HTML,
            reply_markup=_dates_keyboard(),
        )
        return SELECT_DATE

    time_str = query.data.replace("bk_time_", "")
    booking = context.user_data.setdefault("booking", {})
    booking["time"] = time_str

    db: Database = context.bot_data["db"]
    user = update.effective_user
    client = await db.get_client(user.id) if user else None

    if client and client.get("phone"):
        booking["saved_name"] = client["full_name"]
        booking["saved_phone"] = client["phone"]

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"✅ Да: {client['full_name']}, {client['phone']}",
                        callback_data="bk_use_saved",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "✏️ Указать другие данные",
                        callback_data="bk_new_contact",
                    )
                ],
                [InlineKeyboardButton("✖️ Отмена", callback_data="bk_cancel")],
            ]
        )
        await query.edit_message_text(
            "🗓 <b>Онлайн-запись · Шаг 5 из 5</b>\n\n"
            "Мы сохранили ваши контакты с прошлого визита.\n"
            "Использовать их для этой записи?",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
        return ASK_SAVED_PROFILE

    return await _ask_client_name(query, user)


async def _ask_client_name(query, user) -> int:
    """Запрашивает имя клиента (с быстрой кнопкой имени из профиля)."""
    profile_name = user.first_name if user and user.first_name else None
    buttons = []
    if profile_name:
        buttons.append(
            [
                InlineKeyboardButton(
                    f"Использовать имя «{profile_name}»",
                    callback_data="bk_name_profile",
                )
            ]
        )
    buttons.append([InlineKeyboardButton("✖️ Отмена", callback_data="bk_cancel")])

    await query.edit_message_text(
        "🗓 <b>Онлайн-запись · Шаг 5 из 5</b>\n\n"
        "Как к вам обращаться? Напишите ваше <b>имя</b> сообщением "
        "или нажмите кнопку ниже:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return ENTER_NAME


async def handle_saved_profile_choice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Обрабатывает выбор: использовать сохранённые контакты или ввести заново."""
    query = update.callback_query
    if not query or not query.data:
        return ASK_SAVED_PROFILE

    await query.answer()
    booking = context.user_data["booking"]

    if query.data == "bk_use_saved":
        booking["client_name"] = booking["saved_name"]
        booking["client_phone"] = booking["saved_phone"]
        return await _show_confirmation(query.message, booking, edit=True)

    return await _ask_client_name(query, update.effective_user)


async def enter_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Принимает имя клиента (кнопкой из профиля или текстом) и просит телефон."""
    booking = context.user_data.setdefault("booking", {})

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        user = update.effective_user
        booking["client_name"] = user.first_name if user and user.first_name else "Гость"
        target_message = query.message
    elif update.message and update.message.text:
        name = update.message.text.strip()
        if len(name) < 2 or len(name) > 50:
            await update.message.reply_text(
                "Пожалуйста, введите корректное имя (от 2 до 50 символов):"
            )
            return ENTER_NAME
        booking["client_name"] = name
        target_message = update.message
    else:
        return ENTER_NAME

    phone_keyboard = ReplyKeyboardMarkup(
        [
            [KeyboardButton("📱 Отправить мой номер телефона", request_contact=True)],
            [KeyboardButton("✖️ Отменить запись")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

    if target_message:
        await target_message.reply_text(
            f"Приятно познакомиться, <b>{html.escape(booking['client_name'])}</b>!\n\n"
            "Теперь укажите ваш <b>номер телефона</b> для связи "
            "(напишите вручную, например <code>+7 999 123-45-67</code>, "
            "или нажмите кнопку ниже):",
            parse_mode=ParseMode.HTML,
            reply_markup=phone_keyboard,
        )
    return ENTER_PHONE


async def enter_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Принимает номер телефона (контактом или текстом) и показывает итог."""
    if not update.message:
        return ENTER_PHONE

    if update.message.contact:
        phone = update.message.contact.phone_number
        if not phone.startswith("+"):
            phone = f"+{phone}"
    elif update.message.text:
        raw_text = update.message.text.strip()
        if raw_text == "✖️ Отменить запись":
            return await cancel_booking_flow(update, context)

        digits = re.sub(r"\D", "", raw_text)
        if len(digits) < 10 or len(digits) > 15:
            await update.message.reply_text(
                "Не похоже на номер телефона 😔\n"
                "Введите номер (например, <code>+7 999 123-45-67</code>) "
                "или нажмите кнопку «📱 Отправить мой номер телефона».",
                parse_mode=ParseMode.HTML,
            )
            return ENTER_PHONE
        phone = raw_text
    else:
        return ENTER_PHONE

    booking = context.user_data["booking"]
    booking["client_phone"] = phone

    await update.message.reply_text(
        "Отлично, контакты приняты!",
        reply_markup=get_main_menu_keyboard(),
    )

    return await _show_confirmation(update.message, booking, edit=False)


async def _show_confirmation(message, booking: dict, edit: bool) -> int:
    """Показывает итоговую карточку записи с кнопками подтверждения."""
    text = (
        "✨ <b>Проверьте данные вашей записи</b>\n\n"
        "<blockquote>"
        f"💅 <b>Услуга:</b> {html.escape(booking['service_name'])}\n"
        f"💰 <b>Стоимость:</b> <code>{html.escape(booking['price'])}</code>\n"
        f"📅 <b>Дата:</b> {_format_date_ru(booking['date'])}\n"
        f"🕒 <b>Время:</b> {booking['time']}\n"
        f"👤 <b>Имя:</b> {html.escape(booking['client_name'])}\n"
        f"📱 <b>Телефон:</b> <code>{html.escape(booking['client_phone'])}</code>"
        "</blockquote>\n"
        "Всё верно?"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Подтвердить запись", callback_data="bk_confirm")],
            [InlineKeyboardButton("✖️ Отменить", callback_data="bk_cancel")],
        ]
    )

    if edit and message:
        await message.edit_text(text=text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    elif message:
        await message.reply_text(text=text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

    return CONFIRM_BOOKING


async def confirm_booking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохраняет клиента и запись в базу данных SQLite и уведомляет администратора."""
    query = update.callback_query
    if not query or not update.effective_user:
        return ConversationHandler.END

    await query.answer()
    db: Database = context.bot_data["db"]
    user = update.effective_user
    booking = context.user_data.get("booking", {})

    if not booking.get("service_name"):
        await query.edit_message_text("Сессия записи устарела. Начните, пожалуйста, заново.")
        return ConversationHandler.END

    await db.update_client_contact(
        telegram_id=user.id,
        full_name=booking["client_name"],
        phone=booking["client_phone"],
    )

    try:
        appointment_id = await db.create_appointment(
            client_id=user.id,
            service_name=booking["service_name"],
            price=booking["price"],
            appointment_date=booking["date"],
            appointment_time=booking["time"],
        )
    except aiosqlite.IntegrityError:
        await query.edit_message_text(
            "😔 Ой! Пока вы заполняли данные, это время уже занял другой клиент.\n\n"
            "Нажмите «🗓 Записаться», чтобы выбрать другое свободное окно."
        )
        context.user_data.pop("booking", None)
        return ConversationHandler.END

    await query.edit_message_text(
        f"🎉 <b>Вы успешно записаны! (Запись №{appointment_id})</b>\n\n"
        "<blockquote>"
        f"💅 <b>Услуга:</b> {html.escape(booking['service_name'])}\n"
        f"📅 <b>Дата:</b> {_format_date_ru(booking['date'])}\n"
        f"🕒 <b>Время:</b> {booking['time']}\n"
        f"💰 <b>Стоимость:</b> <code>{html.escape(booking['price'])}</code>"
        "</blockquote>\n"
        "🔔 Мы напомним вам о визите за день до записи.\n"
        "Посмотреть или отменить визит можно в разделе <b>«📋 Моя запись»</b>.",
        parse_mode=ParseMode.HTML,
    )

    config: Config = context.bot_data["config"]
    if config.admin_id:
        username_str = f" (@{html.escape(user.username)})" if user.username else ""
        try:
            await context.bot.send_message(
                chat_id=config.admin_id,
                text=(
                    f"🔔 <b>Новая запись №{appointment_id}!</b>\n\n"
                    "<blockquote>"
                    f"💅 <b>Услуга:</b> {html.escape(booking['service_name'])}\n"
                    f"📅 <b>Дата:</b> {_format_date_ru(booking['date'])} в {booking['time']}\n"
                    f"👤 <b>Клиент:</b> {html.escape(booking['client_name'])}{username_str}\n"
                    f"📱 <b>Телефон:</b> <code>{html.escape(booking['client_phone'])}</code>"
                    "</blockquote>"
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception as notify_err:
            logger.warning("Не удалось отправить уведомление админу: %s", notify_err)

    context.user_data.pop("booking", None)
    return ConversationHandler.END


async def cancel_booking_flow(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Отмена процесса заполнения записи на любом этапе."""
    context.user_data.pop("booking", None)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ Оформление записи отменено.")
    elif update.message:
        await update.message.reply_text(
            "❌ Оформление записи отменено.",
            reply_markup=get_main_menu_keyboard(),
        )

    return ConversationHandler.END


async def exit_and_redirect(
    update: Update, context: ContextTypes.DEFAULT_TYPE, handler_func
) -> int:
    """Если клиент нажал другую кнопку меню прямо посреди записи — выходим из диалога."""
    context.user_data.pop("booking", None)
    await handler_func(update, context)
    return ConversationHandler.END


async def fallback_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await exit_and_redirect(update, context, start_command)


async def fallback_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await exit_and_redirect(update, context, help_command)


async def fallback_services(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await exit_and_redirect(update, context, show_services)


async def fallback_my_booking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await exit_and_redirect(update, context, show_my_booking)


async def fallback_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await exit_and_redirect(update, context, show_contacts)


def build_booking_conversation_handler() -> ConversationHandler:
    """Собирает и возвращает готовый ConversationHandler для регистрации в bot.py."""
    return ConversationHandler(
        entry_points=[
            MessageHandler(filters.Text([BTN_BOOK]), start_booking),
            CallbackQueryHandler(start_booking, pattern="^go_to_booking$"),
        ],
        states={
            SELECT_CATEGORY: [
                CallbackQueryHandler(select_category, pattern="^bk_(cat_|back_cats)"),
            ],
            SELECT_SERVICE: [
                CallbackQueryHandler(
                    select_service, pattern="^bk_(srv_|back_cats|back_srvs)"
                ),
            ],
            SELECT_DATE: [
                CallbackQueryHandler(
                    select_date, pattern="^bk_(date_|back_srvs|back_dates)"
                ),
            ],
            SELECT_TIME: [
                CallbackQueryHandler(select_time, pattern="^bk_(time_|back_dates)"),
            ],
            ASK_SAVED_PROFILE: [
                CallbackQueryHandler(
                    handle_saved_profile_choice, pattern="^bk_(use_saved|new_contact)$"
                ),
            ],
            ENTER_NAME: [
                CallbackQueryHandler(enter_name, pattern="^bk_name_profile$"),
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND
                    & ~filters.Text([BTN_SERVICES, BTN_BOOK, BTN_MY_BOOKING, BTN_CONTACT]),
                    enter_name,
                ),
            ],
            ENTER_PHONE: [
                MessageHandler(filters.CONTACT, enter_phone),
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND
                    & ~filters.Text([BTN_SERVICES, BTN_BOOK, BTN_MY_BOOKING, BTN_CONTACT]),
                    enter_phone,
                ),
            ],
            CONFIRM_BOOKING: [
                CallbackQueryHandler(confirm_booking, pattern="^bk_confirm$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_booking_flow, pattern="^bk_cancel$"),
            CommandHandler("start", fallback_start),
            CommandHandler("help", fallback_help),
            CommandHandler("cancel", cancel_booking_flow),
            MessageHandler(filters.Text([BTN_SERVICES]), fallback_services),
            MessageHandler(filters.Text([BTN_MY_BOOKING]), fallback_my_booking),
            MessageHandler(filters.Text([BTN_CONTACT]), fallback_contacts),
        ],
        allow_reentry=True,
    )


async def handle_cancel_appointment_request(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Спрашивает подтверждение перед отменой записи."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()
    appointment_id = int(query.data.replace("cancel_ask_", ""))

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Да, отменить", callback_data=f"cancel_yes_{appointment_id}"
                ),
                InlineKeyboardButton("← Оставить", callback_data="cancel_no"),
            ]
        ]
    )

    await query.edit_message_text(
        f"❓ Вы уверены, что хотите отменить запись <b>№{appointment_id}</b>?",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def handle_cancel_appointment_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Подтверждает отмену записи в базе данных и уведомляет администратора."""
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    if query.data == "cancel_no":
        await query.edit_message_text("👍 Запись сохранена! Ждём вас в студии.")
        return

    appointment_id = int(query.data.replace("cancel_yes_", ""))
    db: Database = context.bot_data["db"]

    app = await db.get_appointment_by_id(appointment_id)
    cancelled = await db.cancel_appointment(
        appointment_id=appointment_id,
        client_id=update.effective_user.id,
    )

    if cancelled:
        await query.edit_message_text(
            f"✅ Запись <b>№{appointment_id}</b> успешно отменена.\n\n"
            "Будем рады видеть вас в другой день! Вы всегда можете выбрать "
            "новое время через кнопку <b>«🗓 Записаться»</b>.",
            parse_mode=ParseMode.HTML,
        )

        config: Config = context.bot_data["config"]
        if config.admin_id and app:
            try:
                await context.bot.send_message(
                    chat_id=config.admin_id,
                    text=(
                        f"⚠️ <b>Клиент отменил запись №{appointment_id}</b>\n\n"
                        "<blockquote>"
                        f"💅 {html.escape(app['service_name'])}\n"
                        f"📅 {_format_date_ru(app['appointment_date'])} в {app['appointment_time']}\n"
                        f"👤 {html.escape(app.get('full_name') or 'Клиент')} "
                        f"(<code>{html.escape(app.get('phone') or 'без телефона')}</code>)"
                        "</blockquote>"
                    ),
                    parse_mode=ParseMode.HTML,
                )
            except Exception as notify_err:
                logger.warning("Не удалось уведомить админа об отмене: %s", notify_err)
    else:
        await query.edit_message_text(
            "Эта запись уже была отменена ранее или не найдена."
        )