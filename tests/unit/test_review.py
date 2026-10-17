"""The tally and the approval gate: the rules the UI depends on."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from flowremote.contracts.enums import ExceptionStatus  # noqa: E402
from flowremote.contracts.models import ExceptionItem  # noqa: E402
from flowremote.control_plane.review import (  # noqa: E402
    ApprovalBlocked,
    DecisionRejected,
    DuplicateApproval,
    approved_records,
    build_approval,
    decide,
    proceed_enabled,
    skipped_records,
    tally,
)
from dataclasses import replace  # noqa: E402


def make(number: int, status: ExceptionStatus, value: str | None = None) -> ExceptionItem:
    return ExceptionItem(
        id=f"EXC-{number:04d}",
        task_id="TASK-1001",
        record_id=f"ORD-{number:03d}",
        issue="Missing Customer ID",
        flagged_fields="customer_id",
        original_value="(blank)",
        suggestion="C-1024",
        confidence=0.98,
        reason="AI unique match from customer registry.",
        status=status,
        resolved_value=value,
        reviewed_by="USR-0001" if status is not ExceptionStatus.UNRESOLVED else None,
    )


def storyboard_reviewed() -> list[ExceptionItem]:
    """12 exceptions after review: 8 accepted, 3 manual, 1 skipped."""
    items = [make(n, ExceptionStatus.ACCEPTED, "C-1024") for n in range(1, 9)]
    items += [make(n, ExceptionStatus.MANUAL, "6") for n in range(9, 12)]
    items += [make(12, ExceptionStatus.SKIPPED)]
    return items


class TallyTests(unittest.TestCase):
    def test_empty_batch(self):
        counts = tally([])
        self.assertEqual(
            (counts.accepted, counts.manual, counts.skipped, counts.unresolved), (0, 0, 0, 0)
        )
        self.assertEqual(counts.total, 0)

    def test_unreviewed_batch(self):
        items = [make(n, ExceptionStatus.UNRESOLVED) for n in range(1, 13)]
        counts = tally(items)
        self.assertEqual(counts.unresolved, 12)
        self.assertEqual(counts.reviewed, 0)
        self.assertEqual(counts.total, 12)

    def test_reviewed_batch_matches_the_storyboard(self):
        counts = tally(storyboard_reviewed())
        self.assertEqual(counts.accepted, 8)
        self.assertEqual(counts.manual, 3)
        self.assertEqual(counts.skipped, 1)
        self.assertEqual(counts.unresolved, 0)
        self.assertEqual(counts.ready, 11)
        self.assertEqual(counts.total, 12)

    def test_tally_is_the_sum_of_its_parts(self):
        counts = tally(storyboard_reviewed())
        self.assertEqual(counts.reviewed + counts.unresolved, counts.total)


class GateTests(unittest.TestCase):
    def test_blocked_while_anything_is_unresolved(self):
        items = storyboard_reviewed()[:11] + [make(12, ExceptionStatus.UNRESOLVED)]
        self.assertFalse(proceed_enabled(items))

    def test_enabled_when_everything_is_reviewed(self):
        self.assertTrue(proceed_enabled(storyboard_reviewed()))

    def test_ready_and_skipped_sets_are_disjoint(self):
        items = storyboard_reviewed()
        ready = {item.record_id for item in approved_records(items)}
        skipped = {item.record_id for item in skipped_records(items)}
        self.assertEqual(len(ready), 11)
        self.assertEqual(len(skipped), 1)
        self.assertFalse(ready & skipped)


class ApprovalTests(unittest.TestCase):
    def test_refuses_while_unresolved(self):
        items = [make(n, ExceptionStatus.UNRESOLVED) for n in range(1, 13)]
        with self.assertRaises(ApprovalBlocked) as context:
            build_approval(task_id="TASK-1001", exceptions=items, approver_id="USR-0001")
        self.assertIn("unresolved", str(context.exception).lower())

    def test_refuses_when_nothing_is_approved(self):
        items = [make(1, ExceptionStatus.SKIPPED), make(2, ExceptionStatus.SKIPPED)]
        with self.assertRaises(ApprovalBlocked):
            build_approval(task_id="TASK-1001", exceptions=items, approver_id="USR-0001")

    def test_builds_the_counts_from_the_tally(self):
        approval = build_approval(
            task_id="TASK-1001", exceptions=storyboard_reviewed(), approver_id="USR-0001"
        )
        self.assertEqual(approval.approved_count, 11)
        self.assertEqual(approval.skipped_count, 1)
        self.assertEqual(approval.attempt, 1)
        self.assertEqual(approval.task_id, "TASK-1001")

    def test_refuses_a_second_approval_for_the_same_attempt(self):
        with self.assertRaises(DuplicateApproval):
            build_approval(
                task_id="TASK-1001",
                exceptions=storyboard_reviewed(),
                approver_id="USR-0001",
                attempt=1,
                existing_attempts=[1],
            )

    def test_allows_the_next_attempt(self):
        approval = build_approval(
            task_id="TASK-1001",
            exceptions=storyboard_reviewed(),
            approver_id="USR-0001",
            attempt=2,
            existing_attempts=[1],
        )
        self.assertEqual(approval.attempt, 2)


class DecisionRuleTests(unittest.TestCase):
    def test_accept_keeps_the_suggestion(self):
        result = decide(make(1, ExceptionStatus.UNRESOLVED), "accept", None)
        self.assertIs(result.status, ExceptionStatus.ACCEPTED)
        self.assertEqual(result.resolved_value, "C-1024")

    def test_edit_uses_the_operator_value(self):
        result = decide(make(2, ExceptionStatus.UNRESOLVED), "edit", "6")
        self.assertIs(result.status, ExceptionStatus.MANUAL)
        self.assertEqual(result.resolved_value, "6")

    def test_skip_never_carries_a_value(self):
        result = decide(make(3, ExceptionStatus.UNRESOLVED), "skip", "ignored")
        self.assertIs(result.status, ExceptionStatus.SKIPPED)
        self.assertIsNone(result.resolved_value)

    def test_accept_without_a_suggestion_is_rejected(self):
        item = replace(make(4, ExceptionStatus.UNRESOLVED), suggestion=None, confidence=None)
        with self.assertRaises(DecisionRejected):
            decide(item, "accept", None)

    def test_edit_needs_a_value(self):
        with self.assertRaises(DecisionRejected):
            decide(make(5, ExceptionStatus.UNRESOLVED), "edit", "   ")

    def test_an_action_must_be_known(self):
        with self.assertRaises(DecisionRejected):
            decide(make(6, ExceptionStatus.UNRESOLVED), "approve", None)

    def test_a_resolved_row_cannot_be_decided_again(self):
        with self.assertRaises(DecisionRejected):
            decide(make(7, ExceptionStatus.ACCEPTED, "C-1024"), "skip", None)


if __name__ == "__main__":
    unittest.main()
