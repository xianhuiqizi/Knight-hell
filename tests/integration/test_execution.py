"""Feature 2 end to end: approve -> execute in steps -> results -> activity log.

The batch is 100 input records: 99 already passed and 1 skipped exception, so
the approval releases 99 records and a run finishes in five steps of twenty.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from flowremote.api.app import create_app  # noqa: E402
from flowremote.control_plane.auth import create_user  # noqa: E402
from flowremote.control_plane.db import PROJECT_ROOT, Database  # noqa: E402

DB_PATH = PROJECT_ROOT / "data" / "runtime" / "tests" / "execution.db"
DB_URL = f"sqlite:///{DB_PATH.as_posix()}"
TABLES = (
    "activity_events",
    "execution_runs",
    "decisions",
    "approvals",
    "exceptions",
    "source_records",
    "tasks",
    "users",
)
NOW = "2026-09-30T14:00:00Z"


class ExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = create_app(database_url=DB_URL, session_secret="test-secret")

    def setUp(self) -> None:
        os.environ.pop("FLOWREMOTE_EXECUTION_FAIL_AT", None)
        with Database(DB_URL) as db:
            db.apply_migrations()
            for table in TABLES:
                db.execute(f"DELETE FROM {table}")
            create_user(db, name="Alex Morgan", email="alex@example.com",
                        password="password123", user_id="USR-A")
            create_user(db, name="Bea Chen", email="bea@example.com",
                        password="password123", user_id="USR-B")
            self.seed_task(db, "TASK-A", "USR-A")
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        os.environ.pop("FLOWREMOTE_EXECUTION_FAIL_AT", None)

    @staticmethod
    def seed_task(db: Database, task_id: str, owner: str) -> None:
        """99 passed records + 1 skipped exception = 100 input, 99 approvable."""
        db.execute(
            "INSERT INTO tasks (id, workflow, batch_size, status, source_file, source_location,"
            " primary_target, secondary_target, owner_id, created_at, updated_at)"
            " VALUES (?, 'Order Data Validation & Sync', 100, 'review_required',"
            " 'Orders_September.xlsx', 'Company Workspace', 'OA - Order Administration',"
            " 'BI - Business Intelligence', ?, ?, ?)",
            (task_id, owner, NOW, NOW),
        )
        for index in range(1, 100):
            db.execute(
                "INSERT INTO source_records (task_id, record_id, customer_name, customer_id,"
                " quantity, unit_price, amount, order_date, outcome)"
                " VALUES (?, ?, 'Customer', 'C-1', 1, 2.0, 2.0, '2026-09-01', 'passed')",
                (task_id, f"ORD-{index:03d}"),
            )
        db.execute(
            "INSERT INTO exceptions (id, task_id, record_id, issue, flagged_fields,"
            " original_value, suggestion, confidence, reason, status, created_at)"
            " VALUES (?, ?, 'ORD-100', 'Missing Name + ID', 'customer_name, customer_id',"
            " '(both blank)', 'Unreliable - skip recommended', 0.68, 'why', 'skipped', ?)",
            (f"EXC-{task_id}-1", task_id, NOW),
        )

    def login(self, email: str = "alex@example.com") -> None:
        response = self.client.post(
            "/login", data={"email": email, "password": "password123"}, follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)

    def approve(self, task: str = "TASK-A") -> None:
        self.assertEqual(self.client.post(f"/tasks/{task}/proceed",
                                          follow_redirects=False).status_code, 303)
        self.assertEqual(self.client.post(f"/tasks/{task}/approval",
                                          follow_redirects=False).status_code, 303)

    def step(self, task: str = "TASK-A") -> dict:
        response = self.client.post(
            f"/tasks/{task}/execution/step", headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def run_rows(self, task: str = "TASK-A") -> list[dict]:
        with Database(DB_URL) as db:
            return db.query("SELECT * FROM execution_runs WHERE task_id = ?", (task,))

    def event_rows(self, task: str = "TASK-A") -> list[dict]:
        with Database(DB_URL) as db:
            return db.query(
                "SELECT kind, actor, actor_kind, description FROM activity_events"
                " WHERE task_id = ? ORDER BY occurred_at, id",
                (task,),
            )

    def task_status(self, task: str = "TASK-A") -> str:
        with Database(DB_URL) as db:
            return db.scalar("SELECT status FROM tasks WHERE id = ?", (task,))

    # --- what approval creates ------------------------------------------------

    def test_approval_creates_one_run_starting_at_zero(self) -> None:
        self.login()
        self.approve()
        runs = self.run_rows()
        self.assertEqual(len(runs), 1)
        run = runs[0]
        self.assertEqual((run["attempt"], run["approved_count"]), (1, 99))
        self.assertEqual((run["written_count"], run["synced_count"]), (0, 0))
        self.assertEqual(run["status"], "executing")
        self.assertEqual(self.task_status(), "executing")

    def test_approving_twice_does_not_create_a_second_run(self) -> None:
        self.login()
        self.approve()
        self.client.post("/tasks/TASK-A/approval", follow_redirects=False)
        self.assertEqual(len(self.run_rows()), 1)

    def test_approval_is_logged(self) -> None:
        self.login()
        self.approve()
        kinds = [event["kind"] for event in self.event_rows()]
        self.assertIn("execution_approved", kinds)
        approved = next(e for e in self.event_rows() if e["kind"] == "execution_approved")
        self.assertEqual(approved["actor_kind"], "user")
        self.assertIn("99", approved["description"])

    # --- the pages ------------------------------------------------------------

    def test_execution_page_is_closed_before_approval(self) -> None:
        self.login()
        response = self.client.get("/tasks/TASK-A/execution", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/tasks/TASK-A")

    def test_task_page_offers_the_execution_entry(self) -> None:
        self.login()
        self.approve()
        page = self.client.get("/tasks/TASK-A")
        self.assertIn("/tasks/TASK-A/execution", page.text)

    def test_execution_page_shows_the_approved_count(self) -> None:
        self.login()
        self.approve()
        page = self.client.get("/tasks/TASK-A")
        self.assertEqual(page.status_code, 200)
        self.assertIn("99", page.text)
        execution = self.client.get("/tasks/TASK-A/execution")
        self.assertEqual(execution.status_code, 200)
        self.assertIn("approved", execution.text)
        self.assertIn("simulated", execution.text.lower())

    def test_results_redirect_while_the_run_is_still_going(self) -> None:
        self.login()
        self.approve()
        response = self.client.get("/tasks/TASK-A/results", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/tasks/TASK-A/execution")

    # --- stepping -------------------------------------------------------------

    def test_five_steps_finish_a_99_record_run(self) -> None:
        self.login()
        self.approve()
        written = [self.step()["written"] for _ in range(5)]
        self.assertEqual(written, [20, 40, 60, 80, 99])
        run = self.run_rows()[0]
        self.assertEqual(run["status"], "complete")
        self.assertEqual((run["written_count"], run["synced_count"]), (99, 99))
        self.assertEqual(run["written_count"], run["approved_count"])
        self.assertEqual(self.task_status(), "complete")

    def test_the_final_step_records_a_finish_time_and_duration(self) -> None:
        self.login()
        self.approve()
        for _ in range(5):
            self.step()
        run = self.run_rows()[0]
        self.assertIsNotNone(run["finished_at"])
        self.assertIsNotNone(run["duration_ms"])
        self.assertGreaterEqual(run["duration_ms"], 0)

    def test_a_step_after_completion_changes_nothing(self) -> None:
        self.login()
        self.approve()
        for _ in range(5):
            self.step()
        data = self.step()
        self.assertEqual(data["status"], "complete")
        self.assertEqual(data["written"], 99)
        self.assertEqual(len(self.run_rows()), 1)

    def test_completion_is_logged_by_the_engine(self) -> None:
        self.login()
        self.approve()
        for _ in range(5):
            self.step()
        completed = [e for e in self.event_rows() if e["kind"] == "execution_completed"]
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["actor_kind"], "engine")
        self.assertIn("99", completed[0]["description"])

    # --- partial failure ------------------------------------------------------

    def test_a_failed_write_stops_the_run_and_leaves_the_task_executing(self) -> None:
        self.login()
        self.approve()
        with patch.dict(os.environ, {"FLOWREMOTE_EXECUTION_FAIL_AT": "25"}):
            first = self.step()
            self.assertEqual(first["written"], 20)
            second = self.step()
        self.assertEqual(second["written"], 24)
        self.assertEqual(second["status"], "partial")
        self.assertIn("record 25", second["failure"] or "")
        run = self.run_rows()[0]
        self.assertEqual(run["status"], "partial")
        self.assertEqual(run["written_count"], 24)
        self.assertEqual(self.task_status(), "executing")
        kinds = [event["kind"] for event in self.event_rows()]
        self.assertIn("execution_failed", kinds)
        self.assertNotIn("execution_completed", kinds)

    def test_a_partial_run_shows_results_with_a_warning(self) -> None:
        self.login()
        self.approve()
        with patch.dict(os.environ, {"FLOWREMOTE_EXECUTION_FAIL_AT": "25"}):
            self.step()
            self.step()
        response = self.client.get("/tasks/TASK-A/results")
        self.assertEqual(response.status_code, 200)
        self.assertIn("stopped early", response.text)
        self.assertIn("24", response.text)

    # --- results and the log --------------------------------------------------

    def test_results_show_the_storyboard_numbers(self) -> None:
        self.login()
        self.approve()
        for _ in range(5):
            self.step()
        page = self.client.get("/tasks/TASK-A/results")
        self.assertEqual(page.status_code, 200)
        self.assertIn("99/100", page.text)
        self.assertIn("99.0%", page.text)
        self.assertIn("1 record(s)", page.text)

    def test_the_activity_export_matches_the_page(self) -> None:
        self.login()
        self.approve()
        for _ in range(5):
            self.step()
        page = self.client.get("/tasks/TASK-A/results")
        export = self.client.get("/tasks/TASK-A/activity.json")
        self.assertEqual(export.status_code, 200)
        payload = export.json()
        self.assertEqual(payload["task_id"], "TASK-A")
        self.assertEqual(len(payload["events"]), len(self.event_rows()))
        self.assertEqual(page.text.count('class="log-item"'), len(self.event_rows()))
        self.assertTrue(all("payload" in event for event in payload["events"]))

    # --- guards ---------------------------------------------------------------

    def test_another_operator_cannot_see_or_advance_the_run(self) -> None:
        self.login()
        self.approve()
        self.client.post("/logout", follow_redirects=False)
        self.login("bea@example.com")
        for path in ("/tasks/TASK-A/execution", "/tasks/TASK-A/results",
                     "/tasks/TASK-A/execution.json", "/tasks/TASK-A/activity.json"):
            self.assertEqual(self.client.get(path, follow_redirects=False).status_code, 404, path)
        response = self.client.post(
            "/tasks/TASK-A/execution/step", headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.run_rows()[0]["written_count"], 0)

    def test_anonymous_users_are_sent_to_the_login_page(self) -> None:
        response = self.client.get("/tasks/TASK-A/execution", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")
        response = self.client.get("/tasks/TASK-A/results", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")

    def test_execution_state_endpoint_reports_the_run(self) -> None:
        self.login()
        self.approve()
        self.step()
        response = self.client.get("/tasks/TASK-A/execution.json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual((data["status"], data["written"], data["approved"]),
                         ("executing", 20, 99))
        self.assertEqual(data["progress_pct"], 20)

    def test_the_step_button_works_without_javascript(self) -> None:
        """A plain form post redirects; only the polling client asks for JSON."""
        self.login()
        self.approve()
        response = self.client.post("/tasks/TASK-A/execution/step", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/tasks/TASK-A/execution")
        self.assertEqual(self.run_rows()[0]["written_count"], 20)

    def test_an_admin_can_watch_any_run(self) -> None:
        self.login()
        self.approve()
        with Database(DB_URL) as db:
            create_user(db, name="Admin", email="admin@example.com",
                        password="password123", role="admin", user_id="USR-ADMIN")
        self.client.post("/logout", follow_redirects=False)
        self.login("admin@example.com")
        self.assertEqual(self.client.get("/tasks/TASK-A/execution").status_code, 200)


if __name__ == "__main__":
    unittest.main()
