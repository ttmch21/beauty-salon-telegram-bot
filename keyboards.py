"""
Клавиатуры бота: главное меню и интерактивные inline-кнопки.
"""

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

BTN_SERVICES = "💅 Наши услуги"
BTN_BOOK = "🗓 Записаться"
BTN_MY_BOOKING = "📋 Моя запись"
BTN_CONTACT = "📞 Связаться"


def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Главное меню бота (закреплённые кнопки внизу экрана)."""
    keyboard = [
        [KeyboardButton(BTN_SERVICES), KeyboardButton(BTN_BOOK)],
        [KeyboardButton(BTN_MY_BOOKING), KeyboardButton(BTN_CONTACT)],
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Выберите раздел меню...",
    )


def get_service_categories_keyboard() -> InlineKeyboardMarkup:
    """Категории прайс-листа под сообщением."""
    keyboard = [
        [
            InlineKeyboardButton("💅 Ногтевой сервис", callback_data="cat_nails"),
            InlineKeyboardButton("💇‍♀️ Волосы", callback_data="cat_hair"),
        ],
        [
            InlineKeyboardButton("✨ Брови и ресницы", callback_data="cat_brows"),
        ],
        [
            InlineKeyboardButton("🗓 Записаться онлайн", callback_data="go_to_booking"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_service_detail_keyboard() -> InlineKeyboardMarkup:
    """Кнопки внутри выбранной категории услуг."""
    keyboard = [
        [InlineKeyboardButton("🗓 Записаться на процедуру", callback_data="go_to_booking")],
        [InlineKeyboardButton("← Все категории", callback_data="cat_back")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_contacts_inline_keyboard(map_url: str, manager_url: str) -> InlineKeyboardMarkup:
    """Две кнопки-ссылки в ряд под разделом контактов."""
    keyboard = [
        [
            InlineKeyboardButton("📍 На карте", url=map_url),
            InlineKeyboardButton("💬 Написать нам", url=manager_url),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)