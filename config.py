"""
Конфигурация бота: загрузка секретов из .env и основные данные салона.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_id: Optional[int]
    db_path: str = "salon.db"
    salon_name: str = "LUMIÈRE Beauty Studio"
    salon_tagline: str = "Эстетика, уход и безупречный сервис"
    salon_address: str = "ул. Цветочная, д. 15, 2 этаж"
    salon_phone: str = "+7 (999) 123-45-67"
    salon_hours: str = "Ежедневно с 10:00 до 21:00"
    map_url: str = "https://yandex.ru/maps"
    manager_url: str = "https://t.me/telegram"  # Замени на свой @username
    banner_path: Path = Path("banner.jpg")


def load_config() -> Config:
    """Загружает конфигурацию и проверяет наличие обязательного токена."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or token == "your_telegram_bot_token_here":
        raise ValueError("TELEGRAM_BOT_TOKEN не задан! Проверь файл .env.")

    admin_raw = os.getenv("ADMIN_ID", "").strip()
    admin_id: Optional[int] = None
    if admin_raw:
        if not admin_raw.isdigit():
            raise ValueError("ADMIN_ID в .env должен состоять только из цифр.")
        admin_id = int(admin_raw)

    return Config(bot_token=token, admin_id=admin_id)