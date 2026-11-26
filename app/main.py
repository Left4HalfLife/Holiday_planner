import json
import sqlite3

from flask import Blueprint, Response, abort, jsonify, render_template, request

from .ai_service import AIError, change_holiday, health_status, run_assistant
from .calendar_export import export_ics
from .database import get_db
from .services import (
    TABLES, add_packing_items, get_child, get_holiday, holiday_detail,
    insert, serialize, template_list, update,
)
from .validation import CATEGORIES, EXPENSE_CATEGORIES, ValidationError, text, validate


bp = Blueprint("main", __name__)


def payload():
    data = request.get_json()
    if not isinstance(data, dict):
        raise ValidationError("The JSON payload must be an object.")
    return data


@bp.get("/")
def index():
    return render_template("index.html")


@bp.get("/holidays/<int:holiday_id>")
def holiday_page(holiday_id):
    return render_template(
        "holiday.html", holiday=get_holiday(holiday_id),
        categories=CATEGORIES, expense_categories=EXPENSE_CATEGORIES,
    )


@bp.get("/api/health")
def health():
    get_db().execute("SELECT 1").fetchone()
    return jsonify(status="ok")


@bp.get("/api/ai/status")
def ai_status():
    return jsonify(health_status())


@bp.get("/api/holidays")
def holidays_list():
    rows = get_db().execute("""
        SELECT h.*,
          (SELECT COUNT(*) FROM packing_items p WHERE p.holiday_id = h.id) AS item_count,
          (SELECT COUNT(*) FROM packing_items p WHERE p.holiday_id = h.id AND p.packed = 1) AS packed_count
        FROM holidays h ORDER BY h.start_date, h.id
    """).fetchall()
    return jsonify([serialize("holiday", row) for row in rows])


@bp.post("/api/holidays")
def holidays_create():
    data = validate("holiday", payload())
    with get_db():
        holiday_id = insert("holiday", data)
    return jsonify(holiday_detail(holiday_id)), 201


@bp.get("/api/holidays/<int:holiday_id>")
def holidays_get(holiday_id):
    return jsonify(holiday_detail(holiday_id))


@bp.patch("/api/holidays/<int:holiday_id>")
def holidays_update(holiday_id):
    with get_db():
        change_holiday(holiday_id, payload())
    return jsonify(holiday_detail(holiday_id))


@bp.delete("/api/holidays/<int:holiday_id>")
def holidays_delete(holiday_id):
    get_holiday(holiday_id)
    with get_db():
        get_db().execute("DELETE FROM holidays WHERE id = ?", (holiday_id,))
    return "", 204


def child_kind(collection):
    mapping = {"packing": "packing", "flights": "flight", "expenses": "expense"}
    if collection not in mapping:
        abort(404)
    return mapping[collection]


@bp.post("/api/holidays/<int:holiday_id>/<collection>")
def child_create(holiday_id, collection):
    kind = child_kind(collection)
    get_holiday(holiday_id)
    data = validate(kind, payload())
    with get_db():
        item_id = insert(kind, data, holiday_id)
    return jsonify(get_child(kind, holiday_id, item_id)), 201


@bp.patch("/api/holidays/<int:holiday_id>/<collection>/<int:item_id>")
def child_update(holiday_id, collection, item_id):
    kind = child_kind(collection)
    current = get_child(kind, holiday_id, item_id)
    data = validate(kind, payload(), current)
    with get_db():
        update(kind, item_id, data, holiday_id)
    return jsonify(get_child(kind, holiday_id, item_id))


@bp.delete("/api/holidays/<int:holiday_id>/<collection>/<int:item_id>")
def child_delete(holiday_id, collection, item_id):
    kind = child_kind(collection)
    get_child(kind, holiday_id, item_id)
    with get_db():
        get_db().execute(f"DELETE FROM {TABLES[kind]} WHERE id = ? AND holiday_id = ?", (item_id, holiday_id))
    return "", 204


@bp.get("/api/holidays/<int:holiday_id>/calendar.ics")
def calendar_download(holiday_id):
    return Response(
        export_ics(holiday_detail(holiday_id)), mimetype="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="holiday-{holiday_id}.ics"'},
    )


@bp.get("/api/templates")
def templates_list():
    return jsonify(template_list())


@bp.post("/api/holidays/<int:holiday_id>/templates")
def templates_save(holiday_id):
    data = payload()
    if set(data) != {"name"}:
        raise ValidationError("Provide a template name.")
    name = text(data["name"], "Template name", 100, True)
    holiday = holiday_detail(holiday_id)
    if not holiday["packing_items"]:
        raise ValidationError("Add packing items before saving a template.")
    items = [
        {key: item[key] for key in ("name", "category", "quantity")}
        for item in holiday["packing_items"]
    ]
    try:
        with get_db():
            get_db().execute(
                "INSERT INTO packing_templates (name, items_json) VALUES (?, ?)", (name, json.dumps(items))
            )
    except sqlite3.IntegrityError as error:
        if error.sqlite_errorname != "SQLITE_CONSTRAINT_UNIQUE":
            raise
        raise ValidationError("A template with that name already exists.") from None
    return jsonify(templates=template_list()), 201


@bp.post("/api/holidays/<int:holiday_id>/templates/<int:template_id>")
def templates_apply(holiday_id, template_id):
    get_holiday(holiday_id)
    row = get_db().execute("SELECT items_json FROM packing_templates WHERE id = ?", (template_id,)).fetchone()
    if row is None:
        abort(404, description="Template not found.")
    with get_db():
        added = add_packing_items(holiday_id, json.loads(row["items_json"]))
    return jsonify(added=added)


@bp.delete("/api/templates/<int:template_id>")
def templates_delete(template_id):
    with get_db():
        cursor = get_db().execute("DELETE FROM packing_templates WHERE id = ?", (template_id,))
        if not cursor.rowcount:
            abort(404, description="Template not found.")
    return "", 204


@bp.get("/api/holidays/<int:holiday_id>/chat")
def chat_history(holiday_id):
    get_holiday(holiday_id)
    rows = get_db().execute(
        "SELECT role, content, created_at FROM chat_messages WHERE holiday_id = ? ORDER BY id DESC LIMIT 50",
        (holiday_id,),
    ).fetchall()
    return jsonify([dict(row) for row in reversed(rows)])


@bp.post("/api/holidays/<int:holiday_id>/ai/<mode>")
def ai_action(holiday_id, mode):
    if mode not in {"chat", "packing", "audit"}:
        abort(404)
    data = payload()
    if set(data) - {"message"}:
        raise ValidationError("Only a message field is supported.")
    message = text(data.get("message", ""), "Message", 4000, mode == "chat")
    try:
        return jsonify(run_assistant(holiday_id, mode, message))
    except AIError as error:
        return jsonify(error=str(error)), 503
