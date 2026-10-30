"""Run a self-contained Feature 3 demonstration.

The demo starts the real FastAPI application with an isolated temporary
database, a small synthetic order batch, and the offline suggestion provider.
It never calls an external AI API and never touches the development database.

Examples:

    .\\.venv\\Scripts\\python.exe demo\\run_feature3_demo.py
    .\\.venv\\Scripts\\python.exe demo\\run_feature3_demo.py --no-browser
    .\\.venv\\Scripts\\python.exe demo\\run_feature3_demo.py --check
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import webbrowser
from pathlib import Path

DEMO_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = DEMO_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from fastapi.testclient import TestClient

from flowremote.api.app import create_app
from flowremote.control_plane.auth import create_user
from flowremote.control_plane.db import Database
from flowremote.control_plane.order_validation import (
    FIELDS,
    analyse_rows,
    save_analysis,
)

TASK_ID = "TASK-FEATURE3"
EMAIL = "alex.morgan@example.com"
PASSWORD = "123456"
SESSION_SECRET = "feature3-local-demo-secret"


def _write_registry(path: Path) -> None:
    path.write_text(
        "customer_id,customer_name,region,tier\n"
        "C-1005,Alex Morgan,North,priority\n"
        "C-1006,Mia Chen,East,standard\n",
        encoding="utf-8",
    )


def seed_demo(db: Database) -> None:
    db.apply_migrations()
    create_user(
        db,
        name="Alex Morgan",
        email=EMAIL,
        password=PASSWORD,
        user_id="USR-FEATURE3",
    )
    now = "2026-10-30T12:00:00Z"
    db.execute(
        "INSERT INTO tasks (id, workflow, batch_size, status, source_file,"
        " source_location, primary_target, secondary_target, owner_id,"
        " created_at, updated_at) VALUES (?, ?, ?, 'ready', ?, ?, ?, ?, ?, ?, ?)",
        (
            TASK_ID,
            "Feature 3 AI Exception Review",
            3,
            "Feature3_orders.xlsx",
            "Bundled demo data",
            "OA - Order Administration",
            "BI - Business Intelligence",
            "USR-FEATURE3",
            now,
            now,
        ),
    )
    rows = [
        (
            2,
            ["DEMO-001", "Alex Morgan", "", 2, 10, 20, "2026-10-30"],
        ),
        (
            3,
            ["DEMO-002", "Mia Chen", "C-1006", "", 15, "", "2026-10-30"],
        ),
        (
            4,
            ["DEMO-003", "Mia Chen", "C-1006", 3, 20, 60, "2026-10-30"],
        ),
    ]
    results, summary = analyse_rows(FIELDS, rows)
    with db.transaction():
        save_analysis(db, TASK_ID, 1, results, summary)


def build_app(folder: Path):
    registry = folder / "customer_registry.csv"
    _write_registry(registry)
    url = f"sqlite:///{(folder / 'feature3.db').as_posix()}"
    with Database(url) as db:
        seed_demo(db)
    return create_app(
        database_url=url,
        session_secret=SESSION_SECRET,
        upload_dir=folder / "uploads",
        customer_registry=registry,
    )


def run_check(app) -> int:
    with TestClient(app) as client:
        login = client.post(
            "/login",
            data={"email": EMAIL, "password": PASSWORD},
            follow_redirects=False,
        )
        settings = client.post(
            "/settings/ai",
            data={
                "provider": "offline",
                "model": "grounded-rules-v1",
                "base_url": "",
                "api_key": "",
            },
            headers={"Accept": "application/json"},
        )
        suggestion = client.post(
            f"/tasks/{TASK_ID}/exceptions/ORD-001/suggestions",
            data={"request_id": "FEATURE3-DEMO-CHECK"},
            follow_redirects=False,
        )
        page = client.get(f"/tasks/{TASK_ID}")
        accept = client.post(
            f"/tasks/{TASK_ID}/exceptions/ORD-001/decisions",
            data={"action": "accept", "decision_id": "FEATURE3-HUMAN-ACCEPT"},
            follow_redirects=False,
        )
        with Database(app.state.database_url) as db:
            exception = db.query(
                "SELECT status, suggestion FROM exceptions WHERE record_id = 'ORD-001'"
            )[0]
            decisions = db.scalar("SELECT COUNT(*) FROM decisions")
            run = db.query(
                "SELECT status, provider, model FROM ai_suggestion_runs"
                " ORDER BY created_at DESC LIMIT 1"
            )[0]

    checks = {
        "login": login.status_code == 303,
        "settings_saved": settings.status_code == 200 and settings.json()["ok"],
        "suggestion_generated": suggestion.status_code == 303,
        "AI_panel_rendered": "AI suggestion" in page.text,
        "run_completed": run["status"] == "completed",
        "offline_provider": run["provider"] == "offline",
        "human_accept": accept.status_code == 303,
        "exception_accepted": exception["status"] == "accepted",
        "one_decision": decisions == 1,
    }
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}  {name}")
    print(f"\nrun: {run}")
    print(f"exception: {exception}")
    return 0 if all(checks.values()) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the FlowRemote Feature 3 demo.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--check", action="store_true", help="Run automated checks and exit.")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix=".feature3-demo-", dir=DEMO_ROOT) as temporary:
        app = build_app(Path(temporary))
        if args.check:
            return run_check(app)

        url = f"http://127.0.0.1:{args.port}"
        print("FlowRemote Feature 3 demo")
        print(f"URL      : {url}")
        print(f"Email    : {EMAIL}")
        print(f"Password : {PASSWORD}")
        print("Data     : temporary and isolated; removed when this process exits")
        print("AI       : offline provider, no external API call")
        print("\nPress Ctrl+C to stop.\n")
        if not args.no_browser:
            webbrowser.open(url)

        import uvicorn

        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
