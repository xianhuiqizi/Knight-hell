"""Sign-up, sign-in, sign-out and the isolation rule the course asks for."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from flowremote.api.app import create_app  # noqa: E402
from flowremote.api.sessions import COOKIE_NAME  # noqa: E402
from flowremote.control_plane.auth import create_user  # noqa: E402
from flowremote.control_plane.db import PROJECT_ROOT, Database  # noqa: E402

DB_PATH = PROJECT_ROOT / "data" / "runtime" / "tests" / "app.db"
DB_URL = f"sqlite:///{DB_PATH.as_posix()}"
TABLES = ("ai_suggestion_items", "ai_suggestion_runs", "activity_events", "execution_runs",
          "decisions", "approvals", "exceptions", "source_records", "ai_settings",
          "tasks", "users")


def seed_task(db: Database, task_id: str, owner: str, workflow: str, batch: int) -> None:
    now = "2026-09-30T14:00:00Z"
    db.execute(
        "INSERT INTO tasks (id, workflow, batch_size, status, source_file, source_location,"
        " primary_target, secondary_target, owner_id, created_at, updated_at)"
        " VALUES (?, ?, ?, 'review_required', 'Orders_September.xlsx', 'Company Workspace',"
        " 'OA', 'BI', ?, ?, ?)",
        (task_id, workflow, batch, owner, now, now),
    )
    for index, (record, status) in enumerate(
        (("ORD-052", "unresolved"), ("ORD-081", "unresolved")), start=1
    ):
        db.execute(
            "INSERT INTO exceptions (id, task_id, record_id, issue, flagged_fields,"
            " original_value, suggestion, confidence, reason, status, created_at)"
            " VALUES (?, ?, ?, 'Missing Customer ID', 'customer_id', '(blank)', 'C-1024',"
            " 0.98, 'why', ?, ?)",
            (f"EXC-{task_id}-{index}", task_id, record, status, now),
        )
    db.execute(
        "INSERT INTO source_records (task_id, record_id, customer_name, customer_id, quantity,"
        " unit_price, amount, order_date, outcome) VALUES (?, 'ORD-001', 'X', 'C-1', 1, 1.0,"
        " 1.0, '2026-09-01', 'passed')",
        (task_id,),
    )


class AuthTests(unittest.TestCase):
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
            create_user(db, name="Ada Admin", email="admin@example.com",
                        password="password123", role="admin", user_id="USR-ADMIN")
            seed_task(db, "TASK-A", "USR-A", "Order Data Validation & Sync", 100)
            seed_task(db, "TASK-B", "USR-B", "Invoice Reconciliation", 40)
        self.client = TestClient(self.app)

    # -- helpers ---------------------------------------------------------
    def login(self, email: str, password: str = "password123"):
        return self.client.post(
            "/login", data={"email": email, "password": password}, follow_redirects=False
        )

    def assert_redirects_to_login(self, response) -> None:
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers.get("location"), "/login")

    # -- anonymous -------------------------------------------------------
    def test_home_requires_a_session(self):
        self.assert_redirects_to_login(self.client.get("/", follow_redirects=False))

    def test_task_page_requires_a_session(self):
        self.assert_redirects_to_login(self.client.get("/tasks/TASK-A", follow_redirects=False))

    def test_login_page_links_the_stylesheet(self):
        page = self.client.get("/login")
        self.assertEqual(page.status_code, 200)
        self.assertIn("/static/app.css", page.text)

    def test_the_stylesheet_is_served(self):
        response = self.client.get("/static/app.css")
        self.assertEqual(response.status_code, 200)
        self.assertIn("--accent", response.text)

    # -- sign in ---------------------------------------------------------
    def test_wrong_password_is_rejected(self):
        response = self.login("alex@example.com", "wrong-password")
        self.assertEqual(response.status_code, 401)
        self.assertIn("do not match", response.text)

    def test_unknown_email_is_rejected(self):
        response = self.login("nobody@example.com")
        self.assertEqual(response.status_code, 401)

    def test_login_sets_a_cookie_and_opens_the_home_page(self):
        response = self.login("alex@example.com")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers.get("location"), "/")
        self.assertIn(COOKIE_NAME, response.cookies)
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("Order Data Validation &amp; Sync", home.text)

    # -- isolation -------------------------------------------------------
    def test_operator_sees_only_their_own_tasks(self):
        self.login("alex@example.com")
        home = self.client.get("/")
        self.assertIn("TASK-A", home.text)
        self.assertNotIn("TASK-B", home.text)
        self.assertNotIn("Invoice Reconciliation", home.text)

    def test_operator_cannot_open_somebody_elses_task(self):
        self.login("alex@example.com")
        self.assertEqual(self.client.get("/tasks/TASK-B").status_code, 404)

    def test_admin_sees_every_task(self):
        self.login("admin@example.com")
        home = self.client.get("/")
        self.assertIn("TASK-A", home.text)
        self.assertIn("TASK-B", home.text)

    def test_task_detail_shows_the_counts(self):
        self.login("alex@example.com")
        page = self.client.get("/tasks/TASK-A")
        self.assertEqual(page.status_code, 200)
        self.assertIn("100", page.text)
        self.assertIn("ORD-052", page.text)
        self.assertIn("Unresolved", page.text)
        self.assertIn("98%", page.text)

    # -- sign out and forged cookies -------------------------------------
    def test_logout_ends_the_session(self):
        self.login("alex@example.com")
        self.assertEqual(self.client.get("/").status_code, 200)
        response = self.client.post("/logout", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assert_redirects_to_login(self.client.get("/", follow_redirects=False))

    def test_a_forged_cookie_is_treated_as_anonymous(self):
        self.client.cookies.set(COOKIE_NAME, "forged.payload")
        self.assert_redirects_to_login(self.client.get("/", follow_redirects=False))

    # -- sign up ---------------------------------------------------------
    def test_signup_creates_the_account_and_signs_in(self):
        response = self.client.post(
            "/signup",
            data={"name": "New Person", "email": "new@example.com",
                  "password": "password123", "password_again": "password123"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("No tasks yet", home.text)

    def test_signup_rejects_a_duplicate_email(self):
        response = self.client.post(
            "/signup",
            data={"name": "Copy Cat", "email": "alex@example.com",
                  "password": "password123", "password_again": "password123"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("already exists", response.text)

    def test_signup_rejects_mismatched_passwords(self):
        response = self.client.post(
            "/signup",
            data={"name": "New Person", "email": "new2@example.com",
                  "password": "password123", "password_again": "password124"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 400)

    def test_signup_rejects_a_short_password(self):
        response = self.client.post(
            "/signup",
            data={"name": "New Person", "email": "new3@example.com",
                  "password": "short", "password_again": "short"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
