"""Validated, auditable AI suggestion orchestration."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flowremote.agent.providers import (
    CustomerCandidate,
    ProviderError,
    SuggestedChange,
    SuggestionProvider,
    SuggestionRequest,
    SuggestionResponse,
)
from flowremote.contracts.enums import ActorKind, SuggestionState
from flowremote.contracts.models import ExceptionItem, SuggestionRun
from flowremote.control_plane.activity import ENGINE_NAME, log_event
from flowremote.control_plane.db import PROJECT_ROOT, Database, new_id
from flowremote.control_plane.order_validation import (
    FIELDS,
    validate_order,
    validate_proposed_changes,
)

MIN_ACCEPT_CONFIDENCE = 0.70
DEFAULT_REGISTRY = PROJECT_ROOT / "data" / "seed" / "customer_registry.csv"


class SuggestionError(ValueError):
    """A suggestion request is not allowed or cannot be represented safely."""


def _suggestion_now() -> str:
    """Suggestion ordering needs sub-second precision for rapid regenerations."""
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _normal_text(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def load_registry(path: Path | None = None) -> list[CustomerCandidate]:
    target = path or Path(os.environ.get("FLOWREMOTE_CUSTOMER_REGISTRY", DEFAULT_REGISTRY))
    if not target.exists():
        return []
    candidates: list[CustomerCandidate] = []
    with target.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            customer_id = str(row.get("customer_id") or "").strip()
            customer_name = str(row.get("customer_name") or "").strip()
            if customer_id and customer_name:
                candidates.append(
                    CustomerCandidate(
                        customer_id=customer_id,
                        customer_name=customer_name,
                        region=str(row.get("region") or "").strip(),
                        tier=str(row.get("tier") or "").strip(),
                    )
                )
    return candidates


def _matching_candidates(
    current: dict[str, str], registry: list[CustomerCandidate]
) -> tuple[CustomerCandidate, ...]:
    name = _normal_text(current.get("customer_name"))
    customer_id = str(current.get("customer_id") or "").strip()
    if customer_id:
        matches = [candidate for candidate in registry if candidate.customer_id == customer_id]
    elif name:
        matches = [
            candidate
            for candidate in registry
            if _normal_text(candidate.customer_name) == name
        ]
    else:
        matches = []
    return tuple(matches[:8])


def _exception_model(db: Database, task_id: str, record_id: str) -> ExceptionItem:
    rows = db.query(
        "SELECT * FROM exceptions WHERE task_id = ? AND record_id = ?",
        (task_id, record_id),
    )
    if not rows:
        raise SuggestionError("exception not found")
    return ExceptionItem.from_row(rows[0])


def _request_for(
    db: Database,
    exception: ExceptionItem,
    registry_path: Path | None,
) -> SuggestionRequest:
    order_rows = db.query(
        "SELECT current_json, issues_json FROM order_inputs"
        " WHERE task_id = ? AND record_id = ?",
        (exception.task_id, exception.record_id),
    )
    if order_rows:
        current = json.loads(order_rows[0]["current_json"])
        issues = json.loads(order_rows[0]["issues_json"])
        issue_codes = tuple(
            dict.fromkeys(str(issue.get("code") or "") for issue in issues if issue.get("code"))
        )
    else:
        source = db.query(
            "SELECT customer_name, customer_id, quantity, unit_price, amount, order_date"
            " FROM source_records WHERE task_id = ? AND record_id = ?",
            (exception.task_id, exception.record_id),
        )
        if not source:
            raise SuggestionError("source record not found")
        current = {
            field: "" if source[0].get(field) is None else str(source[0][field])
            for field in FIELDS
        }
        current["order_id"] = exception.record_id
        issue_codes = tuple(
            item.strip() for item in exception.issue.split(";") if item.strip()
        )
    current = {field: str(current.get(field, "")) for field in FIELDS}
    flagged = tuple(
        field.strip() for field in exception.flagged_fields.split(",") if field.strip()
    )
    return SuggestionRequest(
        task_id=exception.task_id,
        record_id=exception.record_id,
        issue_codes=issue_codes,
        flagged_fields=flagged,
        current_values=current,
        candidates=_matching_candidates(current, load_registry(registry_path)),
    )


def _run_row(db: Database, run_id: str) -> SuggestionRun:
    rows = db.query("SELECT * FROM ai_suggestion_runs WHERE id = ?", (run_id,))
    if not rows:
        raise SuggestionError("suggestion run not found")
    return SuggestionRun.from_row(rows[0])


def _validate_changes(
    db: Database,
    request: SuggestionRequest,
    changes: list[SuggestedChange],
) -> list[dict[str, Any]]:
    proposed = dict(request.current_values)
    proposed.update({change.field: change.value for change in changes})
    has_uploaded_order = db.scalar(
        "SELECT 1 FROM order_inputs WHERE task_id = ? AND record_id = ?",
        (request.task_id, request.record_id),
    )
    if has_uploaded_order:
        _, _, issues = validate_proposed_changes(
            db,
            request.task_id,
            request.record_id,
            {change.field: change.value for change in changes},
        )
        return issues
    issues, _, _ = validate_order(proposed, {proposed["order_id"]: 1})
    return issues


def _existing_run(
    db: Database, exception_id: str, request_id: str
) -> SuggestionRun | None:
    rows = db.query(
        "SELECT * FROM ai_suggestion_runs WHERE exception_id = ? AND request_id = ?",
        (exception_id, request_id),
    )
    return SuggestionRun.from_row(rows[0]) if rows else None


def _sanitise_changes(
    response: SuggestionResponse, request: SuggestionRequest
) -> list[SuggestedChange]:
    required = set(request.flagged_fields)
    allowed_fields = {field for field in FIELDS if field in required}
    candidate_ids = {candidate.customer_id for candidate in request.candidates}
    candidate_names = {candidate.customer_name for candidate in request.candidates}
    changes: list[SuggestedChange] = []
    seen: set[str] = set()

    for item in response.changes:
        field = item.field.strip()
        value = item.value.strip()
        reason = item.reason.strip()
        if field not in allowed_fields or field in seen or not value or not reason:
            continue
        if len(value) > 500 or not 0.0 <= float(item.confidence) <= 1.0:
            continue
        if field == "customer_id" and (
            len(request.candidates) != 1 or value not in candidate_ids
        ):
            continue
        if field == "customer_name" and (
            len(request.candidates) != 1 or value not in candidate_names
        ):
            continue
        evidence = tuple(
            dict.fromkeys(
                text[:240]
                for text in item.evidence
                if isinstance(text, str) and text.strip()
            )
        )[:10]
        if field in ("customer_id", "customer_name"):
            candidate = request.candidates[0]
            evidence = tuple(
                dict.fromkeys(
                    (
                        f"customer_registry:{candidate.customer_id}",
                        f"server-verified exact match: {candidate.customer_name}",
                    )
                    + evidence
                )
            )[:10]
        seen.add(field)
        changes.append(
            SuggestedChange(
                field=field,
                value=value,
                confidence=float(item.confidence),
                reason=reason[:1000],
                evidence=evidence,
            )
        )
    return changes


def is_actionable(fields: set[str], items: list[dict[str, Any]]) -> bool:
    available = {item["field"]: item for item in items}
    return bool(fields) and fields.issubset(available) and all(
        float(available[field]["confidence"]) >= MIN_ACCEPT_CONFIDENCE for field in fields
    )


def run_suggestion(
    db: Database,
    *,
    task_id: str,
    record_id: str,
    request_id: str,
    provider: SuggestionProvider,
    registry_path: Path | None = None,
) -> SuggestionRun:
    """Run one provider request and persist its validated result.

    The provider call happens between two short transactions. No database lock
    is held during a network request.
    """
    request_id = request_id.strip()
    if not request_id or len(request_id) > 100:
        raise SuggestionError("a valid suggestion request id is required")
    task = db.query("SELECT status FROM tasks WHERE id = ?", (task_id,))
    if not task:
        raise SuggestionError("task not found")
    if task[0]["status"] != "review_required":
        raise SuggestionError("AI suggestions are available only while the task is under review")
    exception = _exception_model(db, task_id, record_id)
    if exception.status.value != "unresolved":
        raise SuggestionError("this exception is already resolved")
    existing = _existing_run(db, exception.id, request_id)
    if existing:
        return existing

    request = _request_for(db, exception, registry_path)
    input_text = json.dumps(
        {
            "issue_codes": request.issue_codes,
            "flagged_fields": request.flagged_fields,
            "current_values": request.current_values,
            "candidates": [candidate.customer_id for candidate in request.candidates],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    input_hash = hashlib.sha256(input_text.encode("utf-8")).hexdigest()
    run_id = new_id("AIS")
    created_at = _suggestion_now()
    provider_name = getattr(provider, "name", provider.__class__.__name__)
    provider_model = getattr(provider, "model", None)
    prompt_version = getattr(provider, "prompt_version", "suggestions-v1")
    try:
        with db.transaction():
            db.execute(
                "INSERT INTO ai_suggestion_runs (id, task_id, exception_id, request_id,"
                " status, provider, model, prompt_version, input_hash, created_at)"
                " VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)",
                (
                    run_id,
                    task_id,
                    exception.id,
                    request_id,
                    provider_name,
                    provider_model,
                    prompt_version,
                    input_hash,
                    created_at,
                ),
            )
    except Exception:
        # A simultaneous double-click can lose the UNIQUE race. The first
        # request owns the run, so return it instead of surfacing a 500.
        existing = _existing_run(db, exception.id, request_id)
        if existing:
            return existing
        raise

    started = time.perf_counter()
    response: SuggestionResponse | None = None
    error_code: str | None = None
    error_message: str | None = None
    try:
        response = provider.suggest(request)
    except ProviderError as exc:
        error_code = "provider_error"
        error_message = str(exc)
    except Exception:  # noqa: BLE001 - provider libraries raise different exceptions.
        error_code = "provider_failure"
        error_message = "The AI provider failed without returning a usable suggestion."
    duration_ms = max(0, round((time.perf_counter() - started) * 1000))
    completed_at = _suggestion_now()

    status = SuggestionState.FAILED if error_code else SuggestionState.COMPLETED
    changes: list[SuggestedChange] = []
    message = error_message or "No reliable suggestion was found. Use Edit or Skip."
    raw_response: dict[str, Any] = {}
    if response is not None:
        try:
            provider_name = response.provider
            provider_model = response.model
            prompt_version = response.prompt_version
            raw_response = response.raw_response
            changes = _sanitise_changes(response, request)
            message = response.message or message
            if response.changes and not changes:
                status = SuggestionState.INVALID
                message = "The AI response did not contain a valid correction, so it was rejected."
            elif changes:
                issues = _validate_changes(db, request, changes)
                required = set(request.flagged_fields)
                if {change.field for change in changes} != required:
                    status = SuggestionState.INVALID
                    message = "The AI response did not correct every flagged field."
                elif issues:
                    status = SuggestionState.INVALID
                    message = "The AI response failed the order checks: " + "; ".join(
                        str(issue.get("message") or "invalid value") for issue in issues
                    )
                elif any(change.confidence < MIN_ACCEPT_CONFIDENCE for change in changes):
                    message = (
                        "The AI suggestion is below the review threshold;"
                        " edit manually or skip."
                    )
        except Exception:  # noqa: BLE001 - reject any malformed provider response.
            status = SuggestionState.INVALID
            message = "The AI response could not be validated, so it was rejected."
            changes = []
            raw_response = {}

    with db.transaction():
        db.execute(
            "UPDATE ai_suggestion_runs SET status = ?, provider = ?, model = ?,"
            " prompt_version = ?, message = ?, raw_response_json = ?, error_code = ?,"
            " completed_at = ?, duration_ms = ? WHERE id = ?",
            (
                status.value,
                provider_name,
                provider_model,
                prompt_version,
                message,
                json.dumps(raw_response, ensure_ascii=False, sort_keys=True),
                error_code,
                completed_at,
                duration_ms,
                run_id,
            ),
        )
        for change in changes:
            db.execute(
                "INSERT INTO ai_suggestion_items (run_id, field, value, confidence,"
                " reason, evidence_json) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    change.field,
                    change.value,
                    change.confidence,
                    change.reason,
                    json.dumps(list(change.evidence), ensure_ascii=False),
                ),
            )
        actionable = (
            status is SuggestionState.COMPLETED
            and set(request.flagged_fields) == {change.field for change in changes}
            and bool(changes)
            and all(change.confidence >= MIN_ACCEPT_CONFIDENCE for change in changes)
        )
        if actionable:
            summary = (
                changes[0].value
                if len(changes) == 1
                else "; ".join(f"{change.field}={change.value}" for change in changes)
            )
            confidence = min(change.confidence for change in changes)
            db.execute(
                "UPDATE exceptions SET suggestion = ?, confidence = ? WHERE id = ?",
                (summary, confidence, exception.id),
            )
        elif status is SuggestionState.COMPLETED:
            db.execute(
                "UPDATE exceptions SET suggestion = NULL, confidence = NULL WHERE id = ?",
                (exception.id,),
            )
        log_event(
            db,
            task_id=task_id,
            kind="ai_suggestion_generated" if status is SuggestionState.COMPLETED
            else "ai_suggestion_failed",
            actor=provider_name or ENGINE_NAME,
            actor_kind=ActorKind.ENGINE,
            occurred_at=completed_at,
            description=message,
            payload={
                "record_id": record_id,
                "suggestion_run_id": run_id,
                "status": status.value,
                "provider": provider_name,
                "model": provider_model,
                "change_count": len(changes),
                "actionable": actionable,
                "duration_ms": duration_ms,
            },
        )
    return _run_row(db, run_id)


def suggestion_context(db: Database, task_id: str) -> dict[str, dict[str, Any]]:
    """Latest run and latest completed items, keyed by exception id."""
    runs = db.query(
        "SELECT r.* FROM ai_suggestion_runs r"
        " JOIN exceptions e ON e.id = r.exception_id"
        " WHERE e.task_id = ? ORDER BY r.created_at DESC, r.id DESC",
        (task_id,),
    )
    context: dict[str, dict[str, Any]] = {}
    completed_run_ids: list[str] = []
    for row in runs:
        exception_id = row["exception_id"]
        latest = context.setdefault(exception_id, {"latest": row, "active": None, "items": []})
        if latest["active"] is None and row["status"] == SuggestionState.COMPLETED.value:
            latest["active"] = row
            completed_run_ids.append(row["id"])
    if completed_run_ids:
        placeholders = ", ".join("?" for _ in completed_run_ids)
        items = db.query(
            "SELECT i.*, r.exception_id FROM ai_suggestion_items i"
            " JOIN ai_suggestion_runs r ON r.id = i.run_id"
            f" WHERE i.run_id IN ({placeholders}) ORDER BY i.field",
            completed_run_ids,
        )
        active_ids = {
            exception_id: data["active"]["id"]
            for exception_id, data in context.items()
            if data["active"] is not None
        }
        by_exception: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            if item["run_id"] == active_ids.get(item["exception_id"]):
                try:
                    item["evidence"] = json.loads(item.pop("evidence_json"))
                except (TypeError, ValueError):
                    item["evidence"] = []
                by_exception.setdefault(item["exception_id"], []).append(item)
        for exception_id, item_list in by_exception.items():
            context[exception_id]["items"] = item_list
    return context


def accepted_changes(
    db: Database, exception: ExceptionItem
) -> dict[str, str] | None:
    """The active verified suggestion, or a legacy single-field rule suggestion."""
    required = {
        field.strip() for field in exception.flagged_fields.split(",") if field.strip()
    }
    rows = db.query(
        "SELECT i.field, i.value, i.confidence FROM ai_suggestion_runs r"
        " JOIN ai_suggestion_items i ON i.run_id = r.id"
        " WHERE r.exception_id = ? AND r.status = 'completed'"
        " ORDER BY r.created_at DESC, r.id DESC",
        (exception.id,),
    )
    if rows:
        latest_run = db.query(
            "SELECT id FROM ai_suggestion_runs WHERE exception_id = ?"
            " AND status = 'completed' ORDER BY created_at DESC, id DESC LIMIT 1",
            (exception.id,),
        )
        if latest_run:
            items = [
                row for row in db.query(
                    "SELECT field, value, confidence FROM ai_suggestion_items"
                    " WHERE run_id = ?",
                    (latest_run[0]["id"],),
                )
            ]
            if is_actionable(required, items):
                return {item["field"]: item["value"] for item in items}
    if len(required) == 1 and exception.suggestion:
        field = next(iter(required))
        if field in FIELDS:
            return {field: exception.suggestion}
    return None


def run_items(db: Database, run_id: str) -> list[dict[str, Any]]:
    items = db.query(
        "SELECT field, value, confidence, reason, evidence_json"
        " FROM ai_suggestion_items WHERE run_id = ? ORDER BY field",
        (run_id,),
    )
    for item in items:
        try:
            item["evidence"] = json.loads(item.pop("evidence_json"))
        except (TypeError, ValueError):
            item["evidence"] = []
    return items
