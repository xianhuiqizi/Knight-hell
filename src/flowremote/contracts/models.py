"""Domain models for FlowRemote, using the standard library only.

Why dataclasses and not an ORM or Pydantic: this slice has to run on a clean
Python install with nothing installed, so the project cannot depend on a
third-party package yet. These models still do the job a contract has to do:
one place that defines each field, its type, and the rules a value must pass.

When the HTTP layer arrives in P2, Pydantic request/response models will live
in ``api/schemas.py`` and convert into these objects. Keeping transport models
separate from domain models is deliberate: a browser request must not be able
to set a field the domain does not allow.

Every model can be built from a database row with ``from_row``, which keeps the
mapping between the SQL schema and Python in one place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from typing import Any, Mapping

from flowremote.contracts.enums import (
    DecisionAction,
    ExceptionStatus,
    Outcome,
    Role,
    TaskState,
)
from flowremote.contracts.timeutil import utc_now

RECORD_ID_PATTERN = re.compile(r"^ORD-\d{3,5}$")


class ModelError(ValueError):
    """A value does not satisfy the rules of its model."""


def _require_text(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ModelError(f"{name} must be a non-empty string, got {value!r}")


def _coerce(enum_type, value, name: str):
    """Turn a stored string into its enum member, with a readable error."""
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(member.value for member in enum_type)
        raise ModelError(f"{name} must be one of [{allowed}], got {value!r}") from exc


def _row_mapping(row: Any) -> dict[str, Any]:
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return dict(row)


def _pick(model_type, data: dict[str, Any]) -> dict[str, Any]:
    """Keep only the keys the model declares, so extra row columns are ignored."""
    declared = {item.name for item in fields(model_type)}
    return {key: value for key, value in data.items() if key in declared}


@dataclass(frozen=True)
class User:
    id: str
    name: str
    email: str
    role: Role
    device: str | None = None
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _require_text(self.id, "User.id")
        _require_text(self.name, "User.name")
        _require_text(self.email, "User.email")
        if "@" not in self.email:
            raise ModelError(f"User.email looks wrong: {self.email!r}")
        object.__setattr__(self, "role", _coerce(Role, self.role, "User.role"))

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | Any) -> "User":
        return cls(**_pick(cls, _row_mapping(row)))


@dataclass(frozen=True)
class Task:
    id: str
    workflow: str
    batch_size: int
    status: TaskState
    source_file: str
    source_location: str
    primary_target: str
    secondary_target: str
    owner_id: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _require_text(self.id, "Task.id")
        _require_text(self.workflow, "Task.workflow")
        _require_text(self.source_file, "Task.source_file")
        if not isinstance(self.batch_size, int) or self.batch_size <= 0:
            raise ModelError(f"Task.batch_size must be a positive integer, got {self.batch_size!r}")
        object.__setattr__(self, "status", _coerce(TaskState, self.status, "Task.status"))

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | Any) -> "Task":
        return cls(**_pick(cls, _row_mapping(row)))


@dataclass(frozen=True)
class SourceRecord:
    """One row of the input batch, before and after validation."""

    task_id: str
    record_id: str
    customer_name: str | None
    customer_id: str | None
    quantity: int | None
    unit_price: float | None
    amount: float | None
    order_date: str | None
    outcome: Outcome

    def __post_init__(self) -> None:
        if not RECORD_ID_PATTERN.match(self.record_id or ""):
            raise ModelError(
                f"SourceRecord.record_id must look like ORD-001, got {self.record_id!r}"
            )
        outcome = _coerce(Outcome, self.outcome, "SourceRecord.outcome")
        object.__setattr__(self, "outcome", outcome)
        if outcome is Outcome.PASSED:
            missing = [
                name
                for name in ("customer_name", "customer_id", "quantity")
                if getattr(self, name) in (None, "")
            ]
            if missing:
                raise ModelError("a passed record cannot be missing " + ", ".join(missing))
        if self.quantity is not None and self.quantity <= 0:
            raise ModelError("SourceRecord.quantity must be positive when present")

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | Any) -> "SourceRecord":
        return cls(**_pick(cls, _row_mapping(row)))


@dataclass(frozen=True)
class ExceptionItem:
    """One flagged record: what was wrong, what the AI suggests, what we did."""

    id: str
    task_id: str
    record_id: str
    issue: str
    flagged_fields: str
    original_value: str | None
    suggestion: str | None
    confidence: float | None
    reason: str | None
    status: ExceptionStatus
    resolved_value: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _require_text(self.id, "ExceptionItem.id")
        _require_text(self.task_id, "ExceptionItem.task_id")
        if not RECORD_ID_PATTERN.match(self.record_id or ""):
            raise ModelError(
                f"ExceptionItem.record_id must look like ORD-052, got {self.record_id!r}"
            )
        if not self.issue or not self.flagged_fields:
            raise ModelError("ExceptionItem needs an issue and at least one flagged field")
        if self.confidence is not None and not (0.0 <= float(self.confidence) <= 1.0):
            raise ModelError(
                f"ExceptionItem.confidence must be between 0 and 1, got {self.confidence!r}"
            )
        status = _coerce(ExceptionStatus, self.status, "ExceptionItem.status")
        object.__setattr__(self, "status", status)
        if status is ExceptionStatus.UNRESOLVED:
            if self.resolved_value is not None:
                raise ModelError("an unresolved exception cannot carry a resolved value")
            if self.reviewed_by is not None:
                raise ModelError("an unresolved exception cannot name a reviewer")
        if status in (ExceptionStatus.ACCEPTED, ExceptionStatus.MANUAL):
            if not self.resolved_value:
                raise ModelError(f"a {status.value} exception needs a resolved value")
            if not self.reviewed_by:
                raise ModelError(f"a {status.value} exception needs to record who decided")
        if status is ExceptionStatus.SKIPPED and self.resolved_value is not None:
            raise ModelError("a skipped exception must not carry a resolved value")

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | Any) -> "ExceptionItem":
        return cls(**_pick(cls, _row_mapping(row)))


@dataclass(frozen=True)
class Decision:
    """One append-only record of a review action."""

    id: str
    exception_id: str
    decision_id: str
    action: DecisionAction
    new_value: str | None
    by_user: str
    decided_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _require_text(self.id, "Decision.id")
        _require_text(self.exception_id, "Decision.exception_id")
        _require_text(self.decision_id, "Decision.decision_id")
        _require_text(self.by_user, "Decision.by_user")
        action = _coerce(DecisionAction, self.action, "Decision.action")
        object.__setattr__(self, "action", action)
        if action is DecisionAction.EDIT and not self.new_value:
            raise ModelError("an edit decision must carry the new value")
        if action is DecisionAction.SKIP and self.new_value is not None:
            raise ModelError("a skip decision must not carry a value")

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | Any) -> "Decision":
        return cls(**_pick(cls, _row_mapping(row)))


@dataclass(frozen=True)
class Approval:
    """One authorisation. The database allows only one per task attempt."""

    id: str
    task_id: str
    attempt: int
    approver_id: str
    approved_count: int
    skipped_count: int
    approved_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _require_text(self.id, "Approval.id")
        _require_text(self.task_id, "Approval.task_id")
        _require_text(self.approver_id, "Approval.approver_id")
        if not isinstance(self.attempt, int) or self.attempt <= 0:
            raise ModelError(f"Approval.attempt must be a positive integer, got {self.attempt!r}")
        if not isinstance(self.approved_count, int) or self.approved_count <= 0:
            raise ModelError("Approval.approved_count must be greater than zero")
        if not isinstance(self.skipped_count, int) or self.skipped_count < 0:
            raise ModelError("Approval.skipped_count cannot be negative")

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | Any) -> "Approval":
        return cls(**_pick(cls, _row_mapping(row)))
