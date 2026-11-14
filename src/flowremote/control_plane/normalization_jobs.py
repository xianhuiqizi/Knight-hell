"""Staged normalization job: persistence, progress, cancel and retry.

One tick is one deterministic unit of work. The browser asks for a tick every
350 ms, so progress survives a refresh and no background thread or in-memory
job is required. Ticks are idempotent once the batch stops running.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from flowremote.contracts.enums import ActorKind
from flowremote.contracts.normalization import (
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_TOTAL_BYTES,
    RULE_VERSION,
    NormalizedSourceRow,
)
from flowremote.control_plane.activity import log_event
from flowremote.control_plane.db import Database, new_id, utc_now
from flowremote.control_plane.normalization import (
    NormalizationError,
    build_mapping,
    detect_table,
    fingerprint_sources,
    merge_records,
    normalize_table,
)
from flowremote.control_plane.sync import touch_task

STAGE_LABELS = {
    "detect": "Detecting formats",
    "map": "Mapping columns",
    "normalize": "Normalizing records",
    "merge": "Merging files",
    "complete": "Complete",
}
STATUS_LABELS = {
    "uploaded": "Ready to start",
    "running": "Running",
    "needs_review": "Needs review",
    "complete": "Complete",
    "canceled": "Canceled",
    "failed": "Failed",
}
FILE_STATUS_LABELS = {
    "uploaded": "Uploaded",
    "detected": "Detected",
    "mapped": "Mapped",
    "normalized": "Normalized",
    "attention": "Needs attention",
}
STAGES = ("detect", "map", "normalize", "merge", "complete")


class NormalizationJobError(ValueError):
    """The requested normalization transition is not currently allowed."""


def _elapsed_ms(started_at: str | None, finished_at: str | None = None) -> int:
    if not started_at:
        return 0
    start = datetime.fromisoformat(started_at)
    end = datetime.fromisoformat(finished_at) if finished_at else datetime.now(UTC)
    return max(0, int((end - start).total_seconds() * 1000))


def _suffix(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in (".xlsx", ".csv"):
        raise NormalizationJobError("Only .xlsx and .csv source files are accepted.")
    return suffix


def create_normalization_task(
    db: Database,
    upload_dir: Path,
    owner_id: str,
    name: str,
    files: list[tuple[str, bytes]],
    actor: str = "Signed-in user",
) -> str:
    """Persist a task and its source files, before any parsing is attempted."""
    if not 1 <= len(files) <= MAX_FILES:
        raise NormalizationJobError(f"Choose between 1 and {MAX_FILES} files.")
    if any(len(data) > MAX_FILE_BYTES for _, data in files):
        raise NormalizationJobError("Each file must be 10 MB or smaller.")
    if sum(len(data) for _, data in files) > MAX_TOTAL_BYTES:
        raise NormalizationJobError("The combined upload must be 20 MB or smaller.")

    task_id, batch_id = new_id("TASK"), new_id("NORM")
    now = utc_now()
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored: list[tuple[str, str, bytes]] = []
    destinations: list[Path] = []
    try:
        for filename, data in files:
            storage_name = uuid4().hex + _suffix(filename)
            destination = upload_dir / storage_name
            with destination.open("xb") as target:
                target.write(data)
            destinations.append(destination)
            stored.append((filename, storage_name, data))

        source_summary = ", ".join(filename for filename, _, _ in stored)
        if len(source_summary) > 500:
            source_summary = source_summary[:497] + "..."
        fingerprint = fingerprint_sources([(filename, data) for filename, data in files])
        with db.transaction():
            db.execute(
                "INSERT INTO tasks (id, workflow, batch_size, status, source_file,"
                " source_location, primary_target, secondary_target, owner_id, created_at,"
                " updated_at, task_mode) VALUES (?, ?, ?, 'ready', ?, 'Uploaded files',"
                " 'Normalized Excel', 'Audit trail', ?, ?, ?, 'normalize')",
                (
                    task_id,
                    name,
                    len(files),
                    source_summary,
                    owner_id,
                    now,
                    now,
                ),
            )
            db.execute(
                "INSERT INTO normalization_batches (id, task_id, status, stage, cursor,"
                " current_file, total_files, processed_files, raw_records, normalized_records,"
                " auto_fixed, issue_count, rule_version, input_fingerprint, created_at, updated_at)"
                " VALUES (?, ?, 'uploaded', 'detect', 0, ?, ?, 0, 0, 0, 0, 0, ?, ?, ?, ?)",
                (
                    batch_id,
                    task_id,
                    files[0][0],
                    len(files),
                    RULE_VERSION,
                    fingerprint,
                    now,
                    now,
                ),
            )
            for ordinal, (filename, storage_name, data) in enumerate(stored):
                db.execute(
                    "INSERT INTO normalization_files (id, batch_id, task_id, ordinal, filename,"
                    " storage_name, byte_size, file_type, status, mapping_json, created_at,"
                    " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'uploaded', '{}', ?, ?)",
                    (
                        new_id("NFL"),
                        batch_id,
                        task_id,
                        ordinal,
                        filename,
                        storage_name,
                        len(data),
                        _suffix(filename).lstrip("."),
                        now,
                        now,
                    ),
                )
            log_event(
                db,
                task_id=task_id,
                kind="normalize_upload",
                actor=actor,
                actor_kind=ActorKind.USER,
                occurred_at=now,
                description=(
                    f"Uploaded {len(files)} source files "
                    f"({sum(len(data) for _, data in files) / 1024:.1f} KB) for normalization"
                ),
                payload={
                    "files": [entry[0] for entry in files],
                    "input_fingerprint": fingerprint,
                    "rule_version": RULE_VERSION,
                },
            )
        return task_id
    except Exception:
        for destination in destinations:
            destination.unlink(missing_ok=True)
        raise


def recognize_normalization_task(
    db: Database, task_id: str, upload_dir: Path, actor: str = "FlowRemote Normalizer"
) -> dict | None:
    """Detect and map every file at upload time, before the run starts.

    The demo script needs visible recognition before the presenter presses
    Start. This pass is side-effect free apart from file metadata and the two
    activity events; no normalized row is written.
    """
    batch = get_batch(db, task_id)
    if batch is None:
        raise NormalizationJobError("This task has no normalization batch.")
    files = _files(db, batch["id"])
    if not files:
        return normalization_snapshot(db, task_id)
    if all(file["status"] in ("mapped", "normalized", "attention") for file in files):
        return normalization_snapshot(db, task_id)
    now = utc_now()
    with db.transaction():
        for table in ("normalized_records", "normalization_changes", "normalization_issues"):
            db.execute(f"DELETE FROM {table} WHERE batch_id = ? AND issue_type <> 'file_error'"
                       if table == "normalization_issues"
                       else f"DELETE FROM {table} WHERE batch_id = ?",
                       (batch["id"],))
        detected_count = 0
        mapped_count = 0
        field_assignments = 0
        for file in files:
            db.execute(
                "UPDATE normalization_files SET status = 'uploaded', file_type = NULL,"
                " worksheet = NULL, header_row = NULL, row_count = NULL, field_count = NULL,"
                " detected_columns = NULL, error = NULL, mapping_json = '{}', updated_at = ?"
                " WHERE id = ?",
                (now, file["id"]),
            )
            try:
                data = _file_bytes(upload_dir, file["storage_name"])
                detected = detect_table(file["filename"], data)
                mapping = build_mapping(detected)
            except (NormalizationError, OSError) as exc:
                _mark_attention(
                    db,
                    batch_id=batch["id"],
                    file_id=file["id"],
                    filename=file["filename"],
                    message=str(exc),
                    now=now,
                )
                continue
            detected_count += 1
            mapped_count += 1
            field_assignments += mapping.field_count
            db.execute(
                "UPDATE normalization_files SET status = 'mapped', file_type = ?,"
                " worksheet = ?, header_row = ?, row_count = ?, field_count = ?,"
                " detected_columns = ?, error = NULL, mapping_json = ?, updated_at = ?"
                " WHERE id = ?",
                (
                    detected.file_type,
                    detected.worksheet,
                    detected.header_row,
                    detected.row_count,
                    mapping.field_count,
                    detected.column_count,
                    json.dumps(mapping.as_dict(), ensure_ascii=False),
                    now,
                    file["id"],
                ),
            )
        raw = db.scalar(
            "SELECT COALESCE(SUM(row_count), 0) FROM normalization_files WHERE batch_id = ?",
            (batch["id"],),
            0,
        )
        db.execute(
            "UPDATE normalization_batches SET stage = 'normalize', cursor = 0,"
            " current_file = ?, processed_files = 0, raw_records = ?,"
            " normalized_records = 0, auto_fixed = 0, issue_count = ("
            " SELECT COUNT(*) FROM normalization_issues WHERE batch_id = ?"
            " AND status = 'unresolved'), updated_at = ? WHERE id = ?",
            (files[0]["filename"], int(raw or 0), batch["id"], now, batch["id"]),
        )
        db.execute(
            "UPDATE tasks SET batch_size = ?, updated_at = ? WHERE id = ?",
            (max(1, int(raw or 0)), now, task_id),
        )
        _log_stage(
            db,
            task_id=task_id,
            kind="normalize_detect",
            description=(
                f"Detected {detected_count}/{len(files)} files with {int(raw or 0)} source rows"
            ),
            now=now,
            payload={
                "detected": detected_count,
                "total": len(files),
                "raw_records": int(raw or 0),
            },
        )
        _log_stage(
            db,
            task_id=task_id,
            kind="normalize_map",
            description=(
                f"Mapped {field_assignments} field assignments across {mapped_count}"
                " files with rule evidence"
            ),
            now=now,
            payload={
                "mapped_files": mapped_count,
                "field_assignments": field_assignments,
            },
        )
    return normalization_snapshot(db, task_id)


def get_batch(db: Database, task_id: str) -> dict | None:
    rows = db.query("SELECT * FROM normalization_batches WHERE task_id = ?", (task_id,))
    return dict(rows[0]) if rows else None


def _files(db: Database, batch_id: str) -> list[dict]:
    return [
        dict(row)
        for row in db.query(
            "SELECT * FROM normalization_files WHERE batch_id = ? ORDER BY ordinal",
            (batch_id,),
        )
    ]


def _safe_json_object(value: Any) -> dict:
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _current_file_name(files: list[dict], cursor: int) -> str | None:
    if 0 <= cursor < len(files):
        return files[cursor]["filename"]
    return None


def _progress(batch: dict) -> dict[str, Any]:
    total_files = int(batch["total_files"] or 1)
    stage = batch["stage"]
    cursor = int(batch["cursor"] or 0)
    if batch["status"] in ("needs_review", "complete"):
        total_steps = total_files + 1
        return {
            "stage": "complete",
            "stage_label": STAGE_LABELS["complete"],
            "stage_index": 2,
            "stage_total": 2,
            "steps_done": total_steps,
            "steps_total": total_steps,
            "percent": 100,
        }
    if stage in ("normalize", "merge"):
        # Recognition and mapping happened at upload. The visible run is the
        # normalization pass plus one merge step.
        total_steps = total_files + 1
        steps_done = cursor if stage == "normalize" else total_files
        stage_index = 0 if stage == "normalize" else 1
        stage_total = 2
    else:
        stage_index = STAGES.index(stage) if stage in STAGES else 0
        total_steps = 3 * total_files + 1
        steps_done = min(total_steps, stage_index * total_files + cursor)
        stage_total = 4
    steps_done = min(total_steps, steps_done)
    return {
        "stage": stage,
        "stage_label": STAGE_LABELS.get(stage, stage),
        "stage_index": stage_index,
        "stage_total": stage_total,
        "steps_done": steps_done,
        "steps_total": total_steps,
        "percent": min(99, round(100 * steps_done / total_steps)),
    }


def normalization_snapshot(db: Database, task_id: str) -> dict[str, Any] | None:
    batch = get_batch(db, task_id)
    if batch is None:
        return None
    files = _files(db, batch["id"])
    progress = _progress(batch)
    unresolved = db.scalar(
        "SELECT COUNT(*) FROM normalization_issues WHERE batch_id = ?"
        " AND status = 'unresolved'",
        (batch["id"],),
        0,
    )
    total_issues = db.scalar(
        "SELECT COUNT(*) FROM normalization_issues WHERE batch_id = ?", (batch["id"],), 0
    )
    confirmed = db.scalar(
        "SELECT COUNT(*) FROM normalization_issues WHERE batch_id = ?"
        " AND status = 'resolved'",
        (batch["id"],),
        0,
    )
    skipped = db.scalar(
        "SELECT COUNT(*) FROM normalization_issues WHERE batch_id = ?"
        " AND status = 'skipped'",
        (batch["id"],),
        0,
    )
    duration = (
        batch.get("duration_ms")
        if batch["status"] in ("needs_review", "complete")
        else _elapsed_ms(batch.get("started_at"), batch.get("finished_at"))
    )
    current_file = batch.get("current_file") if batch["status"] == "running" else None
    if batch["status"] == "running" and not current_file:
        current_file = _current_file_name(files, int(batch.get("cursor") or 0))
    return {
        "task_id": task_id,
        "batch_id": batch["id"],
        "status": batch["status"],
        "status_label": STATUS_LABELS.get(batch["status"], batch["status"]),
        "current_file": current_file,
        "total_files": int(batch["total_files"]),
        "phase_done": (
            int(batch["total_files"])
            if batch["stage"] == "merge" and batch["status"] == "running"
            else int(batch["cursor"] or 0)
        ),
        "processed_files": int(batch["cursor"] or 0),
        "raw_records": int(batch.get("raw_records") or 0),
        "normalized_records": int(batch.get("normalized_records") or 0),
        "auto_fixed": int(batch.get("auto_fixed") or 0),
        "issues": total_issues,
        "unresolved": unresolved,
        "confirmed": int(confirmed or 0),
        "skipped": int(skipped or 0),
        "review_ready": batch["status"] == "needs_review" and int(unresolved or 0) == 0,
        "review_completed_at": batch.get("review_completed_at"),
        "recognized": sum(
            1 for row in files if row["status"] in ("mapped", "normalized")
        ),
        "needs_attention": sum(1 for row in files if row["status"] == "attention"),
        "duration_ms": duration,
        "started_at": batch.get("started_at"),
        "finished_at": batch.get("finished_at"),
        "files": [
            {
                "id": row["id"],
                "ordinal": row["ordinal"],
                "filename": row["filename"],
                "byte_size": row["byte_size"],
                "file_type": row.get("file_type"),
                "worksheet": row.get("worksheet"),
                "header_row": row.get("header_row"),
                "row_count": row.get("row_count"),
                "field_count": row.get("field_count"),
                "detected_columns": row.get("detected_columns"),
                "status": row["status"],
                "status_label": FILE_STATUS_LABELS.get(row["status"], row["status"]),
                "error": row.get("error"),
                "mapping": _safe_json_object(row.get("mapping_json")),
            }
            for row in files
        ],
        **progress,
    }


def start_normalization(db: Database, task_id: str, actor: str = "Signed-in user") -> bool:
    """Start or resume a job. Repeated calls are harmless."""
    batch = get_batch(db, task_id)
    if batch is None:
        raise NormalizationJobError("This task has no normalization batch.")
    if batch["status"] == "running":
        return False
    if batch["status"] in ("needs_review", "complete"):
        return False
    files = _files(db, batch["id"])
    if not files:
        raise NormalizationJobError("No source files are attached to this batch.")
    prepared = batch["stage"] == "normalize" and all(
        file["status"] in ("mapped", "attention") for file in files
    )
    now = utc_now()
    with db.transaction():
        for table in ("normalized_records", "normalization_changes"):
            db.execute(f"DELETE FROM {table} WHERE batch_id = ?", (batch["id"],))
        if prepared:
            db.execute(
                "DELETE FROM normalization_issues WHERE batch_id = ?"
                " AND issue_type <> 'file_error'",
                (batch["id"],),
            )
        else:
            db.execute(
                "DELETE FROM normalization_issues WHERE batch_id = ?", (batch["id"],)
            )
            db.execute(
                "UPDATE normalization_files SET status = 'uploaded', file_type = NULL,"
                " worksheet = NULL, header_row = NULL, row_count = NULL, field_count = NULL,"
                " detected_columns = NULL, error = NULL, mapping_json = '{}', updated_at = ?"
                " WHERE batch_id = ?",
                (now, batch["id"]),
            )
        raw_records = db.scalar(
            "SELECT COALESCE(SUM(row_count), 0) FROM normalization_files WHERE batch_id = ?",
            (batch["id"],),
            0,
        )
        file_errors = db.scalar(
            "SELECT COUNT(*) FROM normalization_issues WHERE batch_id = ?"
            " AND issue_type = 'file_error' AND status = 'unresolved'",
            (batch["id"],),
            0,
        )
        db.execute(
            "UPDATE normalization_batches SET status = 'running', stage = ?, cursor = 0,"
            " current_file = ?, processed_files = 0, raw_records = ?, normalized_records = 0,"
            " auto_fixed = 0, issue_count = ?, started_at = ?, finished_at = NULL,"
            " duration_ms = NULL, updated_at = ? WHERE id = ?",
            (
                "normalize" if prepared else "detect",
                files[0]["filename"],
                int(raw_records or 0),
                int(file_errors or 0),
                now,
                now,
                batch["id"],
            ),
        )
        db.execute(
            "UPDATE tasks SET status = 'validating', updated_at = ? WHERE id = ?",
            (now, task_id),
        )
        touch_task(db, task_id)
        log_event(
            db,
            task_id=task_id,
            kind="normalize_started",
            actor=actor,
            actor_kind=ActorKind.USER,
            occurred_at=now,
            description=(
                f"Started normalization of {len(files)} sources with rules-only mode"
            ),
            payload={"files": len(files), "rule_version": RULE_VERSION},
        )
    return True


def cancel_normalization(db: Database, task_id: str, actor: str = "Signed-in user") -> bool:
    batch = get_batch(db, task_id)
    if batch is None:
        raise NormalizationJobError("This task has no normalization batch.")
    if batch["status"] not in ("uploaded", "running"):
        return False
    files = _files(db, batch["id"])
    prepared = bool(files) and all(
        file["status"] in ("mapped", "normalized", "attention") for file in files
    )
    now = utc_now()
    with db.transaction():
        for table in ("normalized_records", "normalization_changes"):
            db.execute(f"DELETE FROM {table} WHERE batch_id = ?", (batch["id"],))
        db.execute(
            "DELETE FROM normalization_issues WHERE batch_id = ?"
            + ("" if not prepared else " AND issue_type <> 'file_error'"),
            (batch["id"],),
        )
        if prepared:
            db.execute(
                "UPDATE normalization_files SET status = CASE WHEN status = 'normalized'"
                " THEN 'mapped' ELSE status END, updated_at = ? WHERE batch_id = ?",
                (now, batch["id"]),
            )
        else:
            db.execute(
                "UPDATE normalization_files SET status = 'uploaded', file_type = NULL,"
                " worksheet = NULL, header_row = NULL, row_count = NULL, field_count = NULL,"
                " detected_columns = NULL, error = NULL, mapping_json = '{}', updated_at = ?"
                " WHERE batch_id = ?",
                (now, batch["id"]),
            )
        raw_records = db.scalar(
            "SELECT COALESCE(SUM(row_count), 0) FROM normalization_files WHERE batch_id = ?",
            (batch["id"],),
            0,
        )
        file_errors = db.scalar(
            "SELECT COUNT(*) FROM normalization_issues WHERE batch_id = ?"
            " AND issue_type = 'file_error' AND status = 'unresolved'",
            (batch["id"],),
            0,
        )
        db.execute(
            "UPDATE normalization_batches SET status = 'canceled', stage = ?, cursor = 0,"
            " current_file = ?, processed_files = 0, raw_records = ?, normalized_records = 0,"
            " auto_fixed = 0, issue_count = ?, started_at = NULL, finished_at = NULL,"
            " duration_ms = NULL, updated_at = ? WHERE id = ?",
            (
                "normalize" if prepared else "detect",
                files[0]["filename"] if prepared else None,
                int(raw_records or 0),
                int(file_errors or 0),
                now,
                batch["id"],
            ),
        )
        db.execute(
            "UPDATE tasks SET status = 'ready', updated_at = ? WHERE id = ?",
            (now, task_id),
        )
        touch_task(db, task_id)
        log_event(
            db,
            task_id=task_id,
            kind="normalize_canceled",
            actor=actor,
            actor_kind=ActorKind.USER,
            occurred_at=now,
            description="Canceled normalization and removed all partial derived data",
            payload={"derived_rows_removed": True},
        )
    return True


def _file_bytes(upload_dir: Path, storage_name: str) -> bytes:
    path = upload_dir / storage_name
    if not path.is_file():
        raise NormalizationError(
            "This uploaded file is missing on disk. Upload it again as a new task."
        )
    return path.read_bytes()


def _mark_attention(
    db: Database,
    *,
    batch_id: str,
    file_id: str,
    filename: str,
    message: str,
    now: str,
) -> None:
    db.execute(
        "UPDATE normalization_files SET status = 'attention', error = ?, updated_at = ? WHERE id = ?",
        (message, now, file_id),
    )
    db.execute(
        "INSERT INTO normalization_issues (id, batch_id, task_id, file_id, issue_type, field,"
        " order_id, source_file, source_row, original_value, suggested_value, confidence,"
        " reason, status, created_at) VALUES (?, ?,"
        " (SELECT task_id FROM normalization_files WHERE id = ?), ?, 'file_error', '', NULL,"
        " ?, NULL, '', NULL, NULL, ?, 'unresolved', ?)",
        (new_id("NIS"), batch_id, file_id, file_id, filename, message, now),
    )


def _log_stage(
    db: Database,
    *,
    task_id: str,
    kind: str,
    description: str,
    now: str,
    payload: dict[str, Any],
) -> None:
    log_event(
        db,
        task_id=task_id,
        kind=kind,
        actor="FlowRemote Normalizer",
        actor_kind=ActorKind.ENGINE,
        occurred_at=now,
        description=description,
        payload=payload,
    )


def _tick_detect(
    db: Database,
    *,
    batch: dict,
    files: list[dict],
    upload_dir: Path,
    now: str,
) -> None:
    cursor = int(batch["cursor"] or 0)
    if cursor >= len(files):
        db.execute(
            "UPDATE normalization_batches SET stage = 'map', cursor = 0, processed_files = 0,"
            " current_file = ?, updated_at = ? WHERE id = ?",
            (files[0]["filename"], now, batch["id"]),
        )
        raw = db.scalar(
            "SELECT COALESCE(SUM(row_count), 0) FROM normalization_files WHERE batch_id = ?",
            (batch["id"],),
            0,
        )
        detected_count = db.scalar(
            "SELECT COUNT(*) FROM normalization_files WHERE batch_id = ?"
            " AND status IN ('detected', 'mapped', 'normalized')",
            (batch["id"],),
            0,
        )
        db.execute(
            "UPDATE normalization_batches SET raw_records = ? WHERE id = ?",
            (int(raw or 0), batch["id"]),
        )
        _log_stage(
            db,
            task_id=batch["task_id"],
            kind="normalize_detect",
            description=(
                f"Detected {int(detected_count or 0)}/{len(files)} files"
                f" with {int(raw or 0)} source rows"
            ),
            now=now,
            payload={
                "detected": int(detected_count or 0),
                "total": len(files),
                "raw_records": int(raw or 0),
            },
        )
        return

    file = files[cursor]
    try:
        data = _file_bytes(upload_dir, file["storage_name"])
        detected = detect_table(file["filename"], data)
    except (NormalizationError, OSError) as exc:
        _mark_attention(
            db,
            batch_id=batch["id"],
            file_id=file["id"],
            filename=file["filename"],
            message=str(exc),
            now=now,
        )
    else:
        db.execute(
            "UPDATE normalization_files SET status = 'detected', file_type = ?, worksheet = ?,"
            " header_row = ?, row_count = ?, detected_columns = ?, error = NULL, updated_at = ?"
            " WHERE id = ?",
            (
                detected.file_type,
                detected.worksheet,
                detected.header_row,
                detected.row_count,
                detected.column_count,
                now,
                file["id"],
            ),
        )
    next_cursor = cursor + 1
    next_file = files[next_cursor]["filename"] if next_cursor < len(files) else None
    db.execute(
        "UPDATE normalization_batches SET cursor = ?, processed_files = ?, current_file = ?,"
        " updated_at = ? WHERE id = ?",
        (next_cursor, next_cursor, next_file, now, batch["id"]),
    )


def _tick_map(
    db: Database,
    *,
    batch: dict,
    files: list[dict],
    upload_dir: Path,
    now: str,
) -> None:
    cursor = int(batch["cursor"] or 0)
    if cursor >= len(files):
        db.execute(
            "UPDATE normalization_batches SET stage = 'normalize', cursor = 0, processed_files = 0,"
            " current_file = ?, updated_at = ? WHERE id = ?",
            (files[0]["filename"], now, batch["id"]),
        )
        mapped = db.scalar(
            "SELECT COUNT(*) FROM normalization_files WHERE batch_id = ? AND status = 'mapped'",
            (batch["id"],),
            0,
        )
        fields = db.scalar(
            "SELECT COALESCE(SUM(field_count), 0) FROM normalization_files WHERE batch_id = ?",
            (batch["id"],),
            0,
        )
        _log_stage(
            db,
            task_id=batch["task_id"],
            kind="normalize_map",
            description=(
                f"Mapped {int(fields or 0)} field assignments across {int(mapped or 0)}"
                " files with rule evidence"
            ),
            now=now,
            payload={"mapped_files": int(mapped or 0), "field_assignments": int(fields or 0)},
        )
        return

    file = files[cursor]
    if file["status"] == "detected":
        try:
            data = _file_bytes(upload_dir, file["storage_name"])
            detected = detect_table(file["filename"], data)
            mapping = build_mapping(detected)
        except (NormalizationError, OSError) as exc:
            _mark_attention(
                db,
                batch_id=batch["id"],
                file_id=file["id"],
                filename=file["filename"],
                message=str(exc),
                now=now,
            )
        else:
            db.execute(
                "UPDATE normalization_files SET status = 'mapped', field_count = ?,"
                " detected_columns = ?, mapping_json = ?, error = NULL, updated_at = ?"
                " WHERE id = ?",
                (
                    mapping.field_count,
                    detected.column_count,
                    json.dumps(mapping.as_dict(), ensure_ascii=False),
                    now,
                    file["id"],
                ),
            )
    next_cursor = cursor + 1
    at_end = next_cursor >= len(files)
    next_file = files[next_cursor]["filename"] if not at_end else None
    db.execute(
        "UPDATE normalization_batches SET cursor = ?, processed_files = ?, current_file = ?,"
        " updated_at = ? WHERE id = ?",
        (next_cursor, next_cursor, next_file, now, batch["id"]),
    )


def _insert_file_result(
    db: Database,
    *,
    batch_id: str,
    task_id: str,
    file: dict,
    detected,
    mapping,
    rows,
    now: str,
) -> None:
    db.execute(
        "DELETE FROM normalization_changes WHERE batch_id = ? AND file_id = ?",
        (batch_id, file["id"]),
    )
    db.execute(
        "DELETE FROM normalization_issues WHERE batch_id = ? AND file_id = ?"
        " AND issue_type <> 'file_error'",
        (batch_id, file["id"]),
    )
    db.execute(
        "DELETE FROM normalized_records WHERE batch_id = ? AND file_id = ?",
        (batch_id, file["id"]),
    )
    for row in rows:
        db.execute(
            "INSERT INTO normalized_records (id, batch_id, task_id, file_id, source_file,"
            " source_row, order_id, customer_name, customer_id, quantity, unit, unit_price,"
            " amount, order_date, is_primary, duplicate_count, has_conflict, issue_count,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, 0, ?, ?)",
            (
                new_id("NRC"),
                batch_id,
                task_id,
                file["id"],
                row.source_file,
                row.source_row,
                row.order_id,
                row.customer_name or None,
                row.customer_id or None,
                row.quantity,
                row.unit,
                row.unit_price,
                row.amount,
                row.order_date,
                len(row.issues),
                now,
            ),
        )
        for change in row.changes:
            db.execute(
                "INSERT INTO normalization_changes (id, batch_id, task_id, file_id, order_id,"
                " source_file, source_row, field, original_value, new_value, reason, method,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    new_id("NCH"),
                    batch_id,
                    task_id,
                    file["id"],
                    row.order_id,
                    row.source_file,
                    row.source_row,
                    change["field"],
                    change["original_value"],
                    change["new_value"],
                    change["reason"],
                    change["method"],
                    now,
                ),
            )
        for issue in row.issues:
            db.execute(
                "INSERT INTO normalization_issues (id, batch_id, task_id, file_id, issue_type,"
                " field, order_id, source_file, source_row, original_value, suggested_value,"
                " confidence, reason, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
                " ?, ?, ?, 'unresolved', ?)",
                (
                    new_id("NIS"),
                    batch_id,
                    task_id,
                    file["id"],
                    issue["issue_type"],
                    issue["field"],
                    row.order_id,
                    row.source_file,
                    row.source_row,
                    issue["original_value"],
                    issue["suggested_value"],
                    issue["confidence"],
                    issue["reason"],
                    now,
                ),
            )


def _tick_normalize(
    db: Database,
    *,
    batch: dict,
    files: list[dict],
    upload_dir: Path,
    now: str,
) -> None:
    cursor = int(batch["cursor"] or 0)
    if cursor >= len(files):
        db.execute(
            "UPDATE normalization_batches SET stage = 'merge', cursor = 0, processed_files = 0,"
            " current_file = NULL, updated_at = ? WHERE id = ?",
            (now, batch["id"]),
        )
        raw = db.scalar(
            "SELECT COALESCE(SUM(row_count), 0) FROM normalization_files WHERE batch_id = ?",
            (batch["id"],),
            0,
        )
        count = db.scalar(
            "SELECT COUNT(*) FROM normalized_records WHERE batch_id = ?", (batch["id"],), 0
        )
        fixed = db.scalar(
            "SELECT COUNT(*) FROM normalized_records r WHERE r.batch_id = ? AND EXISTS ("
            " SELECT 1 FROM normalization_changes c WHERE c.batch_id = r.batch_id"
            " AND c.file_id = r.file_id AND c.source_row = r.source_row)",
            (batch["id"],),
            0,
        )
        db.execute(
            "UPDATE normalization_batches SET raw_records = ?, normalized_records = ?,"
            " auto_fixed = ? WHERE id = ?",
            (int(raw or 0), int(count or 0), int(fixed or 0), batch["id"]),
        )
        conversion_rows = db.query(
            "SELECT reason, COUNT(*) AS n FROM normalization_changes WHERE batch_id = ?"
            " GROUP BY reason",
            (batch["id"],),
        )
        conversions = {row["reason"]: int(row["n"]) for row in conversion_rows}
        thousand = sum(
            count for reason, count in conversions.items()
            if "thousand CNY" in reason
        )
        boxes = sum(
            count for reason, count in conversions.items()
            if reason.startswith("Converted boxes to pieces")
        )
        dates = sum(
            count for reason, count in conversions.items()
            if reason.startswith("Normalized ") and "date to ISO" in reason
        )
        _log_stage(
            db,
            task_id=batch["task_id"],
            kind="normalize_normalize",
            description=(
                f"Normalized {int(raw or 0)} source rows: {thousand} thousand-CNY prices"
                f" converted, {boxes} box rows converted to pieces, {dates} dates"
                f" normalized; {int(fixed or 0)} records carry rule-based fixes"
            ),
            now=now,
            payload={
                "raw_records": int(raw or 0),
                "source_rows_stored": int(count or 0),
                "auto_fixed_records": int(fixed or 0),
                "thousand_cny_conversions": thousand,
                "box_to_piece_conversions": boxes,
                "date_conversions": dates,
            },
        )
        return

    file = files[cursor]
    if file["status"] == "mapped":
        try:
            data = _file_bytes(upload_dir, file["storage_name"])
            detected = detect_table(file["filename"], data)
            mapping = build_mapping(detected)
            rows = normalize_table(
                detected,
                mapping,
                source_file=file["filename"],
                source_file_id=file["id"],
                file_ordinal=int(file["ordinal"]),
            )
            _insert_file_result(
                db,
                batch_id=batch["id"],
                task_id=batch["task_id"],
                file=file,
                detected=detected,
                mapping=mapping,
                rows=rows,
                now=now,
            )
            db.execute(
                "UPDATE normalization_files SET status = 'normalized', row_count = ?,"
                " field_count = ?, error = NULL, updated_at = ? WHERE id = ?",
                (detected.row_count, mapping.field_count, now, file["id"]),
            )
        except (NormalizationError, OSError) as exc:
            _mark_attention(
                db,
                batch_id=batch["id"],
                file_id=file["id"],
                filename=file["filename"],
                message=str(exc),
                now=now,
            )
    next_cursor = cursor + 1
    next_file = (
        files[next_cursor]["filename"] if next_cursor < len(files) else None
    )
    db.execute(
        "UPDATE normalization_batches SET cursor = ?, processed_files = ?, current_file = ?,"
        " updated_at = ? WHERE id = ?",
        (next_cursor, next_cursor, next_file, now, batch["id"]),
    )


def _tick_merge(db: Database, *, batch: dict, now: str) -> None:
    batch_id = batch["id"]
    task_id = batch["task_id"]
    db.execute(
        "DELETE FROM normalization_issues WHERE batch_id = ? AND issue_type = 'cross_file_conflict'",
        (batch_id,),
    )
    rows = db.query(
        "SELECT r.*, f.ordinal FROM normalized_records r"
        " JOIN normalization_files f ON f.id = r.file_id"
        " WHERE r.batch_id = ? ORDER BY f.ordinal, r.source_row",
        (batch_id,),
    )
    reconstructed = [
        NormalizedSourceRow(
            order_id=row["order_id"],
            customer_name=row["customer_name"] or "",
            customer_id=row["customer_id"] or "",
            quantity=row["quantity"],
            unit=row["unit"] or "piece",
            unit_price=row["unit_price"],
            amount=row["amount"],
            order_date=row["order_date"],
            source_file=row["source_file"],
            source_row=row["source_row"],
            source_file_id=row["file_id"],
            file_ordinal=int(row["ordinal"]),
        )
        for row in rows
    ]
    merged, conflicts = merge_records(reconstructed)
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["order_id"], []).append(row)
    for item in merged:
        group = groups[item["order_id"]]
        for source in group:
            is_primary = (
                source["source_file"] == item["source_file"]
                and source["source_row"] == item["source_row"]
            )
            db.execute(
                "UPDATE normalized_records SET is_primary = ?, duplicate_count = ?,"
                " has_conflict = ?, issue_count = ? WHERE id = ?",
                (
                    1 if is_primary else 0,
                    item["duplicate_count"],
                    1 if item["has_conflict"] else 0,
                    item["issue_count"],
                    source["id"],
                ),
            )
    files = _files(db, batch_id)
    for conflict in conflicts:
        source_file = conflict["source_file"]
        file_id = next(
            (row["file_id"] for row in rows if row["source_file"] == source_file), None
        )
        db.execute(
            "INSERT INTO normalization_issues (id, batch_id, task_id, file_id, issue_type,"
            " field, order_id, source_file, source_row, original_value, suggested_value,"
            " confidence, reason, status, created_at) VALUES (?, ?, ?, ?, 'cross_file_conflict',"
            " ?, ?, ?, ?, ?, NULL, NULL, ?, 'unresolved', ?)",
            (
                new_id("NIS"),
                batch_id,
                task_id,
                file_id,
                conflict["field"],
                conflict["order_id"],
                conflict["source_file"],
                conflict["source_row"],
                conflict["original_value"],
                conflict["reason"],
                now,
            ),
        )
    unresolved = db.scalar(
        "SELECT COUNT(*) FROM normalization_issues WHERE batch_id = ?"
        " AND status = 'unresolved'",
        (batch_id,),
        0,
    )
    normalized_count = len(merged)
    fixed = db.scalar(
        "SELECT COUNT(*) FROM normalized_records r WHERE r.batch_id = ? AND EXISTS ("
        " SELECT 1 FROM normalization_changes c WHERE c.batch_id = r.batch_id"
        " AND c.file_id = r.file_id AND c.source_row = r.source_row)",
        (batch_id,),
        0,
    )
    started = batch.get("started_at") or now
    duration = _elapsed_ms(started, now)
    new_status = "needs_review" if int(unresolved or 0) else "complete"
    db.execute(
        "UPDATE normalization_batches SET status = ?, stage = 'complete', cursor = 0,"
        " current_file = NULL, processed_files = ?, raw_records = ?, normalized_records = ?,"
        " auto_fixed = ?, issue_count = ?, finished_at = ?, duration_ms = ?, updated_at = ?"
        " WHERE id = ?",
        (
            new_status,
            len(files),
            db.scalar(
                "SELECT COALESCE(SUM(row_count), 0) FROM normalization_files WHERE batch_id = ?",
                (batch_id,),
                0,
            ),
            normalized_count,
            int(fixed or 0),
            int(unresolved or 0),
            now,
            duration,
            now,
            batch_id,
        ),
    )
    db.execute(
        "UPDATE tasks SET status = ?, batch_size = ?, updated_at = ? WHERE id = ?",
        (
            "review_required" if new_status == "needs_review" else "complete",
            max(1, normalized_count),
            now,
            task_id,
        ),
    )
    touch_task(db, task_id)
    _log_stage(
        db,
        task_id=task_id,
        kind="normalize_complete",
        description=(
            f"Normalization complete: {len(files)} files, {len(rows)} source rows,"
            f" {normalized_count} merged records, {len(conflicts)} cross-file conflicts,"
            f" {int(unresolved or 0)} unresolved"
        ),
        now=now,
        payload={
            "files": len(files),
            "source_rows": len(rows),
            "records": normalized_count,
            "cross_file_conflicts": len(conflicts),
            "auto_fixed_records": int(fixed or 0),
            "unresolved": int(unresolved or 0),
            "duration_ms": duration,
        },
    )


def tick_normalization(db: Database, task_id: str, upload_dir: Path) -> dict[str, Any]:
    """Advance exactly one stage step and return the new snapshot."""
    batch = get_batch(db, task_id)
    if batch is None:
        raise NormalizationJobError("This task has no normalization batch.")
    if batch["status"] != "running":
        snapshot = normalization_snapshot(db, task_id)
        if snapshot is None:
            raise NormalizationJobError("This task has no normalization batch.")
        return snapshot

    files = _files(db, batch["id"])
    now = utc_now()
    with db.transaction():
        # Re-read inside the transaction so two browser tabs cannot apply the
        # same step twice.
        current = get_batch(db, task_id)
        if current is None or current["status"] != "running":
            pass
        elif current["stage"] == "detect":
            _tick_detect(
                db, batch=current, files=files, upload_dir=upload_dir, now=now
            )
        elif current["stage"] == "map":
            _tick_map(db, batch=current, files=files, upload_dir=upload_dir, now=now)
        elif current["stage"] == "normalize":
            _tick_normalize(
                db, batch=current, files=files, upload_dir=upload_dir, now=now
            )
        elif current["stage"] == "merge":
            _tick_merge(db, batch=current, now=now)
    snapshot = normalization_snapshot(db, task_id)
    if snapshot is None:
        raise NormalizationJobError("This task has no normalization batch.")
    return snapshot


def download_workbook(db: Database, task_id: str) -> bytes:
    """Build the three-sheet output workbook for a finished batch."""
    batch = get_batch(db, task_id)
    if batch is None:
        raise NormalizationJobError("This task has no normalization batch.")
    if batch["status"] != "complete":
        raise NormalizationJobError(
            "Resolve every confirmation item and click Complete cleaning before downloading."
        )
    records = db.query(
        "SELECT order_id, customer_name, customer_id, quantity, unit, unit_price, amount,"
        " order_date, source_file, source_row FROM normalized_records"
        " WHERE batch_id = ? AND is_primary = 1 ORDER BY order_id, source_file, source_row",
        (batch["id"],),
    )
    changes = db.query(
        "SELECT order_id, field, original_value, new_value, reason, method, source_file,"
        " source_row, created_at FROM normalization_changes WHERE batch_id = ?"
        " ORDER BY source_file, source_row, field",
        (batch["id"],),
    )
    issues = db.query(
        "SELECT issue_type, order_id, source_file, source_row, field, original_value,"
        " suggested_value, confidence, reason, status, skip_reason FROM normalization_issues"
        " WHERE batch_id = ? AND status IN ('unresolved', 'skipped')"
        " ORDER BY source_file, source_row, issue_type",
        (batch["id"],),
    )
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    normalized_sheet = workbook.active
    normalized_sheet.title = "normalized"
    normalized_headers = [
        "order_id", "customer_name", "customer_id", "quantity", "unit", "unit_price",
        "amount", "order_date", "source_file", "source_row",
    ]
    normalized_sheet.append(normalized_headers)
    for row in records:
        normalized_sheet.append([row.get(header) for header in normalized_headers])

    changes_sheet = workbook.create_sheet("changes")
    change_headers = [
        "order_id", "field", "original_value", "new_value", "reason", "method",
        "source_file", "source_row", "changed_at",
    ]
    changes_sheet.append(change_headers)
    for row in changes:
        changes_sheet.append(
            [
                row["order_id"],
                row["field"],
                row["original_value"],
                row["new_value"],
                row["reason"],
                row["method"],
                row["source_file"],
                row["source_row"],
                row["created_at"],
            ]
        )

    unresolved_sheet = workbook.create_sheet("unresolved")
    unresolved_headers = [
        "issue_type", "order_id", "source_file", "source_row", "field", "original_value",
        "suggested_value", "confidence", "reason", "status",
    ]
    unresolved_sheet.append(unresolved_headers)
    for row in issues:
        payload = dict(row)
        if payload.get("skip_reason"):
            payload["reason"] = (
                f"{payload.get('reason') or ''} Human skip: {payload['skip_reason']}".strip()
            )
        unresolved_sheet.append([payload.get(header) for header in unresolved_headers])

    header_fill = PatternFill("solid", fgColor="E7F2EF")
    for sheet in (normalized_sheet, changes_sheet, unresolved_sheet):
        sheet.freeze_panes = "A2"
        for cell in sheet[1]:
            cell.font = Font(bold=True)
            cell.fill = header_fill
            cell.alignment = Alignment(vertical="center")
        for index, column in enumerate(sheet.columns, start=1):
            width = min(48, max(12, max(len(str(cell.value or "")) for cell in column) + 2))
            sheet.column_dimensions[get_column_letter(index)].width = width
    from io import BytesIO

    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def download_filename(prefix: str = "FlowRemote_normalized") -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"


def summary_payload(db: Database, task_id: str) -> dict[str, Any] | None:
    snapshot = normalization_snapshot(db, task_id)
    if snapshot is None:
        return None
    batch = get_batch(db, task_id)
    issues = db.query(
        "SELECT issue_type, COUNT(*) AS n FROM normalization_issues WHERE batch_id = ?"
        " AND status = 'unresolved' GROUP BY issue_type ORDER BY issue_type",
        (batch["id"],),
    )
    snapshot["issue_types"] = {row["issue_type"]: int(row["n"]) for row in issues}
    return snapshot
