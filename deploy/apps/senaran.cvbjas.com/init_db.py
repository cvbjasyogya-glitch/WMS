from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from werkzeug.security import generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
DATABASE = Path(os.environ.get("SENARAN_DATABASE") or os.environ.get("DATABASE_PATH") or BASE_DIR / "antrian.db").resolve()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    must_change_password INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS queue_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_number TEXT NOT NULL,
    queue_date DATE NOT NULL,
    customer_name TEXT NOT NULL,
    phone TEXT,
    branch TEXT NOT NULL,
    service_type TEXT NOT NULL,
    racket_type TEXT,
    racket_brand TEXT,
    string_type TEXT,
    tension_lbs TEXT,
    racket_count INTEGER DEFAULT 1,
    is_express INTEGER DEFAULT 0,
    staff_name TEXT,
    stringer_name TEXT,
    note TEXT,
    status TEXT DEFAULT 'MENUNGGU',
    payment_status TEXT DEFAULT 'BELUM BAYAR',
    estimated_finish DATETIME,
    called_at DATETIME,
    started_at DATETIME,
    finished_at DATETIME,
    picked_up_at DATETIME,
    canceled_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS queue_ticket_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL,
    item_number INTEGER NOT NULL,
    racket_type TEXT,
    racket_brand TEXT,
    string_type TEXT,
    tension_lbs TEXT,
    knot_type TEXT,
    variation TEXT,
    grommet TEXT DEFAULT 'Tidak',
    racket_note TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(ticket_id) REFERENCES queue_tickets(id)
);

CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_name TEXT NOT NULL,
    price INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS staff (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    staff_name TEXT UNIQUE NOT NULL,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    setting_key TEXT UNIQUE NOT NULL,
    setting_value TEXT
);

CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT,
    ip_address TEXT,
    success INTEGER DEFAULT 0,
    attempted_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS schedule_day_status (
    day_date DATE PRIMARY KEY,
    is_off INTEGER DEFAULT 1,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


DEFAULT_SERVICES = [
    ("Stringing Badminton", 0),
    ("Stringing Tenis", 0),
]


DEFAULT_SETTINGS = [
    ("app_name", "Sistem Antrian Stringing"),
    ("store_name", "Mega Sports"),
    ("active_branches", "Mega Sports"),
    ("queue_number_format", "MGA-001, reset per hari"),
    ("database", "SQLite"),
]

DEFAULT_STAFF = [
    "Bu ika",
    "Lifia",
    "Caca",
    "Afif",
    "Ziza",
    "Edi",
    "Ahmad",
    "Lainnya",
]

DEFAULT_ADMIN = {
    "name": "Administrator",
    "username": "megasports",
    "password": os.environ.get("DEFAULT_ADMIN_PASSWORD", "ChangeMeLocal123"),
    "role": "admin",
}


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def migrate_existing_schema(conn: sqlite3.Connection) -> None:
    if not column_exists(conn, "users", "must_change_password"):
        conn.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER DEFAULT 0")

    if not column_exists(conn, "queue_tickets", "racket_count"):
        conn.execute("ALTER TABLE queue_tickets ADD COLUMN racket_count INTEGER DEFAULT 1")
    if not column_exists(conn, "queue_tickets", "is_express"):
        conn.execute("ALTER TABLE queue_tickets ADD COLUMN is_express INTEGER DEFAULT 0")
    if not column_exists(conn, "queue_tickets", "staff_name"):
        conn.execute("ALTER TABLE queue_tickets ADD COLUMN staff_name TEXT")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS queue_ticket_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            item_number INTEGER NOT NULL,
            racket_type TEXT,
            racket_brand TEXT,
            string_type TEXT,
            tension_lbs TEXT,
            knot_type TEXT,
            variation TEXT,
            grommet TEXT DEFAULT 'Tidak',
            racket_note TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(ticket_id) REFERENCES queue_tickets(id)
        )
        """
    )
    if not column_exists(conn, "queue_ticket_items", "grommet"):
        conn.execute("ALTER TABLE queue_ticket_items ADD COLUMN grommet TEXT DEFAULT 'Tidak'")
    if not column_exists(conn, "queue_ticket_items", "racket_note"):
        conn.execute("ALTER TABLE queue_ticket_items ADD COLUMN racket_note TEXT")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            ip_address TEXT,
            success INTEGER DEFAULT 0,
            attempted_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_name TEXT UNIQUE NOT NULL,
            is_active INTEGER DEFAULT 1
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schedule_day_status (
            day_date DATE PRIMARY KEY,
            is_off INTEGER DEFAULT 1,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        INSERT INTO queue_ticket_items (
            ticket_id, item_number, racket_type, racket_brand, string_type, tension_lbs
        )
        SELECT id, 1, racket_type, racket_brand, string_type, tension_lbs
        FROM queue_tickets AS qt
        WHERE NOT EXISTS (
            SELECT 1 FROM queue_ticket_items AS qi WHERE qi.ticket_id = qt.id
        )
        """
    )
    conn.execute(
        """
        UPDATE queue_tickets
        SET racket_count = COALESCE(NULLIF(racket_count, 0), 1),
            is_express = COALESCE(is_express, 0),
            staff_name = COALESCE(staff_name, '')
        """
    )
    conn.execute(
        """
        UPDATE queue_ticket_items
        SET grommet = COALESCE(NULLIF(grommet, ''), 'Tidak'),
            racket_note = COALESCE(racket_note, '')
        """
    )


def init_db() -> None:
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA)
        migrate_existing_schema(conn)

        admin = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (DEFAULT_ADMIN["username"],),
        ).fetchone()
        if admin is None:
            conn.execute(
                """
                INSERT INTO users (name, username, password_hash, role, must_change_password)
                VALUES (?, ?, ?, ?, 1)
                """,
                (
                    DEFAULT_ADMIN["name"],
                    DEFAULT_ADMIN["username"],
                    generate_password_hash(DEFAULT_ADMIN["password"]),
                    DEFAULT_ADMIN["role"],
                ),
            )

        conn.execute("UPDATE services SET is_active = 0")
        for service_name, price in DEFAULT_SERVICES:
            existing_service = conn.execute(
                "SELECT id FROM services WHERE service_name = ?",
                (service_name,),
            ).fetchone()
            if existing_service:
                conn.execute(
                    "UPDATE services SET price = ?, is_active = 1 WHERE id = ?",
                    (price, existing_service[0]),
                )
            else:
                conn.execute(
                    "INSERT INTO services (service_name, price, is_active) VALUES (?, ?, 1)",
                    (service_name, price),
                )

        conn.execute("UPDATE staff SET is_active = 0")
        for staff_name in DEFAULT_STAFF:
            existing_staff = conn.execute(
                "SELECT id FROM staff WHERE staff_name = ?",
                (staff_name,),
            ).fetchone()
            if existing_staff:
                conn.execute(
                    "UPDATE staff SET is_active = 1 WHERE id = ?",
                    (existing_staff[0],),
                )
            else:
                conn.execute(
                    "INSERT INTO staff (staff_name, is_active) VALUES (?, 1)",
                    (staff_name,),
                )

        conn.executemany(
            """
            INSERT INTO settings (setting_key, setting_value)
            VALUES (?, ?)
            ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value
            """,
            DEFAULT_SETTINGS,
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database siap: {DATABASE}")
