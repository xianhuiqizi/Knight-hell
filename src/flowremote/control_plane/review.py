"""The review rules: counting, the approval gate, and building an approval.

These functions are deliberately pure - they take domain objects and return
answers, touching no database and no UI. Three parts of the app need the same
answers (the browser, the API and the tests), so the rule lives here once.

The database enforces the same rules with CHECK and UNIQUE constraints, so a
mistake here cannot silently write bad data. The rules come first because
"can we proceed?" has to be answerable before anything is written.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from flowremote.contracts.enums import DecisionAction, ExceptionStatus
from flowremote.contracts.models import Approval, ExceptionItem, ModelError


class ApprovalBlocked(ModelError):
    """The batch is not allowed to be approved yet."""


class DuplicateApproval(ApprovalBlocked):
    """This attempt was already approved; approving twice would write twice."""


class DecisionRejected(ModelError):
    """The requested review action is not allowed for this exception."""


@dataclass(frozen=True)
class Tally:
    accepted: int
    manual: int
    skipped: int
    unresolved: int

    @property
    def total(self) -> int:
        return self.accepted + self.manual + self.skipped + self.unresolved

    @property
    def ready(self) -> int:
        """Records that would be written if the batch were approved now."""
        return self.accepted + self.manual

    @property
    def reviewed(self) -> int:
        return self.accepted + self.manual + self.skipped

    def as_dict(self) -> dict[str, int]:
        return {
            "accepted": self.accepted,
            "manual": self.manual,
            "skipped": self.skipped,
            "unresolved": self.unresolved,
            "total": self.total,
            "ready": self.ready,
            "reviewed": self.reviewed,
        }


def tally(exceptions: Iterable[ExceptionItem]) -> Tally:
    counts = {status: 0 for status in ExceptionStatus}
    for exception in exceptions:
        counts[exception.status] += 1
    return Tally(
        accepted=counts[ExceptionStatus.ACCEPTED],
        manual=counts[ExceptionStatus.MANUAL],
        skipped=counts[ExceptionStatus.SKIPPED],
        unresolved=counts[ExceptionStatus.UNRESOLVED],
    )


def proceed_enabled(exceptions: Iterable[ExceptionItem]) -> bool:
    """True only when nothing is unresolved - the gate from the storyboard."""
    return tally(exceptions).unresolved == 0


def approved_records(exceptions: Iterable[ExceptionItem]) -> list[ExceptionItem]:
    """The rows that would be written: accepted AI values plus manual values."""
    return [
        exception
        for exception in exceptions
        if exception.status in (ExceptionStatus.ACCEPTED, ExceptionStatus.MANUAL)
    ]


def skipped_records(exceptions: Iterable[ExceptionItem]) -> list[ExceptionItem]:
    return [item for item in exceptions if item.status is ExceptionStatus.SKIPPED]


@dataclass(frozen=True)
class DecisionResult:
    action: DecisionAction
    status: ExceptionStatus
    resolved_value: str | None


def decide(exception: ExceptionItem, action: str, value: str | None) -> DecisionResult:
    """Apply one review action to an exception and return its new state.

    The rules here are the ones the UI must not be able to talk its way around:
    a row can only be resolved once, Accept needs a suggestion to accept, Edit
    needs a value, and Skip carries no value.
    """
    try:
        chosen = DecisionAction(action)
    except ValueError as exc:
        raise DecisionRejected(f"unknown action {action!r}") from exc
    if exception.status is not ExceptionStatus.UNRESOLVED:
        raise DecisionRejected("this exception is already resolved")
    if chosen is DecisionAction.ACCEPT:
        if not exception.suggestion:
            raise DecisionRejected("there is no suggestion to accept")
        return DecisionResult(chosen, ExceptionStatus.ACCEPTED, exception.suggestion)
    if chosen is DecisionAction.EDIT:
        cleaned = (value or "").strip()
        if not cleaned:
            raise DecisionRejected("the new value cannot be empty")
        return DecisionResult(chosen, ExceptionStatus.MANUAL, cleaned)
    return DecisionResult(chosen, ExceptionStatus.SKIPPED, None)


def build_approval(
    *,
    task_id: str,
    exceptions: Sequence[ExceptionItem],
    approver_id: str,
    attempt: int = 1,
    approval_id: str | None = None,
    existing_attempts: Sequence[int] = (),
) -> Approval:
    """Create the approval row, or explain why the batch cannot be approved.

    Three things can stop it: unresolved exceptions, nothing approved, and this
    attempt already being approved. Each raises a specific error so the API can
    return a reason instead of a generic failure.
    """
    counts = tally(exceptions)
    if counts.unresolved:
        raise ApprovalBlocked(
            f"{counts.unresolved} exception(s) are still unresolved; "
            "approval unlocks only when unresolved reaches zero"
        )
    if counts.ready == 0:
        raise ApprovalBlocked("there is nothing approved to write")
    if attempt in set(existing_attempts):
        raise DuplicateApproval(f"attempt {attempt} was already approved for {task_id}")

    return Approval(
        id=approval_id or f"APR-{task_id}-{attempt}",
        task_id=task_id,
        attempt=attempt,
        approver_id=approver_id,
        approved_count=counts.ready,
        skipped_count=counts.skipped,
    )
