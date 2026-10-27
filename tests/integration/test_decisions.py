"""Accept / Edit / Skip: the write path, its guards, and the gate."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from flowremote.api.app import create_app  # noqa: E402
from flowremote.control_plane.auth import create_user  # noqa: E402
from flowremote.control_plane.db import PROJECT_ROOT, Database  # noqa: E402

DB_PATH = PROJECT_ROOT / "data" / "runtime" / "tests" / "review.db"
DB_URL = f"sqlite:///{DB_PATH.as_posix()}"
TABLES = ("activity_events", "execution_runs", "decisions", "approvals", "exceptions",
          "source_records", "tasks", "users")

EXCEPTIONS = [
    ("ORD-052", "Missing Customer ID", "customer_id", "(blank)", "C-1024", 0.98,
     "AI unique match from customer registry."),
    ("ORD-081", "Missing Quantity", "quantity", "(blank)", None, None,
     "No historical data available for this order line quantity."),
    ("ORD-099", "Missing Name + ID", "customer_name, customer_id", "(both blank)",
     "Unreliable - skip recommended", 0.68,
     "Multiple possible matches, none above confidence threshold."),
]


class DecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = create_app(database_url=DB_URL, session_secret="test-secret")

    def setUp(self) -> None:
        with Database(DB_URL) as db:
            db.apply_migrations()
            for table in TABLES:
                db.execute(f"DELETE FROM {table}")
            create_user(db, name="Alex Morgan", email="alex@example.com",
                        password="password123", user_id="USR-A")
            create_user(db, name="Bea Chen", email="bea@example.com",
                        password="password123", user_id="USR-B")
            self.seed_task(db, "TASK-A", "USR-A")
            self.seed_task(db, "TASK-B", "USR-B")
        self.client = TestClient(self.app)

    @staticmethod
    def seed_task(db: Database, task_id: str, owner: str) -> None:
        now = "2026-09-30T14:00:00Z"
        db.execute(
            "INSERT INTO tasks (id, workflow, batch_size, status, source_file, source_location,"
            " primary_target, secondary_target, owner_id, created_at, updated_at)"
            " VALUES (?, 'Order Data Validation & Sync', 100, 'review_required',"
            " 'Orders_September.xlsx', 'Company Workspace', 'OA', 'BI', ?, ?, ?)",
            (task_id, owner, now, now),
        )
        for index, row in enumerate(EXCEPTIONS, start=1):
            record, issue, fields, original, suggestion, confidence, reason = row
            db.execute(
                "INSERT INTO exceptions (id, task_id, record_id, issue, flagged_fields,"
                " original_value, suggestion, confidence, reason, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'unresolved', ?)",
                (f"EXC-{task_id}-{index}", task_id, record, issue, fields, original,
                 suggestion, confidence, reason, now),
            )
        db.execute(
            "INSERT INTO source_records (task_id, record_id, customer_name, customer_id,"
            " quantity, unit_price, amount, order_date, outcome)"
            " VALUES (?, 'ORD-001', 'X', 'C-1', 1, 1.0, 1.0, '2026-09-01', 'passed')",
            (task_id,),
        )

    def login(self) -> None:
        response = self.client.post(
            "/login",
            data={"email": "alex@example.com", "password": "password123"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def decide(self, record: str, action: str, value: str | None = None,
               decision_id: str = "K-default", task: str = "TASK-A"):
        return self.client.post(
            f"/tasks/{task}/exceptions/{record}/decisions",
            data={"action": action, "value": value or "", "decision_id": decision_id},
            follow_redirects=False,
        )

    def exception_row(self, record: str) -> dict:
        with Database(DB_URL) as db:
            return db.query(
                "SELECT status, resolved_value, reviewed_by FROM exceptions"
                " WHERE task_id = 'TASK-A' AND record_id = ?",
                (record,),
            )[0]

    def decision_count(self) -> int:
        with Database(DB_URL) as db:
            return db.scalar("SELECT COUNT(*) FROM decisions")

    # -- the three actions ----------------------------------------------
    def test_accept_keeps_the_suggestion(self):
        self.login()
        response = self.decide("ORD-052", "accept", decision_id="K-1")
        self.assertEqual(response.status_code, 303)
        row = self.exception_row("ORD-052")
        self.assertEqual(row["status"], "accepted")
        self.assertEqual(row["resolved_value"], "C-1024")
        self.assertEqual(row["reviewed_by"], "USR-A")
        self.assertEqual(self.decision_count(), 1)

    def test_edit_saves_the_operator_value(self):
        self.login()
        self.assertEqual(self.decide("ORD-081", "edit", "6", "K-2").status_code, 303)
        row = self.exception_row("ORD-081")
        self.assertEqual(row["status"], "manual")
        self.assertEqual(row["resolved_value"], "6")

    def test_skip_leaves_no_value(self):
        self.login()
        self.assertEqual(self.decide("ORD-099", "skip", None, "K-3").status_code, 303)
        row = self.exception_row("ORD-099")
        self.assertEqual(row["status"], "skipped")
        self.assertIsNone(row["resolved_value"])

    def test_the_page_shows_the_actions(self):
        self.login()
        page = self.client.get("/tasks/TASK-A")
        self.assertEqual(page.status_code, 200)
        self.assertIn('value="accept"', page.text)
        self.assertIn('value="skip"', page.text)
        self.assertIn('value="edit"', page.text)

    # -- guards ----------------------------------------------------------
    def test_accept_without_a_suggestion_is_refused(self):
        self.login()
        response = self.decide("ORD-081", "accept", decision_id="K-4")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.exception_row("ORD-081")["status"], "unresolved")
        self.assertEqual(self.decision_count(), 0)

    def test_edit_without_a_value_is_refused(self):
        self.login()
        self.assertEqual(self.decide("ORD-081", "edit", "  ", "K-5").status_code, 400)
        self.assertEqual(self.exception_row("ORD-081")["status"], "unresolved")

    def test_a_replayed_decision_is_not_counted_twice(self):
        self.login()
        self.decide("ORD-052", "accept", decision_id="K-6")
        second = self.decide("ORD-052", "accept", decision_id="K-6")
        self.assertEqual(second.status_code, 303)
        self.assertEqual(self.decision_count(), 1)
        self.assertEqual(self.exception_row("ORD-052")["status"], "accepted")

    def test_another_accounts_task_cannot_be_decided(self):
        self.login()
        response = self.decide("ORD-052", "accept", decision_id="K-7", task="TASK-B")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.decision_count(), 0)

    def test_anonymous_requests_are_redirected(self):
        response = self.client.post(
            "/tasks/TASK-A/exceptions/ORD-052/decisions",
            data={"action": "accept", "decision_id": "K-8"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers.get("location"), "/login")

    # -- the gate --------------------------------------------------------
    def test_the_gate_stays_closed_while_anything_is_unresolved(self):
        self.login()
        self.decide("ORD-052", "accept", decision_id="K-9")
        page = self.client.get("/tasks/TASK-A")
        self.assertIn("2 unresolved exception(s) still block approval.", page.text)
        self.assertIn("Blocked", page.text)

    def test_the_gate_opens_when_everything_is_resolved(self):
        self.login()
        self.decide("ORD-052", "accept", decision_id="K-10")
        self.decide("ORD-081", "edit", "6", "K-11")
        self.decide("ORD-099", "skip", None, "K-12")
        page = self.client.get("/tasks/TASK-A")
        self.assertIn("Every exception is resolved.", page.text)
        self.assertIn("/tasks/TASK-A/proceed", page.text)


if __name__ == "__main__":
    unittest.main()
