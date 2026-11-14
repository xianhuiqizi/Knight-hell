"""Build the six-file Demo Day pack, account and preloaded batch.

Run from the repository root:

    python src/flowremote/devtools/seed_demoday.py --reset

This is deterministic: the same six files, 36 synthetic orders, 174 source
rows and exactly six confirmation items are produced every time. No real
person, phone number or company data is used.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from shutil import rmtree

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flowremote.control_plane.auth import AccountError, create_user, get_user_row_by_email
from flowremote.control_plane.db import (
    PROJECT_ROOT,
    RUNTIME_ROOT,
    Database,
)
from flowremote.control_plane.normalization import run_full_normalization
from flowremote.control_plane.normalization_jobs import (
    create_normalization_task,
    get_batch,
    recognize_normalization_task,
)
from flowremote.devtools.demoday_data import (
    demo_sources,
    write_customer_registry,
    write_demo_files,
)

DEMO_EMAIL = "demo@flowremote.dev"
DEMO_PASSWORD = "DemoDay2026!"
DEMO_NAME = "Demo Day Operator"
DEMO_TASK_NAME = "Demo Day data cleanup"
DEMO_DIR = PROJECT_ROOT / "data" / "demoday"
UPLOAD_DIR = RUNTIME_ROOT / "uploads"
EXPECTED_SUMMARY = {
    "files_total": 6,
    "files_ok": 6,
    "raw_records": 174,
    "normalized_records": 36,
    "issues": 6,
    "missing_values": 2,
    "unit_conflicts": 2,
    "cross_file_conflicts": 2,
    "file_errors": 0,
}


def _delete_sqlite(db: Database) -> None:
    if db.engine != "sqlite" or db.is_memory:
        return
    target = db.sqlite_path()
    for path in (target, Path(str(target) + "-wal"), Path(str(target) + "-shm")):
        path.unlink(missing_ok=True)
    print(f"removed database : {target}")


def _reset_uploads() -> None:
    if UPLOAD_DIR.exists():
        rmtree(UPLOAD_DIR)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def verify_files() -> bool:
    result = run_full_normalization(demo_sources())
    summary = result["summary"]
    issue_counts = Counter(issue["issue_type"] for issue in result["issues"])
    print("file-level checks")
    for entry in result["files"]:
        print(
            f"  {entry['filename']:<38} {entry['status']:<10}"
            f" sheet={entry['worksheet']!r:<26} rows={entry['row_count']:<3}"
            f" fields={entry['field_count']}"
        )
    print("\nissues found")
    for name, count in sorted(issue_counts.items()):
        print(f"  {name:<22} {count}")
    ok = all(summary[key] == value for key, value in EXPECTED_SUMMARY.items())
    print(
        "\npack check: 6/6 files, 174 raw rows, 36 merged records, 6 issues"
        " (missing 2, unit 2, cross-file 2) -> " + ("OK" if ok else "NOT MATCHING")
    )
    return ok


def seed_database(db: Database) -> str:
    demo_files = demo_sources()
    demo_files_paths = write_demo_files(DEMO_DIR)
    registry_path = write_customer_registry(DEMO_DIR / "customer_registry.csv")
    print(f"demo files      : {len(demo_files_paths)} written to {DEMO_DIR}")
    print(f"demo registry   : {registry_path}")

    existing = get_user_row_by_email(db, DEMO_EMAIL)
    if existing:
        user_id = existing["id"]
        print(f"account         : reusing {DEMO_EMAIL} ({user_id})")
    else:
        try:
            row = create_user(
                db,
                name=DEMO_NAME,
                email=DEMO_EMAIL,
                password=DEMO_PASSWORD,
                role="operator",
                device="Demo Day laptop",
                user_id="USR-DEMO01",
                onboarding_completed=True,
            )
        except AccountError as exc:
            raise SystemExit(f"could not create demo account: {exc}") from exc
        user_id = row["id"]
        print(f"account created : {DEMO_EMAIL} ({user_id})")

    # Keep a pre-uploaded fallback batch. The live script still creates a new
    # session; this batch is the recovery path if the file picker misbehaves.
    existing_task = db.query(
        "SELECT id FROM tasks WHERE owner_id = ? AND workflow = ? AND task_mode = 'normalize'",
        (user_id, DEMO_TASK_NAME),
    )
    if existing_task:
        task_id = existing_task[0]["id"]
        print(f"batch           : reusing {task_id}")
    else:
        task_id = create_normalization_task(
            db,
            UPLOAD_DIR,
            user_id,
            DEMO_TASK_NAME,
            demo_files,
        )
        recognize_normalization_task(db, task_id, UPLOAD_DIR)
        print(f"batch created   : {task_id} (6 files recognized, ready to start)")
    return task_id


def verify_database(db: Database, task_id: str) -> bool:
    user = get_user_row_by_email(db, DEMO_EMAIL)
    batch = get_batch(db, task_id)
    file_count = db.scalar(
        "SELECT COUNT(*) FROM normalization_files WHERE task_id = ?", (task_id,), 0
    )
    recognized = db.scalar(
        "SELECT COUNT(*) FROM normalization_files WHERE task_id = ? AND status = 'mapped'",
        (task_id,),
        0,
    )
    raw_rows = db.scalar(
        "SELECT raw_records FROM normalization_batches WHERE task_id = ?", (task_id,), 0
    )
    print(f"\naccount         : {user['email'] if user else 'MISSING'} ({user['id'] if user else '—'})")
    print(f"fallback batch  : {task_id}")
    print(f"batch status    : {batch['status'] if batch else 'MISSING'}")
    print(f"uploaded files  : {file_count} ({recognized} recognized, {raw_rows} rows)")
    ok = (
        bool(user)
        and bool(batch)
        and file_count == 6
        and recognized == 6
        and int(raw_rows or 0) == 174
    )
    print("database check  : demo account + 6/6 recognized batch -> "
          + ("OK" if ok else "NOT MATCHING"))
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the ENT207TC Demo Day account and batch.")
    parser.add_argument("--reset", action="store_true", help="delete the SQLite database first")
    parser.add_argument("--verify-only", action="store_true", help="only verify the demo pack")
    parser.add_argument("--db", default=None, help="override the database URL")
    args = parser.parse_args()

    if args.verify_only:
        return 0 if verify_files() else 1

    db = Database(args.db)
    if args.reset:
        _delete_sqlite(db)
        _reset_uploads()
    db.connect()
    try:
        applied = db.apply_migrations()
        if applied:
            print("migrations      : " + ", ".join(applied))
        print()
        if not verify_files():
            return 1
        print()
        task_id = seed_database(db)
        print()
        if not verify_database(db, task_id):
            return 1
        print(f"\nDemo login      : {DEMO_EMAIL} / {DEMO_PASSWORD}")
        print("Open            : http://127.0.0.1:8000/demo")
        print("Demo files      : " + str(DEMO_DIR))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
