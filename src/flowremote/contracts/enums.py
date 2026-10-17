"""The fixed vocabularies of FlowRemote.

Every one of these was a Select field on the paper data model. Defining them
once, here, means the database CHECK constraint, the domain models, the future
API and the browser all use the same strings. Values are stored in lower case
with underscores; the UI turns them into "Review required" style labels.
"""

from __future__ import annotations

from enum import StrEnum


class TaskState(StrEnum):
    """Where one run of a workflow currently is."""

    READY = "ready"
    VALIDATING = "validating"
    REVIEW_REQUIRED = "review_required"
    PENDING_APPROVAL = "pending_approval"
    EXECUTING = "executing"
    COMPLETE = "complete"


class ExceptionStatus(StrEnum):
    """How one flagged record has been resolved, if at all."""

    UNRESOLVED = "unresolved"
    ACCEPTED = "accepted"
    MANUAL = "manual"
    SKIPPED = "skipped"


class DecisionAction(StrEnum):
    """The only three things a reviewer can do to an exception."""

    ACCEPT = "accept"
    EDIT = "edit"
    SKIP = "skip"


class Role(StrEnum):
    OPERATOR = "operator"
    ADMIN = "admin"


class Outcome(StrEnum):
    """How one source record came out of validation."""

    PASSED = "passed"
    FLAGGED = "flagged"
