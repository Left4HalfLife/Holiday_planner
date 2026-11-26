import json
import sqlite3
from datetime import date

from flask import abort

from .database import get_db
from .validation import ValidationError, validate


TABLES = {"holiday": "holidays", "packing": "packing_items", "flight": "flights", "expense": "expenses"}


def serialize(kind, row):
    data = dict(row)
    if kind == "holiday":
        data["budget"] = data.pop("budget_cents") / 100
        data["laundry_available"] = bool(data["laundry_available"])
    elif kind == "expense":
        data["amount"] = data.pop("amount_cents") / 100
    elif kind == "packing":
        data.pop("name_key", None)
        data["packed"] = bool(data["packed"])
    return data


def get_holiday(holiday_id):
    row = get_db().execute("SELECT * FROM holidays WHERE id = ?", (holiday_id,)).fetchone()
    if row is None:
        abort(404, description="Holiday not found.")
    return serialize("holiday", row)


def get_child(kind, holiday_id, item_id):
    table = TABLES[kind]
    row = get_db().execute(
        f"SELECT * FROM {table} WHERE holiday_id = ? AND id = ?", (holiday_id, item_id)
    ).fetchone()
    if row is None:
        abort(404, description="Item not found in this holiday.")
    return serialize(kind, row)


def insert(kind, data, holiday_id=None):
    table = TABLES[kind]
    values = dict(data)
    if holiday_id is not None:
        values["holiday_id"] = holiday_id
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    try:
        cursor = get_db().execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(values.values())
        )
    except sqlite3.IntegrityError as error:
        if kind != "packing" or error.sqlite_errorname != "SQLITE_CONSTRAINT_UNIQUE":
            raise
        raise ValidationError("That packing item already exists in this category.") from None
    return cursor.lastrowid


def update(kind, item_id, data, holiday_id=None):
    table = TABLES[kind]
    assignments = ", ".join(f"{key} = ?" for key in data)
    condition = "id = ?" if holiday_id is None else "id = ? AND holiday_id = ?"
    args = (*data.values(), item_id) if holiday_id is None else (*data.values(), item_id, holiday_id)
    try:
        get_db().execute(f"UPDATE {table} SET {assignments} WHERE {condition}", args)
    except sqlite3.IntegrityError as error:
        if kind != "packing" or error.sqlite_errorname != "SQLITE_CONSTRAINT_UNIQUE":
            raise
        raise ValidationError("That packing item already exists in this category.") from None


def holiday_detail(holiday_id):
    holiday = get_holiday(holiday_id)
    db = get_db()
    for kind, key, order in (
        ("packing", "packing_items", "category, id"),
        ("flight", "flights", "departure_time, id"),
        ("expense", "expenses", "date DESC, id DESC"),
    ):
        rows = db.execute(
            f"SELECT * FROM {TABLES[kind]} WHERE holiday_id = ? ORDER BY {order}", (holiday_id,)
        ).fetchall()
        holiday[key] = [serialize(kind, row) for row in rows]
    spent_cents = db.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) FROM expenses WHERE holiday_id = ?", (holiday_id,)
    ).fetchone()[0]
    holiday["spent"] = spent_cents / 100
    holiday["remaining"] = (round(holiday["budget"] * 100) - spent_cents) / 100
    holiday["packed_count"] = sum(item["packed"] for item in holiday["packing_items"])
    holiday["item_count"] = len(holiday["packing_items"])
    holiday["duration"] = (date.fromisoformat(holiday["end_date"]) - date.fromisoformat(holiday["start_date"])).days + 1
    return holiday


def add_packing_items(holiday_id, items):
    added = 0
    for item in items:
        data = validate("packing", item)
        exists = get_db().execute(
            "SELECT id FROM packing_items WHERE holiday_id = ? AND category = ? AND name_key = ?",
            (holiday_id, data["category"], data["name_key"]),
        ).fetchone()
        if not exists:
            insert("packing", data, holiday_id)
            added += 1
    return added


def template_list():
    rows = get_db().execute("SELECT * FROM packing_templates ORDER BY name").fetchall()
    return [
        {"id": row["id"], "name": row["name"], "item_count": len(json.loads(row["items_json"]))}
        for row in rows
    ]
