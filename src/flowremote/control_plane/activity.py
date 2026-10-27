"""The append-only activity log (BR-10).

Every meaningful state change writes exactly one row here, in the same
transaction as the change itself: a decision that is written but not logged, or
logged but not written, would make the audit trail lie. Nothing in the project
updates or deletes an event.

``actor_kind`` separates people from the engine. The simulated execution writes
its own events with ``ActorKind.ENGINE`` so a reader never has to guess whether
a human pressed something.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from flowremote.contracts.enums import ActorKind
from flowremote.control_plane.db import Database, new_id, utc_now

ENGINE_NAME = "RPA Execution Engine"
VALIDATOR_NAME = "FlowRemote Engine"


def log_event(
    db: Database,
    *,
    task_id: str,
    kind: str,
    description: str,
    actor: str,
    actor_kind: ActorKind | str = ActorKind.USER,
    run_id: str | None = None,
    occurred_at: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> str:
    """Append one event and return its id. Call inside the caller's transaction."""
    event_id = new_id("EVT")
    db.execute(
        "INSERT INTO activity_events (id, task_id, run_id, occurred_at, actor, actor_kind,"
        " kind, description, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event_id,
            task_id,
            run_id,
            occurred_at or utc_now(),
            actor,
            str(actor_kind),
            kind,
            description,
            json.dumps(dict(payload or {}), ensure_ascii=False, sort_keys=True),
        ),
    )
    return event_id


def recent_events(db: Database, task_id: str, limit: int = 100) -> list[dict]:
    """Newest first, which is how the results page reads."""
    return db.query(
        "SELECT id, run_id, occurred_at, actor, actor_kind, kind, description, payload_json"
        " FROM activity_events WHERE task_id = ?"
        " ORDER BY occurred_at DESC, id DESC LIMIT ?",
        (task_id, limit),
    )
