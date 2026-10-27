"""The step rules behind Feature 2, and the two new models.

These are the tests that make the progress bar explainable: how many records one
step moves, when a run is allowed to call itself complete, and where a failed
write stops.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from flowremote.contracts.enums import ActorKind, RunState  # noqa: E402
from flowremote.contracts.models import ActivityEvent, ExecutionRun, ModelError  # noqa: E402
from flowremote.rpa.execution import (  # noqa: E402
    STEP_SIZE,
    ExecutionError,
    format_duration,
    next_step,
    success_rate,
)


class NextStepTests(unittest.TestCase):
    def test_default_step_is_twenty_records(self) -> None:
        self.assertEqual(STEP_SIZE, 20)
        outcome = next_step(approved=99, written=0, status=RunState.EXECUTING)
        self.assertEqual(outcome.written, 20)
        self.assertEqual(outcome.status, RunState.EXECUTING)
        self.assertEqual(outcome.advanced, 20)
        self.assertIsNone(outcome.failure)

    def test_last_step_never_passes_the_approved_count(self) -> None:
        outcome = next_step(approved=99, written=80, status=RunState.EXECUTING)
        self.assertEqual(outcome.written, 99)
        self.assertEqual(outcome.status, RunState.COMPLETE)
        self.assertEqual(outcome.advanced, 19)

    def test_a_finished_run_ignores_another_step(self) -> None:
        for state in (RunState.COMPLETE, RunState.PARTIAL):
            outcome = next_step(approved=99, written=42, status=state)
            self.assertEqual(outcome.written, 42)
            self.assertEqual(outcome.status, state)
            self.assertEqual(outcome.advanced, 0)

    def test_a_failure_stops_before_the_failing_record(self) -> None:
        outcome = next_step(approved=99, written=20, status=RunState.EXECUTING, fail_at=25)
        self.assertEqual(outcome.written, 24)
        self.assertEqual(outcome.status, RunState.PARTIAL)
        self.assertEqual(outcome.advanced, 4)
        self.assertIn("record 25", outcome.failure or "")

    def test_a_failure_on_the_first_record_writes_nothing(self) -> None:
        outcome = next_step(approved=10, written=0, status=RunState.EXECUTING, fail_at=1)
        self.assertEqual(outcome.written, 0)
        self.assertEqual(outcome.status, RunState.PARTIAL)

    def test_a_failure_after_the_last_record_does_not_trigger(self) -> None:
        outcome = next_step(approved=40, written=20, status=RunState.EXECUTING, fail_at=500)
        self.assertEqual(outcome.written, 40)
        self.assertEqual(outcome.status, RunState.COMPLETE)

    def test_impossible_inputs_are_rejected(self) -> None:
        with self.assertRaises(ExecutionError):
            next_step(approved=0, written=0, status=RunState.EXECUTING)
        with self.assertRaises(ExecutionError):
            next_step(approved=10, written=11, status=RunState.EXECUTING)
        with self.assertRaises(ExecutionError):
            next_step(approved=10, written=0, status=RunState.EXECUTING, step=0)


class NumbersTests(unittest.TestCase):
    def test_success_rate_is_written_over_input(self) -> None:
        self.assertEqual(f"{success_rate(99, 100):.1f}%", "99.0%")
        self.assertEqual(success_rate(0, 100), 0.0)

    def test_success_rate_needs_a_batch(self) -> None:
        with self.assertRaises(ExecutionError):
            success_rate(1, 0)

    def test_duration_is_readable(self) -> None:
        self.assertEqual(format_duration(None), "-")
        self.assertEqual(format_duration(0), "< 1 s")
        self.assertEqual(format_duration(840), "840 ms")
        self.assertEqual(format_duration(2400), "2.4 s")


class ExecutionRunModelTests(unittest.TestCase):
    def make(self, **overrides):
        values = {
            "id": "RUN-TASK-1",
            "task_id": "TASK-1",
            "attempt": 1,
            "approved_count": 99,
            "written_count": 0,
            "synced_count": 0,
            "status": RunState.EXECUTING,
            "started_at": "2026-10-25T08:00:00Z",
        }
        values.update(overrides)
        return ExecutionRun(**values)

    def test_a_running_run_has_no_finish_time(self) -> None:
        run = self.make()
        self.assertEqual(run.progress_percent, 0)
        self.assertFalse(run.finished)

    def test_progress_and_finished_flags(self) -> None:
        run = self.make(written_count=50, synced_count=50,
                        status=RunState.COMPLETE, finished_at="2026-10-25T08:00:03Z")
        self.assertEqual(run.progress_percent, 51)
        self.assertTrue(run.finished)

    def test_cannot_write_more_than_approved(self) -> None:
        with self.assertRaises(ModelError):
            self.make(written_count=100)

    def test_secondary_cannot_run_ahead(self) -> None:
        with self.assertRaises(ModelError):
            self.make(written_count=10, synced_count=11)

    def test_a_finished_run_needs_a_timestamp(self) -> None:
        with self.assertRaises(ModelError):
            self.make(status=RunState.COMPLETE)

    def test_a_running_run_cannot_carry_a_finish_time(self) -> None:
        with self.assertRaises(ModelError):
            self.make(finished_at="2026-10-25T08:00:03Z")

    def test_status_must_be_known(self) -> None:
        with self.assertRaises(ModelError):
            self.make(status="halfway")


class ActivityEventModelTests(unittest.TestCase):
    def test_actor_kind_is_required_and_checked(self) -> None:
        event = ActivityEvent(
            id="EVT-1", task_id="TASK-1", occurred_at="2026-10-25T08:00:00Z",
            actor="Alex Morgan", actor_kind=ActorKind.USER, kind="exception_decided",
            description="Accepted the suggestion for ORD-052",
        )
        self.assertEqual(event.actor_kind, ActorKind.USER)
        with self.assertRaises(ModelError):
            ActivityEvent(
                id="EVT-2", task_id="TASK-1", occurred_at="2026-10-25T08:00:00Z",
                actor="x", actor_kind="robot", kind="k", description="d",
            )

    def test_description_cannot_be_empty(self) -> None:
        with self.assertRaises(ModelError):
            ActivityEvent(
                id="EVT-3", task_id="TASK-1", occurred_at="2026-10-25T08:00:00Z",
                actor="x", actor_kind=ActorKind.ENGINE, kind="k", description="  ",
            )


if __name__ == "__main__":
    unittest.main()
