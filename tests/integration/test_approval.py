"""Proceed -> approve -> executing, with the guards around each step."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from flowremote.api.app import create_app  # noqa: E402
from flowremote.control_plane.auth import create_user  # noqa: E402
from flowremote.control_plane.db import PROJECT_ROOT, Database  # noqa: E402

DB_PATH = PROJECT_ROOT / "data" / "runtime" / "tests" / "approval.db"
DB_URL = f"sqlite:///{DB_PATH.as_posix()}"
TABLES = ("activity_events", "execution_runs", "decisions", "approvals", "exceptions",
          "source_records", "tasks", "users")


class ApprovalTests(unittest.TestCase):
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
            " VALUES (?, 'Order Data Validation & Sync', 2, 'review_required',"
            " 'Orders_September.xlsx', 'Company Workspace', 'OA - Order Administration',"
            " 'BI - Business Intelligence', ?, ?, ?)",
            (task_id, owner, now, now),
        )
        rows = [
            ("ORD-052", "Missing Customer ID", "customer_id", "(blank)", "C-1024", 0.98,
             "AI unique match from customer registry."),
            ("ORD-081", "Missing Quantity", "quantity", "(blank)", None, None,
             "No historical data available for this order line quantity."),
        ]
        for index, row in enumerate(rows, start=1):
            record, issue, fields, original, suggestion, confidence, reason = row
            db.execute(
                "INSERT INTO exceptions (id, task_id, record_id, issue, flagged_fields,"
                " original_value, suggestion, confidence, reason, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'unresolved', ?)",
                (f"EXC-{task_id}-{index}", task_id, record, issue, fields, original,
                 suggestion, confidence, reason, now),
            )

    def login(self) -> None:
        response = self.client.post(
            "/login", data={"email": "alex@example.com", "password": "password123"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def resolve_all(self, task: str = "TASK-A") -> None:
        with Database(DB_URL) as db:
            db.execute(
                "UPDATE exceptions SET status = 'accepted', resolved_value = 'C-1024',"
                " reviewed_by = 'USR-A', reviewed_at = '2026-09-30T14:10:00Z'"
                " WHERE task_id = ? AND record_id = 'ORD-052'",
                (task,),
            )
            db.execute(
                "UPDATE exceptions SET status = 'skipped', resolved_value = NULL,"
                " reviewed_by = 'USR-A', reviewed_at = '2026-09-30T14:11:00Z'"
                " WHERE task_id = ? AND record_id = 'ORD-081'",
                (task,),
            )

    def task_row(self, task: str = "TASK-A") -> dict:
        with Database(DB_URL) as db:
            return db.query("SELECT status FROM tasks WHERE id = ?", (task,))[0]

    def approval_rows(self) -> list[dict]:
        with Database(DB_URL) as db:
            return db.query("SELECT * FROM approvals ORDER BY attempt")

    def proceed(self, task: str = "TASK-A"):
        return self.client.post(f"/tasks/{task}/proceed", follow_redirects=False)

    def approve(self, task: str = "TASK-A"):
        return self.client.post(f"/tasks/{task}/approval", follow_redirects=False)

    # -- proceed ---------------------------------------------------------
    def test_proceed_is_blocked_while_unresolved(self):
        self.login()
        response = self.proceed()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.task_row()["status"], "review_required")

    def test_proceed_moves_to_pending_approval(self):
        self.login()
        self.resolve_all()
        response = self.proceed()
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers.get("location"), "/tasks/TASK-A/approval")
        self.assertEqual(self.task_row()["status"], "pending_approval")

    # -- the approval page ------------------------------------------------
    def test_approval_page_needs_the_proceed_step(self):
        self.login()
        response = self.client.get("/tasks/TASK-A/approval", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers.get("location"), "/tasks/TASK-A")

    def test_approval_page_shows_the_summary_and_targets(self):
        self.login()
        self.resolve_all()
        self.proceed()
        page = self.client.get("/tasks/TASK-A/approval")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Execution Approval", page.text)
        self.assertIn("Approve &amp; Execute", page.text)
        self.assertIn("Back to review", page.text)
        self.assertIn("OA - Order Administration", page.text)
        self.assertIn("BI - Business Intelligence", page.text)
        self.assertIn("never a second copy", page.text)
        self.assertIn("Only this approval releases the write", page.text)

    # -- approve ----------------------------------------------------------
    def test_approve_writes_one_row_and_starts_execution(self):
        self.login()
        self.resolve_all()
        self.proceed()
        response = self.approve()
        self.assertEqual(response.status_code, 303)
        rows = self.approval_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["attempt"], 1)
        self.assertEqual(rows[0]["approved_count"], 1)
        self.assertEqual(rows[0]["skipped_count"], 1)
        self.assertEqual(rows[0]["approver_id"], "USR-A")
        self.assertEqual(self.task_row()["status"], "executing")

    def test_approve_twice_keeps_one_row(self):
        self.login()
        self.resolve_all()
        self.proceed()
        self.approve()
        second = self.approve()
        self.assertEqual(second.status_code, 303)
        self.assertEqual(len(self.approval_rows()), 1)

    def test_approve_needs_the_pending_state(self):
        self.login()
        self.resolve_all()
        response = self.approve()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.approval_rows(), [])

    # -- back to review ---------------------------------------------------
    def test_back_to_review_returns_to_review(self):
        self.login()
        self.resolve_all()
        self.proceed()
        response = self.client.post("/tasks/TASK-A/back-to-review", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.task_row()["status"], "review_required")

    def test_back_to_review_is_refused_after_approval(self):
        self.login()
        self.resolve_all()
        self.proceed()
        self.approve()
        response = self.client.post("/tasks/TASK-A/back-to-review", follow_redirects=False)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.task_row()["status"], "executing")

    # -- guards -----------------------------------------------------------
    def test_decisions_are_refused_after_proceed(self):
        self.login()
        self.resolve_all()
        self.proceed()
        response = self.client.post(
            "/tasks/TASK-A/exceptions/ORD-052/decisions",
            data={"action": "accept", "decision_id": "K-1"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 400)
        with Database(DB_URL) as db:
            self.assertEqual(db.scalar("SELECT COUNT(*) FROM decisions"), 0)

    def test_another_accounts_task_cannot_be_proceeded(self):
        self.login()
        self.resolve_all("TASK-B")
        self.assertEqual(self.proceed("TASK-B").status_code, 404)

    def test_anonymous_is_redirected(self):
        response = self.client.post("/tasks/TASK-A/proceed", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers.get("location"), "/login")


if __name__ == "__main__":
    unittest.main()
