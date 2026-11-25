"""
Обработчики команд (/start, /help), главного меню и интерактивного прайса.
"""

from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import Config
from database import Database
from keyboards import (
    get_contacts_inline_keyboard,
    get_main_menu_keyboard,
    get_service_categories_keyboard,
    get_service_detail_keyboard,
)

# Тексты прайс-листа по категориям
SERVICE_CATEGORIES_TEXT = {
    "cat_nails": (
        "💅 <b>Ногтевой сервис</b>\n\n"
        "<blockquote>"
        "• <b>Маникюр + гель-лак</b> — <code>2 200 ₽</code>\n"
        "  <i>Снятие, комбинированный маникюр, выравнивание и покрытие</i> · 90 мин\n\n"
        "• <b>Смарт-педикюр</b> — <code>2 800 ₽</code>\n"
        "  <i>Обработка стоп дисками, уход и покрытие гель-лак</i> · 90 мин\n\n"
        "• <b>Укрепление / Наращивание</b> — <code>от 3 200 ₽</code>\n"
        "  <i>Моделирование длины и архитектуры ногтей</i> · 120 мин"
        "</blockquote>\n"
        "✨ <i>Используем премиальные материалы и 3-этапную стерилизацию.</i>"
    ),
    "cat_hair": (
        "💇‍♀️ <b>Волосы и укладки</b>\n\n"
        "<blockquote>"
        "• <b>Женская стрижка + укладка</b> — <code>2 500 ₽</code>\n"
        "  <i>Мытьё, уход по типу волос, стрижка и укладка на брашинг</i> · 60 мин\n\n"
        "• <b>Сложное окрашивание (AirTouch / Шатуш)</b> — <code>от 6 500 ₽</code>\n"
        "  <i>Плавный переход цвета с защитой структуры волос</i> · 180 мин\n\n"
        "• <b>Спа-уход «Абсолютное счастье»</b> — <code>3 400 ₽</code>\n"
        "  <i>Глубокое восстановление и блеск</i> · 60 мин"
        "</blockquote>\n"
        "✨ <i>Точная стоимость окрашивания зависит от густоты и длины волос.</i>"
    ),
    "cat_brows": (
        "✨ <b>Брови и ресницы</b>\n\n"
        "<blockquote>"
        "• <b>Архитектура и окрашивание бровей</b> — <code>1 400 ₽</code>\n"
        "  <i>Подбор формы, коррекция воском/пинцетом, краска или хна</i> · 45 мин\n\n"
        "• <b>Долговременная укладка бровей</b> — <code>2 100 ₽</code>\n"
        "  <i>Фиксация, окрашивание и уход</i> · 60 мин\n\n"
        "• <b>Ламинирование ресниц</b> — <code>2 400 ₽</code>\n"
        "  <i>Красивый естественный изгиб и питание составами</i> · 60 мин"
        "</blockquote>\n"
        "✨ <i>Подчеркнём естественную красоту без эффекта перегруженности.</i>"
    ),
}

SERVICES_OVERVIEW_TEXT = (
    "💅 <b>Прайс-лист и услуги</b>\n\n"
    "<blockquote>"
    "Мы работаем на сертифицированной косметике премиум-класса и "
    "подбираем уход индивидуально под каждого гостя."
    "</blockquote>\n"
    "👇 <i>Выберите направление, чтобы посмотреть процедуры и цены:</i>"
)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Приветствие клиента, сохранение его профиля в БД и отображение меню."""
    if not update.message:
        return

    config: Config = context.bot_data["config"]
    db: Database = context.bot_data["db"]
    user = update.effective_user
    user_name = user.first_name if user and user.first_name else "гость"

    if user:
        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Гость"
        await db.register_or_touch_client(
            telegram_id=user.id,
            username=user.username,
            full_name=full_name,
        )

    text = (
        f"✨ <b>{config.salon_name}</b>\n"
        f"<i>{config.salon_tagline}</i>\n\n"
        f"Здравствуйте, <b>{user_name}</b>! Рады видеть вас.\n\n"
        "<blockquote>"
        "• 💅 Изучайте услуги и актуальные цены\n"
        "• 🗓 Записывайтесь онлайн за 1 минуту\n"
        "• 🔔 Получайте напоминание за день до визита"
        "</blockquote>\n"
        "👇 <i>Воспользуйтесь меню внизу экрана:</i>"
    )

    if config.banner_path.exists():
        with config.banner_path.open("rb") as photo:
            await update.message.reply_photo(
                photo=photo,
                caption=text,
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_menu_keyboard(),
            )
    else:
        await update.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_menu_keyboard(),
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Справка по возможностям бота."""
    if not update.message:
        return

    config: Config = context.bot_data["config"]
    text = (
        f"ℹ️ <b>Навигация — {config.salon_name}</b>\n\n"
        "<blockquote>"
        "<b>💅 Наши услуги</b> — направления, описания и цены\n"
        "<b>🗓 Записаться</b> — выбор услуги, даты и времени\n"
        "<b>📋 Моя запись</b> — просмотр и отмена визита\n"
        "<b>📞 Связаться</b> — адрес, график работы и чат"
        "</blockquote>\n"
        "Если кнопки внизу пропали, просто нажмите /start."
    )

    await update.message.reply_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_menu_keyboard(),
    )


async def show_services(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает категории услуг."""
    if not update.message:
        return

    await update.message.reply_text(
        text=SERVICES_OVERVIEW_TEXT,
        parse_mode=ParseMode.HTML,
        reply_markup=get_service_categories_keyboard(),
    )


async def handle_service_category(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Плавно переключает категории услуг внутри одного сообщения."""
    query = update.callback_query
    if not query:
        return

    await query.answer()
    data = query.data

    if data == "cat_back":
        await query.edit_message_text(
            text=SERVICES_OVERVIEW_TEXT,
            parse_mode=ParseMode.HTML,
            reply_markup=get_service_categories_keyboard(),
        )
        return

    category_text = SERVICE_CATEGORIES_TEXT.get(data)
    if category_text:
        await query.edit_message_text(
            text=category_text,
            parse_mode=ParseMode.HTML,
            reply_markup=get_service_detail_keyboard(),
        )


async def show_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Красивая карточка контактов с копированием телефона/адреса в один тап."""
    if not update.message:
        return

    config: Config = context.bot_data["config"]
    text = (
        f"📞 <b>Контакты · {config.salon_name}</b>\n\n"
        "<blockquote>"
        f"📍 <b>Адрес:</b> <code>{config.salon_address}</code>\n"
        f"🕒 <b>График:</b> {config.salon_hours}\n"
        f"📱 <b>Телефон:</b> <code>{config.salon_phone}</code>"
        "</blockquote>\n"
        "💡 <i>Нажмите на адрес или номер телефона, чтобы скопировать.</i>"
    )

    await update.message.reply_text(
        text=text,
        parse_mode=ParseMode.HTML,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
        reply_markup=get_contacts_inline_keyboard(
            map_url=config.map_url,
            manager_url=config.manager_url,
        ),
    )


async def show_my_booking(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Показывает активные записи клиента и кнопки для их отмены."""
    if not update.message or not update.effective_user:
        return

    db: Database = context.bot_data["db"]
    appointments = await db.get_client_active_appointments(update.effective_user.id)

    if not appointments:
        await update.message.reply_text(
            "📋 <b>Мои записи</b>\n\n"
            "<blockquote>У вас пока нет активных записей.</blockquote>\n"
            "👇 Нажмите кнопку ниже, чтобы выбрать удобное время.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🗓 Записаться онлайн", callback_data="go_to_booking")]]
            ),
        )
        return

    lines = ["📋 <b>Ваши активные записи</b>\n"]
    cancel_buttons = []

    for app in appointments:
        formatted_date = datetime.strptime(app["appointment_date"], "%Y-%m-%d").strftime(
            "%d.%m.%Y"
        )
        lines.append(
            "<blockquote>"
            f"📌 <b>Запись №{app['id']}: {app['service_name']}</b>\n"
            f"💰 Стоимость: <code>{app['price']}</code>\n"
            f"📅 Дата: <b>{formatted_date}</b>\n"
            f"🕒 Время: <b>{app['appointment_time']}</b>"
            "</blockquote>"
        )
        cancel_buttons.append(
            [
                InlineKeyboardButton(
                    f"❌ Отменить запись №{app['id']} ({formatted_date} в {app['appointment_time']})",
                    callback_data=f"cancel_ask_{app['id']}",
                )
            ]
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(cancel_buttons),
    )


async def unknown_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Мягкая подсказка при произвольном вводе текста."""
    if not update.message:
        return

    await update.message.reply_text(
        "👇 Пожалуйста, выберите нужный раздел на клавиатуре ниже.",
        reply_markup=get_main_menu_keyboard(),
    )