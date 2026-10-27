"""The execution step (Feature 2).

The engine moves a run forward in bounded steps instead of finishing in one
request. That keeps progress observable in the browser and makes the stopping
point of a failed write reproducible in a test.

This is a **simulated** execution: it writes to no OA, no BI and no network. The
counts it produces are real database state, the outward writes are not. Every
piece of user-facing text that mentions the targets says "simulated".
"""

from __future__ import annotations

from dataclasses import dataclass

from flowremote.contracts.enums import RunState
from flowremote.contracts.models import ModelError

#: Records advanced per request. Small enough to see progress, large enough to
#: finish a 99-record batch in five steps.
STEP_SIZE = 20


class ExecutionError(ModelError):
    """A step was asked for a run that cannot take one."""


@dataclass(frozen=True)
class StepOutcome:
    """What one step did: where the run got to and whether it stopped early."""

    written: int
    status: RunState
    failure: str | None = None
    advanced: int = 0


def next_step(
    *,
    approved: int,
    written: int,
    status: RunState | str,
    step: int = STEP_SIZE,
    fail_at: int | None = None,
) -> StepOutcome:
    """Advance one run by at most ``step`` records.

    ``fail_at`` is the 1-based record number that fails to write, used to show
    the partial-failure path. The run stops at the record before it, so a
    failure never reports a record as written when it was not.
    """
    if not isinstance(approved, int) or approved <= 0:
        raise ExecutionError(f"approved count must be positive, got {approved!r}")
    if not isinstance(written, int) or written < 0 or written > approved:
        raise ExecutionError(f"written count {written!r} is outside 0..{approved}")
    if step < 1:
        raise ExecutionError("step must be at least one record")
    state = RunState(status) if not isinstance(status, RunState) else status

    if state is not RunState.EXECUTING:
        # Pressing the button again on a finished run changes nothing.
        return StepOutcome(written=written, status=state)

    target = min(approved, written + step)
    if fail_at is not None and written < fail_at <= target:
        stopped = max(written, fail_at - 1)
        return StepOutcome(
            written=stopped,
            status=RunState.PARTIAL,
            failure=(
                f"record {fail_at} could not be written; the run stopped after {stopped}"
                f" of {approved}"
            ),
            advanced=stopped - written,
        )

    return StepOutcome(
        written=target,
        status=RunState.COMPLETE if target >= approved else RunState.EXECUTING,
        advanced=target - written,
    )


def success_rate(written: int, batch_size: int) -> float:
    """Written records over input records, the storyboard's 99/100 = 99.0%."""
    if batch_size <= 0:
        raise ExecutionError("batch size must be positive")
    return 100.0 * written / batch_size


def format_duration(duration_ms: int | None) -> str:
    """A duration a person can read: < 1 s, 840 ms, 2.4 s.

    The timestamps are second-precision on purpose, so a run that starts and
    finishes inside the same second is honestly reported as "under one second"
    rather than as a suspicious "0 ms".
    """
    if duration_ms is None:
        return "-"
    if duration_ms < 1:
        return "< 1 s"
    if duration_ms < 1000:
        return f"{duration_ms} ms"
    return f"{duration_ms / 1000:.1f} s"
