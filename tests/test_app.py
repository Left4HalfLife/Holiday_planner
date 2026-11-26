import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import requests

from app import create_app
from app.database import get_db


class MockModelHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.respond({"data": [{"id": "test-instruct"}]})

    def do_POST(self):
        self.server.last_request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.last_authorization = self.headers.get("Authorization")
        self.respond({
            "choices": [{"message": {"content": self.server.content}}],
        })

    def respond(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


class PlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model_server = ThreadingHTTPServer(("127.0.0.1", 0), MockModelHandler)
        cls.model_thread = threading.Thread(target=cls.model_server.serve_forever, daemon=True)
        cls.model_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.model_server.shutdown()
        cls.model_server.server_close()
        cls.model_thread.join()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = {
            "TESTING": True,
            "DATABASE": str(Path(self.directory.name) / "nested" / "holidays.db"),
            "LLM_BASE_URL": f"http://127.0.0.1:{self.model_server.server_port}/v1",
            "LLM_API_KEY": "test-token",
            "LLM_MODEL": "",
        }
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        self.model_reply()

    def model_reply(self, actions=None, findings=None, message="Here is your travel update."):
        self.model_server.content = json.dumps({
            "message": message, "actions": actions or [], "findings": findings or [],
        })

    def write(self, url, data=None, method="POST", expected=200):
        response = self.client.open(
            url, method=method, json=data if data is not None else {},
            headers={"X-Requested-With": "HolidayPlanner"},
        )
        self.assertEqual(response.status_code, expected, response.get_data(as_text=True))
        return response.get_json() if expected != 204 else None

    def create_trip(self, **overrides):
        return self.write("/api/holidays", {
            "title": "Coastal escape", "destination": "Amalfi, Italy",
            "start_date": "2027-11-01", "end_date": "2027-11-14",
            "budget": "1000.00", "currency": "EUR", **overrides,
        }, expected=201)

    def detail(self, holiday_id):
        response = self.client.get(f"/api/holidays/{holiday_id}")
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_database_initializes_and_survives_restart(self):
        holiday = self.create_trip(notes="Keep this across restarts")
        second_app = create_app(self.config)
        response = second_app.test_client().get(f"/api/holidays/{holiday['id']}")
        self.assertEqual(response.get_json()["notes"], "Keep this across restarts")
        with second_app.app_context():
            self.assertEqual(get_db().execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(get_db().execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_complete_holiday_crud_and_pages(self):
        holiday = self.create_trip(
            accommodation_name="Coast House", accommodation_address="1 Beach Road",
            booking_references="ABC123\nREF456", notes="Bring a book",
            laundry_available=True, weather="Tropical", air_quality="Moderate",
            dietary_requirements="Vegan",
        )
        self.assertEqual(holiday["duration"], 14)
        self.assertTrue(holiday["laundry_available"])
        self.assertEqual(holiday["accommodation_name"], "Coast House")
        changed = self.write(f"/api/holidays/{holiday['id']}", {"title": "Updated trip"}, method="PATCH")
        self.assertEqual(changed["title"], "Updated trip")
        self.assertEqual(changed["destination"], "Amalfi, Italy")
        for url in ("/", f"/holidays/{holiday['id']}", "/static/css/style.css", "/static/js/app.js", "/static/icons.svg"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            response.close()
        self.assertEqual(len(self.client.get("/api/holidays").get_json()), 1)
        self.write(f"/api/holidays/{holiday['id']}", method="DELETE", expected=204)
        self.assertEqual(self.client.get(f"/api/holidays/{holiday['id']}").status_code, 404)

    def test_holiday_validation_and_malformed_requests(self):
        holiday = self.create_trip()
        url = f"/api/holidays/{holiday['id']}"
        for data in (
            {"end_date": "2027-10-01"}, {"start_date": "2027-02-30"},
            {"start_date": "20271101"}, {"title": ""}, {"budget": -1},
            {"budget": "NaN"}, {"budget": "1.001"}, {"currency": "US"},
            {"laundry_available": "yes"}, {"weather": "Anything"},
            {"air_quality": "Maybe"}, {"destination": "<bad>\x00"},
            {"id": 999}, {"notes": "x" * 10001},
        ):
            with self.subTest(data=data):
                self.write(url, data, method="PATCH", expected=400)
        self.assertEqual(self.detail(holiday["id"])["end_date"], "2027-11-14")
        response = self.client.post("/api/holidays", json=[], headers={"X-Requested-With": "HolidayPlanner"})
        self.assertEqual(response.status_code, 400)
        response = self.client.post("/api/holidays", data="{broken", content_type="application/json", headers={"X-Requested-With": "HolidayPlanner"})
        self.assertEqual(response.status_code, 400)

    def test_cross_origin_and_form_writes_are_rejected(self):
        data = {"title": "Blocked"}
        self.assertEqual(self.client.post("/api/holidays", json=data).status_code, 403)
        self.assertEqual(self.client.post("/api/holidays", data=data).status_code, 403)
        self.assertEqual(self.client.post("/api/holidays", json=data, headers={
            "X-Requested-With": "HolidayPlanner", "Origin": "https://untrusted.example",
        }).status_code, 403)
        self.assertEqual(self.client.post("/api/holidays", json=data, headers={
            "X-Requested-With": "HolidayPlanner", "Sec-Fetch-Site": "cross-site",
        }).status_code, 403)
        response = self.client.get("/")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])

    def test_text_is_stored_without_sql_execution_and_escaped_in_html(self):
        title = "<script>alert('x')</script> '; DROP TABLE holidays; --"
        holiday = self.create_trip(title=title)
        self.assertEqual(self.detail(holiday["id"])["title"], title)
        page = self.client.get(f"/holidays/{holiday['id']}").get_data(as_text=True)
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertEqual(len(self.client.get("/api/holidays").get_json()), 1)

    def test_packing_crud_progress_and_duplicate_validation(self):
        holiday = self.create_trip()
        url = f"/api/holidays/{holiday['id']}/packing"
        item = self.write(url, {"name": "Socks", "category": "Clothing", "quantity": 4}, expected=201)
        self.write(f"{url}/{item['id']}", {"packed": True, "quantity": 3}, method="PATCH")
        detail = self.detail(holiday["id"])
        self.assertEqual((detail["packed_count"], detail["item_count"]), (1, 1))
        self.assertEqual(detail["packing_items"][0]["quantity"], 3)
        self.write(url, {"name": " SOCKS ", "category": "Clothing"}, expected=400)
        for data in ({"quantity": 0}, {"quantity": True}, {"quantity": 1.5}, {"packed": "false"}, {"category": "Invalid"}):
            self.write(f"{url}/{item['id']}", data, method="PATCH", expected=400)
        self.write(f"{url}/{item['id']}", method="DELETE", expected=204)
        self.assertEqual(self.detail(holiday["id"])["item_count"], 0)

    def test_expenses_use_exact_cents_and_allow_over_budget(self):
        holiday = self.create_trip(budget="0.30")
        url = f"/api/holidays/{holiday['id']}/expenses"
        first = self.write(url, {"description": "Snack", "category": "Food", "amount": "0.10"}, expected=201)
        self.write(url, {"description": "Tea", "category": "Food", "amount": "0.20"}, expected=201)
        self.assertEqual(self.detail(holiday["id"])["remaining"], 0)
        self.write(f"{url}/{first['id']}", {"amount": "0.15"}, method="PATCH")
        self.assertEqual(self.detail(holiday["id"])["remaining"], -0.05)
        self.write(f"/api/holidays/{holiday['id']}", {"currency": "USD"}, method="PATCH", expected=400)
        self.write(url, {"description": "Invalid", "amount": 0}, expected=400)
        self.write(f"{url}/{first['id']}", method="DELETE", expected=204)
        self.assertEqual(self.detail(holiday["id"])["spent"], 0.2)

    def test_flight_legs_and_timezone_validation(self):
        holiday = self.create_trip()
        url = f"/api/holidays/{holiday['id']}/flights"
        first = self.write(url, {
            "flight_number": "QF129", "airline": "Qantas", "departure_airport": "SYD",
            "arrival_airport": "PVG", "departure_time": "2027-11-12T09:30",
            "arrival_time": "2027-11-12T17:30", "departure_timezone": "Australia/Sydney",
            "arrival_timezone": "Asia/Shanghai", "terminal": "1", "gate": "10",
            "booking_code": "ABC123",
        }, expected=201)
        self.write(url, {"flight_number": "QF130"}, expected=201)
        self.write(f"{url}/{first['id']}", {"gate": "12"}, method="PATCH")
        self.assertEqual(len(self.detail(holiday["id"])["flights"]), 2)
        for data in ({"departure_timezone": "Not/AZone"}, {"departure_time": "2027-11-01"},
                     {"arrival_time": "2027-11-11T01:00"}, {"departure_time": "2027-11-12T09:30Z"}):
            self.write(f"{url}/{first['id']}", data, method="PATCH", expected=400)
        self.write(f"{url}/{first['id']}", method="DELETE", expected=204)

    def test_child_ids_are_scoped_to_the_trip(self):
        first, second = self.create_trip(), self.create_trip(title="Another trip")
        for collection, data in (
            ("packing", {"name": "Socks"}), ("flights", {"flight_number": "AB123"}),
            ("expenses", {"description": "Food", "amount": 10}),
        ):
            item = self.write(f"/api/holidays/{first['id']}/{collection}", data, expected=201)
            wrong = f"/api/holidays/{second['id']}/{collection}/{item['id']}"
            self.write(wrong, data, method="PATCH", expected=404)
            self.write(wrong, method="DELETE", expected=404)

    def test_holiday_deletion_cascades_but_keeps_templates(self):
        holiday = self.create_trip()
        root = f"/api/holidays/{holiday['id']}"
        self.write(root + "/packing", {"name": "Charger"}, expected=201)
        self.write(root + "/flights", {"flight_number": "AA1"}, expected=201)
        self.write(root + "/expenses", {"description": "Deposit", "amount": 50}, expected=201)
        self.write(root + "/templates", {"name": "Reusable"}, expected=201)
        self.write(root + "/ai/chat", {"message": "Hello"})
        self.write(root, method="DELETE", expected=204)
        with self.app.app_context():
            for table in ("packing_items", "flights", "expenses", "chat_messages"):
                self.assertEqual(get_db().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
        self.assertEqual(len(self.client.get("/api/templates").get_json()), 1)

    def test_templates_start_unpacked_and_preserve_existing_items(self):
        first = self.create_trip()
        root = f"/api/holidays/{first['id']}"
        self.write(root + "/packing", {"name": "Socks", "category": "Clothing", "quantity": 4, "packed": True}, expected=201)
        self.write(root + "/packing", {"name": "Charger", "category": "Documents & Tech"}, expected=201)
        saved = self.write(root + "/templates", {"name": "City break"}, expected=201)
        template_id = saved["templates"][0]["id"]
        self.write(root + "/templates", {"name": "city BREAK"}, expected=400)
        second = self.create_trip(title="New trip")
        second_root = f"/api/holidays/{second['id']}"
        self.write(second_root + "/packing", {"name": "socks", "category": "Clothing", "quantity": 2, "packed": True}, expected=201)
        result = self.write(second_root + f"/templates/{template_id}")
        self.assertEqual(result["added"], 1)
        result = self.write(second_root + f"/templates/{template_id}")
        self.assertEqual(result["added"], 0)
        items = self.detail(second["id"])["packing_items"]
        socks = next(item for item in items if item["name"] == "socks")
        charger = next(item for item in items if item["name"] == "Charger")
        self.assertEqual((socks["quantity"], socks["packed"]), (2, True))
        self.assertFalse(charger["packed"])
        self.write(f"/api/templates/{template_id}", method="DELETE", expected=204)
        self.assertEqual(len(self.detail(second["id"])["packing_items"]), 2)

    def test_ics_inclusive_dates_unicode_folding_and_flight_utc(self):
        holiday = self.create_trip(
            title="Coast, café; " * 10, start_date="2028-02-28", end_date="2028-03-01",
            booking_references="ABC\nDEF",
        )
        root = f"/api/holidays/{holiday['id']}"
        self.write(root + "/flights", {
            "flight_number": "QF129", "departure_time": "2028-02-28T09:30",
            "departure_timezone": "Australia/Sydney",
            "arrival_time": "2028-02-28T17:30", "arrival_timezone": "Asia/Shanghai",
        }, expected=201)
        self.write(root + "/flights", {"flight_number": "NO-TIME"}, expected=201)
        response = self.client.get(root + "/calendar.ics")
        raw = response.data.decode()
        unfolded = raw.replace("\r\n ", "")
        self.assertEqual(response.mimetype, "text/calendar")
        self.assertIn('attachment; filename="holiday-', response.headers["Content-Disposition"])
        self.assertIn("DTSTART;VALUE=DATE:20280228", unfolded)
        self.assertIn("DTEND;VALUE=DATE:20280302", unfolded)
        self.assertIn("DTSTART:20280227T223000Z", unfolded)
        self.assertIn("DTEND:20280228T093000Z", unfolded)
        self.assertIn(r"Coast\, café\;", unfolded)
        self.assertIn(r"ABC\nDEF", unfolded)
        self.assertEqual(unfolded.count("BEGIN:VEVENT"), 2)
        self.assertTrue(all(len(line.encode()) <= 75 for line in raw.split("\r\n")))

    def test_ai_health_and_offline_do_not_break_manual_crud(self):
        status = self.client.get("/api/ai/status").get_json()
        self.assertTrue(status["online"])
        self.assertEqual(status["model"], "test-instruct")
        holiday = self.create_trip()
        with patch("app.ai_service.requests.request", side_effect=requests.ConnectionError):
            status = self.client.get("/api/ai/status").get_json()
            self.assertFalse(status["online"])
            self.write(f"/api/holidays/{holiday['id']}/ai/packing", expected=503)
            self.write(f"/api/holidays/{holiday['id']}/packing", {"name": "Offline item"}, expected=201)
            self.assertEqual(self.client.get("/api/health").get_json(), {"status": "ok"})
        self.assertEqual(self.detail(holiday["id"])["item_count"], 1)

    def test_ai_chat_validates_and_saves_multiple_actions(self):
        holiday = self.create_trip(currency="AUD")
        self.model_reply(actions=[
            {"type": "add_flight", "data": {"flight_number": "QF129", "departure_airport": "SYD", "departure_time": "2027-11-12T09:30"}},
            {"type": "add_packing_item", "data": {"name": "KN95 masks", "category": "Medication & Health", "quantity": 3}},
            {"type": "add_expense", "data": {"description": "Hotel deposit", "category": "Accommodation", "amount": 140}},
        ])
        result = self.write(f"/api/holidays/{holiday['id']}/ai/chat", {"message": "Add flight, masks and hotel deposit."})
        self.assertEqual(result["applied"], 3)
        detail = self.detail(holiday["id"])
        self.assertEqual(detail["spent"], 140)
        self.assertEqual(detail["packing_items"][0]["quantity"], 3)
        self.assertEqual(detail["flights"][0]["flight_number"], "QF129")
        request = self.model_server.last_request
        self.assertEqual(request["response_format"], {"type": "json_object"})
        self.assertEqual(request["model"], "test-instruct")
        self.assertEqual(self.model_server.last_authorization, "Bearer test-token")
        history = self.client.get(f"/api/holidays/{holiday['id']}/chat").get_json()
        self.assertEqual([message["role"] for message in history], ["user", "assistant"])
        self.assertIn("Saved 3 changes.", history[-1]["content"])

    def test_ai_invalid_batch_rolls_back_all_actions_and_chat(self):
        holiday = self.create_trip()
        other = self.create_trip()
        foreign = self.write(f"/api/holidays/{other['id']}/packing", {"name": "Private item"}, expected=201)
        invalid_actions = [
            {"type": "run_sql", "data": {"sql": "DELETE FROM holidays"}},
            {"type": "add_packing_item", "data": {"name": "Bad", "quantity": -1}},
            {"type": "update_packing_item", "id": foreign["id"], "data": {"packed": True}},
            {"type": "delete_packing_item", "id": True},
            {"type": "add_expense", "data": {"description": "Bad", "amount": "Infinity"}},
        ]
        for invalid in invalid_actions:
            with self.subTest(action=invalid):
                self.model_reply(actions=[
                    {"type": "add_expense", "data": {"description": "Must roll back", "amount": 10}},
                    {"type": "update_holiday", "data": {"notes": "Must roll back"}},
                    invalid,
                ])
                self.write(f"/api/holidays/{holiday['id']}/ai/chat", {"message": "Please update"}, expected=503)
                detail = self.detail(holiday["id"])
                self.assertEqual(detail["spent"], 0)
                self.assertEqual(detail["notes"], "")
                self.assertEqual(self.client.get(f"/api/holidays/{holiday['id']}/chat").get_json(), [])

    def test_ai_updates_existing_records_and_deletes_requested_item(self):
        holiday = self.create_trip()
        root = f"/api/holidays/{holiday['id']}"
        item = self.write(root + "/packing", {"name": "Charger"}, expected=201)
        spare = self.write(root + "/packing", {"name": "Spare charger"}, expected=201)
        flight = self.write(root + "/flights", {"flight_number": "QF129"}, expected=201)
        self.model_reply(actions=[
            {"type": "update_packing_item", "id": item["id"], "data": {"quantity": 2, "packed": True}},
            {"type": "delete_packing_item", "id": spare["id"]},
            {"type": "update_flight", "id": flight["id"], "data": {"gate": "B12"}},
            {"type": "update_holiday", "data": {"laundry_available": True, "notes": "Book the train"}},
        ])
        result = self.write(root + "/ai/chat", {"message": "Update the charger, remove the spare, add gate B12 and update my notes."})
        self.assertEqual(result["applied"], 4)
        detail = self.detail(holiday["id"])
        self.assertEqual(detail["packing_items"][0]["quantity"], 2)
        self.assertEqual((detail["packed_count"], detail["item_count"]), (1, 1))
        self.assertEqual(detail["flights"][0]["gate"], "B12")
        self.assertTrue(detail["laundry_available"])
        self.assertEqual(detail["notes"], "Book the train")

    def test_ai_rejects_bad_json_without_writing(self):
        holiday = self.create_trip()
        for content in (
            "not JSON", '{"message":"hello","actions":{},"findings":[]}',
            '{"message":"hello","actions":[],"findings":[],"extra":true}',
            '{"message":"hello","actions":[],"findings":[{}]}',
        ):
            self.model_server.content = content
            self.write(f"/api/holidays/{holiday['id']}/ai/packing", expected=503)
        self.assertEqual(self.detail(holiday["id"])["item_count"], 0)

    def test_smart_packing_laundry_weather_aqi_and_dietary_rules(self):
        for laundry, expected in ((False, 14), (True, 4)):
            with self.subTest(laundry=laundry):
                holiday = self.create_trip(
                    laundry_available=laundry, weather="Cold",
                    air_quality="High/Unhealthy", dietary_requirements="Nut allergy",
                )
                self.model_reply(actions=[{
                    "type": "add_packing_item",
                    "data": {"name": "Reusable water bottle", "category": "Miscellaneous", "quantity": 1},
                }])
                root = f"/api/holidays/{holiday['id']}"
                self.write(root + "/ai/packing")
                detail = self.detail(holiday["id"])
                items = {item["name"]: item for item in detail["packing_items"]}
                self.assertEqual(items["Underwear"]["quantity"], expected)
                self.assertEqual(items["Socks"]["quantity"], expected)
                for name in ("Certified KN95 masks", "Saline nasal spray", "Warm coat and thermal layers", "Dietary translation cards", "Reusable water bottle"):
                    self.assertIn(name, items)
                self.write(root + f"/packing/{items['Socks']['id']}", {"packed": True, "quantity": 2}, method="PATCH")
                result = self.write(root + "/ai/packing")
                self.assertEqual(result["applied"], 0)
                socks = next(item for item in self.detail(holiday["id"])["packing_items"] if item["name"] == "Socks")
                self.assertEqual((socks["quantity"], socks["packed"]), (2, True))

    def test_packing_invalid_actions_roll_back_server_basics(self):
        holiday = self.create_trip()
        self.model_reply(actions=[{"type": "add_expense", "data": {"description": "Not packing", "amount": 100}}])
        self.write(f"/api/holidays/{holiday['id']}/ai/packing", expected=503)
        self.assertEqual(self.detail(holiday["id"])["item_count"], 0)

    def test_audit_is_read_only_and_persists_findings(self):
        holiday = self.create_trip()
        before = self.detail(holiday["id"])
        self.model_reply(findings=["No return flight added.", "Prepare dietary translation cards."])
        result = self.write(f"/api/holidays/{holiday['id']}/ai/audit")
        self.assertEqual(result["applied"], 0)
        self.assertEqual(self.detail(holiday["id"]), before)
        self.assertIn("No return flight", result["message"])
        self.model_reply(actions=[{"type": "add_packing_item", "data": {"name": "Not allowed"}}])
        self.write(f"/api/holidays/{holiday['id']}/ai/audit", expected=503)
        self.assertEqual(self.detail(holiday["id"]), before)


if __name__ == "__main__":
    unittest.main()
