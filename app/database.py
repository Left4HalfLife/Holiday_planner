import sqlite3
from pathlib import Path

from flask import current_app, g


SCHEMA = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS holidays (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    destination TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL CHECK(end_date >= start_date),
    accommodation_name TEXT NOT NULL DEFAULT '',
    accommodation_address TEXT NOT NULL DEFAULT '',
    booking_references TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    budget_cents INTEGER NOT NULL DEFAULT 0 CHECK(budget_cents >= 0),
    currency TEXT NOT NULL DEFAULT 'USD',
    laundry_available INTEGER NOT NULL DEFAULT 0,
    weather TEXT NOT NULL DEFAULT 'Temperate',
    air_quality TEXT NOT NULL DEFAULT 'Low',
    dietary_requirements TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE IF NOT EXISTS packing_items (
    id INTEGER PRIMARY KEY,
    holiday_id INTEGER NOT NULL REFERENCES holidays(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    category TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity > 0),
    packed INTEGER NOT NULL DEFAULT 0,
    UNIQUE(holiday_id, category, name_key)
);
CREATE TABLE IF NOT EXISTS flights (
    id INTEGER PRIMARY KEY,
    holiday_id INTEGER NOT NULL REFERENCES holidays(id) ON DELETE CASCADE,
    airline TEXT NOT NULL DEFAULT '',
    flight_number TEXT NOT NULL,
    departure_airport TEXT NOT NULL DEFAULT '',
    departure_time TEXT NOT NULL DEFAULT '',
    departure_timezone TEXT NOT NULL DEFAULT '',
    arrival_airport TEXT NOT NULL DEFAULT '',
    arrival_time TEXT NOT NULL DEFAULT '',
    arrival_timezone TEXT NOT NULL DEFAULT '',
    terminal TEXT NOT NULL DEFAULT '',
    gate TEXT NOT NULL DEFAULT '',
    booking_code TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY,
    holiday_id INTEGER NOT NULL REFERENCES holidays(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
    date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS packing_templates (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    items_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY,
    holiday_id INTEGER NOT NULL REFERENCES holidays(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user','assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_flights_holiday ON flights(holiday_id);
CREATE INDEX IF NOT EXISTS idx_expenses_holiday ON expenses(holiday_id);
CREATE INDEX IF NOT EXISTS idx_chat_holiday ON chat_messages(holiday_id, id);
PRAGMA user_version = 1;
COMMIT;
"""


def connect(path):
    connection = sqlite3.connect(path, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    return connection


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_app(app):
    path = Path(app.config["DATABASE"])
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(path)
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            raise RuntimeError("This database was created by a newer application version.")
        if version < 1:
            connection.executescript(SCHEMA)
    finally:
        connection.close()
    app.teardown_appcontext(close_db)
