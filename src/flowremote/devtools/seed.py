"""Seed the local demonstration data for TASK-1001.

Run from the project root:

    python src\\flowremote\\devtools\\seed.py --reset --verify

It creates three things:

    data/seed/customer_registry.csv   the registry the suggestion step matches ids in
    data/seed/Orders_September.xlsx   the 100 order source workbook from the storyboard
    data/runtime/flowremote.db        six tables, one task, 100 records, 12 exceptions

The numbers are fixed, so the demonstration always reproduces the report:
100 input, 88 passed, 12 flagged (8 matchable, 3 without a suggestion, 1
unreliable), 0 decisions, 0 approvals.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

# Allow "python src/flowremote/devtools/seed.py" without installing the package.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flowremote.control_plane.db import PROJECT_ROOT, Database, utc_now  # noqa: E402
from flowremote.control_plane.auth import hash_password  # noqa: E402
from flowremote.devtools.xlsx_writer import write_xlsx  # noqa: E402

TASK_ID = "TASK-1001"
WORKFLOW = "Order Data Validation & Sync"
SOURCE_FILE = "Orders_September.xlsx"
SOURCE_LOCATION = "Company Workspace"
PRIMARY_TARGET = "OA - Order Administration"
SECONDARY_TARGET = "BI - Business Intelligence"
OPERATOR_EMAIL = "alex.morgan@example.com"
ADMIN_EMAIL = "admin@example.com"
DEMO_PASSWORD = "flowremote-demo"
SEED = 20260930
BATCH_SIZE = 100

# Which order lines carry which problem. Fixed for reproducibility.
MISSING_CUSTOMER_ID = [5, 18, 23, 37, 44, 52, 61, 78]
MISSING_QUANTITY = [9, 33, 81]
MISSING_NAME_AND_ID = [99]

FIRST_NAMES = ["Alex", "Mia", "Leo", "Wei", "Mei", "Nora", "Omar", "Priya", "Jonas", "Elena",
               "Karim", "Sofia", "Tomas", "Hana", "Ivan", "Lena", "Marco", "Nadia", "Pablo", "Rina"]
LAST_NAMES = ["Morgan", "Chen", "Park", "Silva", "Novak", "Khan", "Okafor", "Bauer", "Rossi",
              "Tanaka", "Lopez", "Weber", "Haddad", "Fischer", "Costa", "Yamada", "Petrov",
              "Andersen", "Moreau", "Ali"]


def build_registry(count: int = 120) -> list[dict]:
    """One unique full name per customer, so a name match is unambiguous."""
    rng = random.Random(SEED + 1)
    pairs = [(first, last) for first in FIRST_NAMES for last in LAST_NAMES]
    rng.shuffle(pairs)
    registry = []
    for index in range(count):
        first, last = pairs[index]
        registry.append(
            {
                "customer_id": f"C-{1001 + index}",
                "customer_name": f"{first} {last}",
                "region": rng.choice(["North", "South", "East", "West"]),
                "tier": rng.choice(["standard", "priority"]),
            }
        )
    return registry


def build_orders(registry: list[dict]) -> list[dict]:
    rng = random.Random(SEED)
    orders = []
    for number in range(1, BATCH_SIZE + 1):
        customer = registry[(number * 7) % len(registry)]
        quantity = rng.randint(1, 50)
        unit_price = round(rng.uniform(5, 250), 2)
        order = {
            "order_id": f"ORD-{number:03d}",
            "customer_name": customer["customer_name"],
            "customer_id": customer["customer_id"],
            "quantity": quantity,
            "unit_price": unit_price,
            "amount": round(quantity * unit_price, 2),
            "order_date": f"2026-09-{rng.randint(1, 30):02d}",
        }
        if number in MISSING_CUSTOMER_ID:
            order["customer_id"] = None
        if number in MISSING_QUANTITY:
            order["quantity"] = None
            order["amount"] = None
        if number in MISSING_NAME_AND_ID:
            order["customer_name"] = None
            order["customer_id"] = None
        orders.append(order)
    return orders


def find_customer(registry: list[dict], name: str | None) -> str | None:
    if not name:
        return None
    matches = [row["customer_id"] for row in registry if row["customer_name"] == name]
    return matches[0] if len(matches) == 1 else None


def build_exceptions(orders: list[dict], registry: list[dict]) -> list[dict]:
    """One exception per flagged order, with the storyboard's wording."""
    flagged = [order for order in orders if order["customer_id"] is None
               or order["quantity"] is None or order["customer_name"] is None]
    exceptions = []
    for index, order in enumerate(flagged, start=1):
        number = int(order["order_id"].split("-")[1])
        if number in MISSING_NAME_AND_ID:
            issue = "Missing Name + ID"
            fields = "customer_name, customer_id"
            original = "(both blank)"
            suggestion = "Unreliable - skip recommended"
            confidence = 0.68
            reason = "Multiple possible matches, none above confidence threshold."
        elif number in MISSING_QUANTITY:
            issue = "Missing Quantity"
            fields = "quantity"
            original = "(blank)"
            suggestion = None
            confidence = None
            reason = "No historical data available for this order line quantity."
        else:
            issue = "Missing Customer ID"
            fields = "customer_id"
            original = "(blank)"
            suggestion = find_customer(registry, order["customer_name"])
            confidence = 0.98
            reason = "AI unique match from customer registry."
        exceptions.append(
            {
                "id": f"EXC-{index:04d}",
                "task_id": TASK_ID,
                "record_id": order["order_id"],
                "issue": issue,
                "flagged_fields": fields,
                "original_value": original,
                "suggestion": suggestion,
                "confidence": confidence,
                "reason": reason,
                "status": "unresolved",
                "created_at": utc_now(),
            }
        )
    return exceptions


def write_registry_file(registry: list[dict]) -> Path:
    path = PROJECT_ROOT / "data" / "seed" / "customer_registry.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["customer_id", "customer_name", "region", "tier"])
        writer.writeheader()
        writer.writerows(registry)
    return path


def write_workbook(orders: list[dict]) -> Path:
    path = PROJECT_ROOT / "data" / "seed" / SOURCE_FILE
    header = ["order_id", "customer_name", "customer_id", "quantity", "unit_price",
              "amount", "order_date"]
    rows = [[order[column] for column in header] for order in orders]
    write_xlsx(path, "Orders", header, rows)
    return path


def wipe_task(db: Database) -> None:
    """Make the seed re-runnable: remove this task's rows and its children."""
    with db.transaction():
        db.execute(
            "DELETE FROM decisions WHERE exception_id IN "
            "(SELECT id FROM exceptions WHERE task_id = ?)",
            (TASK_ID,),
        )
        db.execute("DELETE FROM approvals WHERE task_id = ?", (TASK_ID,))
        db.execute("DELETE FROM exceptions WHERE task_id = ?", (TASK_ID,))
        db.execute("DELETE FROM source_records WHERE task_id = ?", (TASK_ID,))
        db.execute("DELETE FROM tasks WHERE id = ?", (TASK_ID,))
        db.execute(
            "DELETE FROM users WHERE email IN (?, ?)", (OPERATOR_EMAIL, ADMIN_EMAIL)
        )


def seed_database(db: Database, orders: list[dict], exceptions: list[dict]) -> None:
    now = utc_now()
    wipe_task(db)
    with db.transaction():
        db.execute(
            "INSERT INTO users (id, name, email, role, device, password_hash, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("USR-0001", "Alex Morgan", OPERATOR_EMAIL, "operator", "Office-PC-01",
             hash_password(DEMO_PASSWORD), now),
        )
        db.execute(
            "INSERT INTO users (id, name, email, role, device, password_hash, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("USR-0002", "Ada Admin", ADMIN_EMAIL, "admin", "Office-PC-01",
             hash_password(DEMO_PASSWORD), now),
        )
        db.execute(
            "INSERT INTO tasks (id, workflow, batch_size, status, source_file, source_location,"
            " primary_target, secondary_target, owner_id, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (TASK_ID, WORKFLOW, BATCH_SIZE, "review_required", SOURCE_FILE, SOURCE_LOCATION,
             PRIMARY_TARGET, SECONDARY_TARGET, "USR-0001", now, now),
        )
        flagged_ids = {exception["record_id"] for exception in exceptions}
        for order in orders:
            db.execute(
                "INSERT INTO source_records (task_id, record_id, customer_name, customer_id,"
                " quantity, unit_price, amount, order_date, outcome) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (TASK_ID, order["order_id"], order["customer_name"], order["customer_id"],
                 order["quantity"], order["unit_price"], order["amount"], order["order_date"],
                 "flagged" if order["order_id"] in flagged_ids else "passed"),
            )
        for exception in exceptions:
            db.execute(
                "INSERT INTO exceptions (id, task_id, record_id, issue, flagged_fields,"
                " original_value, suggestion, confidence, reason, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (exception["id"], exception["task_id"], exception["record_id"], exception["issue"],
                 exception["flagged_fields"], exception["original_value"], exception["suggestion"],
                 exception["confidence"], exception["reason"], exception["status"],
                 exception["created_at"]),
            )


def verify(db: Database) -> bool:
    total = db.scalar("SELECT COUNT(*) FROM source_records WHERE task_id = ?", (TASK_ID,), 0)
    passed = db.scalar(
        "SELECT COUNT(*) FROM source_records WHERE task_id = ? AND outcome = 'passed'", (TASK_ID,), 0
    )
    flagged = db.scalar(
        "SELECT COUNT(*) FROM source_records WHERE task_id = ? AND outcome = 'flagged'", (TASK_ID,), 0
    )
    unresolved = db.scalar(
        "SELECT COUNT(*) FROM exceptions WHERE task_id = ? AND status = 'unresolved'", (TASK_ID,), 0
    )
    decisions = db.scalar(
        "SELECT COUNT(*) FROM decisions WHERE exception_id IN "
        "(SELECT id FROM exceptions WHERE task_id = ?)",
        (TASK_ID,),
        0,
    )
    approvals = db.scalar("SELECT COUNT(*) FROM approvals WHERE task_id = ?", (TASK_ID,), 0)
    task = db.query("SELECT status, batch_size FROM tasks WHERE id = ?", (TASK_ID,))

    print(f"task            : {TASK_ID} status={task[0]['status']} batch={task[0]['batch_size']}"
          if task else f"task            : {TASK_ID} MISSING")
    print(f"source records  : {total} total ({passed} passed, {flagged} flagged)")
    print(f"exceptions      : {unresolved} unresolved")
    print(f"decisions       : {decisions}")
    print(f"approvals       : {approvals}")
    print(f"gate            : unresolved={unresolved} -> approval "
          f"{'blocked' if unresolved else 'allowed'}")

    print("\nthe three storyboard cases")
    rows = db.query(
        "SELECT record_id, issue, suggestion, confidence, reason FROM exceptions"
        " WHERE record_id IN ('ORD-052', 'ORD-081', 'ORD-099') ORDER BY record_id"
    )
    for row in rows:
        suggestion = row["suggestion"] or "(no suggestion)"
        confidence = "-" if row["confidence"] is None else f"{row['confidence']:.2f}"
        print(f"  {row['record_id']}  {row['issue']:<22} {suggestion:<30} {confidence:>5}"
              f"  {row['reason']}")

    expected = (total == BATCH_SIZE and passed == 88 and flagged == 12 and unresolved == 12
                and decisions == 0 and approvals == 0)
    print("\nstoryboard check: 100 input / 88 passed / 12 exceptions -> "
          + ("OK" if expected else "NOT MATCHING, look at the numbers above"))
    return expected


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the TASK-1001 demonstration data.")
    parser.add_argument("--reset", action="store_true",
                        help="delete the SQLite file first, then rebuild everything")
    parser.add_argument("--verify", action="store_true",
                        help="print the counts after seeding (default when seeding)")
    parser.add_argument("--verify-only", action="store_true",
                        help="print the counts without changing anything")
    parser.add_argument("--db", default=None, help="override DATABASE_URL")
    args = parser.parse_args()

    db = Database(args.db)
    if args.reset and db.engine == "sqlite" and not db.is_memory:
        target = db.sqlite_path()
        for path in (target, Path(str(target) + "-wal"), Path(str(target) + "-shm")):
            if path.exists():
                path.unlink()
        print(f"removed {target}")

    db.connect()
    try:
        applied = db.apply_migrations()
        if applied:
            print("migrations: " + ", ".join(applied))
        if args.verify_only:
            return 0 if verify(db) else 1

        registry = build_registry()
        orders = build_orders(registry)
        exceptions = build_exceptions(orders, registry)
        registry_path = write_registry_file(registry)
        workbook_path = write_workbook(orders)
        seed_database(db, orders, exceptions)

        print(f"registry  : {registry_path.relative_to(PROJECT_ROOT)} ({len(registry)} customers)")
        print(f"workbook  : {workbook_path.relative_to(PROJECT_ROOT)} ({len(orders)} orders)")
        print(f"database  : {db.url}\n")
        print("seeded 1 task, 100 source records, 12 exceptions, 0 decisions, 0 approvals\n")
        print(f"demo accounts (password: {DEMO_PASSWORD})")
        print(f"  operator : {OPERATOR_EMAIL}")
        print(f"  admin    : {ADMIN_EMAIL}\n")
        return 0 if verify(db) else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
