"""
Работа с базой данных SQLite (асинхронно через aiosqlite).
Хранит профили клиентов и записи на процедуры.
"""

from datetime import datetime
from typing import Optional

import aiosqlite


class Database:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def init_db(self) -> None:
        """Создаёт таблицы и индексы, если они ещё не существуют."""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON;")

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS clients (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT NOT NULL,
                    phone TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS appointments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id INTEGER NOT NULL,
                    service_name TEXT NOT NULL,
                    price TEXT NOT NULL,
                    appointment_date TEXT NOT NULL,
                    appointment_time TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    reminded INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (client_id) REFERENCES clients (telegram_id)
                );
                """
            )

            await conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_active_slot
                ON appointments (appointment_date, appointment_time)
                WHERE status = 'active';
                """
            )

            await conn.commit()

    async def register_or_touch_client(
        self,
        telegram_id: int,
        username: Optional[str],
        full_name: str,
    ) -> None:
        """Сохраняет нового клиента при первом /start или обновляет @username."""
        now = datetime.now().isoformat(timespec="seconds")
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO clients (telegram_id, username, full_name, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    username = excluded.username;
                """,
                (telegram_id, username, full_name, now),
            )
            await conn.commit()

    async def update_client_contact(
        self,
        telegram_id: int,
        full_name: str,
        phone: str,
    ) -> None:
        """Обновляет имя и номер телефона клиента после оформления записи."""
        now = datetime.now().isoformat(timespec="seconds")
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO clients (telegram_id, full_name, phone, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    full_name = excluded.full_name,
                    phone = excluded.phone;
                """,
                (telegram_id, full_name, phone, now),
            )
            await conn.commit()

    async def get_client(self, telegram_id: int) -> Optional[dict]:
        """Возвращает данные клиента по его telegram_id или None."""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT * FROM clients WHERE telegram_id = ?;",
                (telegram_id,),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_booked_times(self, appointment_date: str) -> list[str]:
        """Возвращает список уже занятого времени на указанную дату (YYYY-MM-DD)."""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT appointment_time
                FROM appointments
                WHERE appointment_date = ? AND status = 'active'
                ORDER BY appointment_time;
                """,
                (appointment_date,),
            )
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def create_appointment(
        self,
        client_id: int,
        service_name: str,
        price: str,
        appointment_date: str,
        appointment_time: str,
    ) -> int:
        """Создаёт новую запись и возвращает её ID."""
        now = datetime.now().isoformat(timespec="seconds")
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON;")
            cursor = await conn.execute(
                """
                INSERT INTO appointments (
                    client_id, service_name, price,
                    appointment_date, appointment_time,
                    status, reminded, created_at
                )
                VALUES (?, ?, ?, ?, ?, 'active', 0, ?);
                """,
                (client_id, service_name, price, appointment_date, appointment_time, now),
            )
            await conn.commit()
            return cursor.lastrowid

    async def get_client_active_appointments(self, client_id: int) -> list[dict]:
        """Возвращает активные предстоящие записи клиента."""
        today = datetime.now().strftime("%Y-%m-%d")
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                """
                SELECT *
                FROM appointments
                WHERE client_id = ?
                  AND status = 'active'
                  AND appointment_date >= ?
                ORDER BY appointment_date, appointment_time;
                """,
                (client_id, today),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def cancel_appointment(
        self,
        appointment_id: int,
        client_id: Optional[int] = None,
    ) -> bool:
        """Отменяет запись (переводит status в 'cancelled')."""
        async with aiosqlite.connect(self.db_path) as conn:
            if client_id is not None:
                cursor = await conn.execute(
                    """
                    UPDATE appointments
                    SET status = 'cancelled'
                    WHERE id = ? AND client_id = ? AND status = 'active';
                    """,
                    (appointment_id, client_id),
                )
            else:
                cursor = await conn.execute(
                    """
                    UPDATE appointments
                    SET status = 'cancelled'
                    WHERE id = ? AND status = 'active';
                    """,
                    (appointment_id,),
                )
            await conn.commit()
            return cursor.rowcount > 0

    async def get_appointments_by_date(self, appointment_date: str) -> list[dict]:
        """Для админа: все активные записи на конкретную дату."""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                """
                SELECT a.*, c.full_name, c.phone, c.username
                FROM appointments a
                JOIN clients c ON a.client_id = c.telegram_id
                WHERE a.appointment_date = ? AND a.status = 'active'
                ORDER BY a.appointment_time;
                """,
                (appointment_date,),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_upcoming_appointments(self) -> list[dict]:
        """Для админа: все ближайшие активные записи."""
        today = datetime.now().strftime("%Y-%m-%d")
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                """
                SELECT a.*, c.full_name, c.phone, c.username
                FROM appointments a
                JOIN clients c ON a.client_id = c.telegram_id
                WHERE a.appointment_date >= ? AND a.status = 'active'
                ORDER BY a.appointment_date, a.appointment_time;
                """,
                (today,),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_unreminded_upcoming_appointments(self) -> list[dict]:
        """Возвращает активные предстоящие записи, по которым ещё не отправлено напоминание."""
        today = datetime.now().strftime("%Y-%m-%d")
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                """
                SELECT a.*, c.full_name
                FROM appointments a
                JOIN clients c ON a.client_id = c.telegram_id
                WHERE a.appointment_date >= ?
                  AND a.status = 'active'
                  AND a.reminded = 0;
                """,
                (today,),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def mark_reminded(self, appointment_id: int) -> None:
        """Отмечает, что напоминание по записи уже отправлено."""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                "UPDATE appointments SET reminded = 1 WHERE id = ?;",
                (appointment_id,),
            )
            await conn.commit()

    async def get_appointment_by_id(self, appointment_id: int) -> Optional[dict]:
        """Возвращает полную информацию о записи по её ID вместе с контактами клиента."""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                """
                SELECT a.*, c.full_name, c.phone, c.username
                FROM appointments a
                JOIN clients c ON a.client_id = c.telegram_id
                WHERE a.id = ?;
                """,
                (appointment_id,),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_all_clients(self) -> list[dict]:
        """Для админа: список всех клиентов и количество их активных записей."""
        today = datetime.now().strftime("%Y-%m-%d")
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                """
                SELECT
                    c.*,
                    COUNT(CASE WHEN a.status = 'active' AND a.appointment_date >= ? THEN 1 END) AS active_count,
                    COUNT(a.id) AS total_count
                FROM clients c
                LEFT JOIN appointments a ON c.telegram_id = a.client_id
                GROUP BY c.telegram_id
                ORDER BY c.created_at DESC;
                """,
                (today,),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_admin_stats(self) -> dict:
        """Краткая сводка для главного экрана панели администратора."""
        today = datetime.now().strftime("%Y-%m-%d")
        async with aiosqlite.connect(self.db_path) as conn:
            cur_clients = await conn.execute("SELECT COUNT(*) FROM clients;")
            clients_count = (await cur_clients.fetchone())[0]

            cur_today = await conn.execute(
                "SELECT COUNT(*) FROM appointments WHERE appointment_date = ? AND status = 'active';",
                (today,),
            )
            today_count = (await cur_today.fetchone())[0]

            cur_upcoming = await conn.execute(
                "SELECT COUNT(*) FROM appointments WHERE appointment_date >= ? AND status = 'active';",
                (today,),
            )
            upcoming_count = (await cur_upcoming.fetchone())[0]

            return {
                "clients_count": clients_count,
                "today_count": today_count,
                "upcoming_count": upcoming_count,
            }