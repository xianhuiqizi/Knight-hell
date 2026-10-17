"""The domain models must reject bad values before they reach the database."""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from flowremote.contracts.enums import (  # noqa: E402
    DecisionAction,
    ExceptionStatus,
    Outcome,
    TaskState,
)
from flowremote.contracts.models import (  # noqa: E402
    Approval,
    Decision,
    ExceptionItem,
    ModelError,
    SourceRecord,
    Task,
    User,
)


def exception(**overrides):
    data = dict(
        id="EXC-0001",
        task_id="TASK-1001",
        record_id="ORD-052",
        issue="Missing Customer ID",
        flagged_fields="customer_id",
        original_value="(blank)",
        suggestion="C-1024",
        confidence=0.98,
        reason="AI unique match from customer registry.",
        status=ExceptionStatus.UNRESOLVED,
    )
    data.update(overrides)
    return ExceptionItem(**data)


class TaskTests(unittest.TestCase):
    def test_accepts_a_normal_batch(self):
        task = Task(
            id="TASK-1001",
            workflow="Order Data Validation & Sync",
            batch_size=100,
            status=TaskState.REVIEW_REQUIRED,
            source_file="Orders_September.xlsx",
            source_location="Company Workspace",
            primary_target="OA",
            secondary_target="BI",
        )
        self.assertIs(task.status, TaskState.REVIEW_REQUIRED)

    def test_coerces_a_stored_string_into_the_enum(self):
        task = Task(
            id="TASK-1001",
            workflow="w",
            batch_size=1,
            status="review_required",
            source_file="f",
            source_location="l",
            primary_target="a",
            secondary_target="b",
        )
        self.assertIs(task.status, TaskState.REVIEW_REQUIRED)

    def test_rejects_an_unknown_status(self):
        with self.assertRaises(ModelError):
            Task(
                id="TASK-1001",
                workflow="w",
                batch_size=1,
                status="almost_done",
                source_file="f",
                source_location="l",
                primary_target="a",
                secondary_target="b",
            )

    def test_rejects_a_zero_batch(self):
        with self.assertRaises(ModelError):
            Task(
                id="TASK-1001",
                workflow="w",
                batch_size=0,
                status=TaskState.READY,
                source_file="f",
                source_location="l",
                primary_target="a",
                secondary_target="b",
            )


class ExceptionTests(unittest.TestCase):
    def test_rejects_a_record_id_that_is_not_the_expected_shape(self):
        with self.assertRaises(ModelError):
            exception(record_id="52")

    def test_rejects_confidence_above_one(self):
        with self.assertRaises(ModelError):
            exception(confidence=1.4)

    def test_allows_a_missing_suggestion(self):
        item = exception(suggestion=None, confidence=None)
        self.assertIsNone(item.suggestion)

    def test_unresolved_cannot_carry_a_value(self):
        with self.assertRaises(ModelError):
            exception(resolved_value="C-1024")

    def test_manual_needs_a_value_and_a_reviewer(self):
        with self.assertRaises(ModelError):
            exception(status=ExceptionStatus.MANUAL, resolved_value=None, reviewed_by="USR-1")
        with self.assertRaises(ModelError):
            exception(status=ExceptionStatus.MANUAL, resolved_value="6", reviewed_by=None)

    def test_accepted_needs_a_value(self):
        with self.assertRaises(ModelError):
            exception(status=ExceptionStatus.ACCEPTED, reviewed_by="USR-1")

    def test_skipped_must_not_carry_a_value(self):
        with self.assertRaises(ModelError):
            exception(status=ExceptionStatus.SKIPPED, resolved_value="x", reviewed_by="USR-1")

    def test_builds_from_a_sqlite_row(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute(
            "CREATE TABLE e (id TEXT, task_id TEXT, record_id TEXT, issue TEXT,"
            " flagged_fields TEXT, original_value TEXT, suggestion TEXT, confidence REAL,"
            " reason TEXT, status TEXT, resolved_value TEXT, reviewed_by TEXT,"
            " reviewed_at TEXT, created_at TEXT)"
        )
        connection.execute(
            "INSERT INTO e VALUES ('EXC-1','TASK-1001','ORD-052','Missing Customer ID',"
            "'customer_id','(blank)','C-1024',0.98,'why','unresolved',NULL,NULL,NULL,"
            "'2026-09-30T14:31:00Z')"
        )
        row = connection.execute("SELECT * FROM e").fetchone()
        item = ExceptionItem.from_row(row)
        self.assertIs(item.status, ExceptionStatus.UNRESOLVED)
        self.assertEqual(item.record_id, "ORD-052")


class DecisionTests(unittest.TestCase):
    def test_edit_requires_a_value(self):
        with self.assertRaises(ModelError):
            Decision(
                id="D1", exception_id="E1", decision_id="K1",
                action=DecisionAction.EDIT, new_value=None, by_user="USR-1",
            )

    def test_skip_rejects_a_value(self):
        with self.assertRaises(ModelError):
            Decision(
                id="D1", exception_id="E1", decision_id="K1",
                action=DecisionAction.SKIP, new_value="6", by_user="USR-1",
            )

    def test_accept_may_carry_the_value(self):
        decision = Decision(
            id="D1", exception_id="E1", decision_id="K1",
            action="accept", new_value="C-1024", by_user="USR-1",
        )
        self.assertIs(decision.action, DecisionAction.ACCEPT)


class ApprovalTests(unittest.TestCase):
    def test_rejects_zero_approved(self):
        with self.assertRaises(ModelError):
            Approval(
                id="A1", task_id="TASK-1001", attempt=1, approver_id="USR-1",
                approved_count=0, skipped_count=1,
            )

    def test_rejects_negative_skipped(self):
        with self.assertRaises(ModelError):
            Approval(
                id="A1", task_id="TASK-1001", attempt=1, approver_id="USR-1",
                approved_count=99, skipped_count=-1,
            )


class SourceRecordTests(unittest.TestCase):
    def test_flagged_row_may_be_missing_fields(self):
        record = SourceRecord(
            task_id="TASK-1001", record_id="ORD-081", customer_name="Nora Ali",
            customer_id="C-1022", quantity=None, unit_price=10.0, amount=None,
            order_date="2026-09-12", outcome="flagged",
        )
        self.assertIs(record.outcome, Outcome.FLAGGED)

    def test_passed_row_must_be_complete(self):
        with self.assertRaises(ModelError):
            SourceRecord(
                task_id="TASK-1001", record_id="ORD-001", customer_name="Nora Ali",
                customer_id=None, quantity=3, unit_price=10.0, amount=30.0,
                order_date="2026-09-12", outcome="passed",
            )


class UserTests(unittest.TestCase):
    def test_rejects_a_bad_email(self):
        with self.assertRaises(ModelError):
            User(id="USR-1", name="Alex", email="alex", role="operator")


if __name__ == "__main__":
    unittest.main()
