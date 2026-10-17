"""The database must enforce the same rules as the domain models."""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from flowremote.control_plane.db import Database  # noqa: E402


class SchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        # In memory: every test starts with an empty schema and nothing touches the disk.
        self.db = Database("sqlite:///:memory:").connect()
        self.addCleanup(self.db.close)
        self.db.apply_migrations()
        self.db.execute(
            "INSERT INTO users (id, name, email, role, created_at)"
            " VALUES ('USR-1', 'Alex', 'alex@example.com', 'operator', '2026-09-30T14:00:00Z')"
        )
        self.db.execute(
            "INSERT INTO tasks (id, workflow, batch_size, status, source_file, source_location,"
            " primary_target, secondary_target, owner_id, created_at, updated_at)"
            " VALUES ('TASK-1001', 'Flow', 100, 'review_required', 'Orders_September.xlsx',"
            " 'Company Workspace', 'OA', 'BI', 'USR-1', '2026-09-30T14:00:00Z',"
            " '2026-09-30T14:00:00Z')"
        )

    def add_exception(self, record_id: str = "ORD-052", status: str = "unresolved") -> None:
        self.db.execute(
            "INSERT INTO exceptions (id, task_id, record_id, issue, flagged_fields,"
            " original_value, suggestion, confidence, reason, status, created_at)"
            " VALUES (?, 'TASK-1001', ?, 'Missing Customer ID', 'customer_id', '(blank)',"
            " 'C-1024', 0.98, 'why', ?, '2026-09-30T14:00:00Z')",
            (f"EXC-{record_id}", record_id, status),
        )

    def test_schema_version_is_recorded(self):
        versions = [row["version"] for row in self.db.query("SELECT version FROM schema_version")]
        self.assertIn("0001_init", versions)

    def test_rejects_an_unknown_exception_status(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.add_exception(status="almost_done")

    def test_rejects_a_duplicate_approval_for_one_attempt(self):
        sql = (
            "INSERT INTO approvals (id, task_id, attempt, approver_id, approved_count,"
            " skipped_count, approved_at) VALUES (?, 'TASK-1001', 1, 'USR-1', 11, 1,"
            " '2026-09-30T14:32:00Z')"
        )
        self.db.execute(sql, ("APR-1",))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(sql, ("APR-2",))

    def test_rejects_two_decisions_with_the_same_idempotency_key(self):
        self.add_exception()
        exception_id = self.db.scalar("SELECT id FROM exceptions LIMIT 1")
        sql = (
            "INSERT INTO decisions (id, exception_id, decision_id, action, new_value,"
            " by_user, decided_at) VALUES (?, ?, 'K-1', 'accept', 'C-1024', 'USR-1',"
            " '2026-09-30T14:31:00Z')"
        )
        self.db.execute(sql, ("D-1", exception_id))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(sql, ("D-2", exception_id))

    def test_rejects_a_child_row_for_an_unknown_task(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "INSERT INTO exceptions (id, task_id, record_id, issue, flagged_fields,"
                " original_value, suggestion, confidence, reason, status, created_at)"
                " VALUES ('EXC-x', 'TASK-NOPE', 'ORD-999', 'issue', 'customer_id', NULL,"
                " NULL, NULL, NULL, 'unresolved', '2026-09-30T14:00:00Z')"
            )

    def test_the_gate_query_counts_unresolved_rows(self):
        self.add_exception("ORD-052")
        self.add_exception("ORD-081")
        self.add_exception("ORD-099", status="skipped")
        unresolved = self.db.scalar(
            "SELECT COUNT(*) FROM exceptions WHERE task_id = 'TASK-1001'"
            " AND status = 'unresolved'"
        )
        self.assertEqual(unresolved, 2)


if __name__ == "__main__":
    unittest.main()
