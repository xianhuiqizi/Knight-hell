"""FlowRemote Windows demo launcher.

The packaged executable starts the local server, prepares isolated demo data,
opens the browser and keeps a small control window for lifecycle management.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import socket
import sys
import threading
import time
import traceback
import urllib.request
import uuid
import webbrowser
from pathlib import Path


def _source_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]


SOURCE_ROOT = _source_root()
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(SOURCE_ROOT / "src"))

APP_NAME = "FlowRemoteDemo"
VERSION = "0.10.0"


def data_root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    root = Path(os.environ["FLOWREMOTE_DATA_DIR"]) if os.environ.get("FLOWREMOTE_DATA_DIR") else base / APP_NAME
    for folder in ("runtime", "runtime/uploads", "runtime/targets", "runtime/logs", "seed"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    return root


DEMO_DATA = data_root()
os.environ.setdefault("FLOWREMOTE_DATA_DIR", str(DEMO_DATA))
os.environ.setdefault(
    "FLOWREMOTE_DATABASE_URL",
    f"sqlite:///{(DEMO_DATA / 'runtime' / 'flowremote.db').as_posix()}",
)
os.environ.setdefault(
    "FLOWREMOTE_UPLOAD_DIR",
    str(DEMO_DATA / "runtime" / "uploads"),
)
os.environ.setdefault(
    "FLOWREMOTE_CUSTOMER_REGISTRY",
    str(DEMO_DATA / "seed" / "customer_registry.csv"),
)
os.environ.setdefault("FLOWREMOTE_AI_PROVIDER", "offline")
os.environ.setdefault("FLOWREMOTE_DEMO_MODE", "1")


def log(message: str) -> None:
    path = DEMO_DATA / "runtime" / "logs" / "launcher.log"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


def prepare_demo_tree() -> None:
    from flowremote.control_plane.db import Database
    from flowremote.devtools.seed import (
        build_exceptions,
        build_orders,
        build_registry,
        seed_database,
        write_registry_file,
        write_workbook,
    )

    with Database() as db:
        db.apply_migrations()
        if not db.scalar("SELECT COUNT(*) FROM tasks WHERE id = 'TASK-1001'", default=0):
            registry = build_registry()
            orders = build_orders(registry)
            exceptions = build_exceptions(orders, registry)
            write_registry_file(registry)
            write_workbook(orders)
            seed_database(db, orders, exceptions)
        from flowremote.control_plane.auth import create_user, get_user_row_by_email
        from flowremote.control_plane.normalization_jobs import (
            create_normalization_task,
            recognize_normalization_task,
        )
        from flowremote.devtools.demoday_data import demo_sources, write_demo_files
        account = get_user_row_by_email(db, "demo@flowremote.dev")
        if not account:
            account = create_user(db, name="Demo Operator", email="demo@flowremote.dev",
                                  password="DemoDay2026!", onboarding_completed=True)
        if not db.scalar("SELECT COUNT(*) FROM tasks WHERE owner_id = ? AND task_mode = 'normalize'",
                         (account["id"],), 0):
            task = create_normalization_task(db, Path(os.environ["FLOWREMOTE_UPLOAD_DIR"]),
                                             account["id"], "Example: monthly order cleanup",
                                             list(demo_sources()))
            recognize_normalization_task(db, task, Path(os.environ["FLOWREMOTE_UPLOAD_DIR"]))
        write_demo_files(DEMO_DATA / "examples")
    log("Demo data prepared")


def health(url: str, timeout: float = 0.5) -> dict | None:
    try:
        with urllib.request.urlopen(url + "/health", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload if payload.get("app") == "ok" else None
    except (OSError, ValueError):
        return None


def choose_port(start: int = 8765, end: int = 8780) -> tuple[int, str | None]:
    for port in range(start, end + 1):
        url = f"http://127.0.0.1:{port}"
        running = health(url)
        if running:
            # A previous demo may still be running. Reuse only this version,
            # otherwise start on another port so the new EXE opens the new UI.
            if running.get("version") == VERSION:
                return port, url
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port, None
    raise RuntimeError("No local port is available between 8765 and 8780.")


def create_application():
    from flowremote.api.app import create_app

    return create_app()


def start_server(app, port: int):
    import uvicorn

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_config=None,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="flowremote-api", daemon=True)
    thread.start()
    directory = DEMO_DATA / "runtime" / "logs" / "app.log"
    log(f"API starting on http://127.0.0.1:{port}; log={directory}")
    return server, thread


def wait_until_ready(url: str, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if health(url):
            return True
        time.sleep(0.2)
    return False


def smoke_test() -> int:
    from fastapi.testclient import TestClient

    prepare_demo_tree()
    app = create_application()
    with TestClient(app) as client:
        demo_page = client.get("/demo")
        login = client.post(
            "/login",
            data={"email": "alex.morgan@example.com", "password": "123456"},
            follow_redirects=False,
        )
        dashboard = client.get("/")
        settings = client.get("/settings")
        client.post("/logout")
        email = f"smoke-{uuid.uuid4().hex[:10]}@example.com"
        signup = client.post(
            "/signup",
            data={
                "name": "Smoke User",
                "email": email,
                "password": "password123",
                "password_again": "password123",
            },
            follow_redirects=False,
        )
        onboarding = client.get("/onboarding")
        finish = client.post(
            "/onboarding",
            data={
                "provider": "offline",
                "model": "grounded-rules-v1",
                "base_url": "",
                "api_key": "",
                "ai_enabled": "1",
                "rpa_enabled": "1",
                "max_records_per_task": "10000",
                "ai_daily_limit": "100",
                "rpa_daily_limit": "10",
                "connection_local_excel": "1",
                "connection_local_http": "1",
            },
            follow_redirects=False,
        )
        results = {
            "health": client.get("/health").status_code,
            "demo": demo_page.status_code,
            "login": login.status_code,
            "dashboard": dashboard.status_code,
            "settings": settings.status_code,
            "signup": signup.status_code,
            "onboarding": onboarding.status_code,
            "onboarding_complete": finish.status_code,
            "guide_script": client.get("/static/guide.js").status_code,
            "light_theme": client.get("/static/app.css").status_code,
        }
        example = client.post("/tasks/example", follow_redirects=False)
        task_url = example.headers.get("location", "")
        results["example"] = example.status_code
        if task_url:
            client.post(task_url + "/normalize/start", follow_redirects=False)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                state = client.get(task_url + "/normalize/status").json()
                if state["status"] != "running":
                    break
                time.sleep(0.1)
            from flowremote.control_plane.db import Database
            with Database() as db:
                issues = db.query("SELECT id FROM normalization_issues WHERE task_id = ?"
                                  " AND status = 'unresolved'", (task_url.rsplit("/", 1)[-1],))
            for issue in issues:
                base = task_url + "/normalize/issues/" + issue["id"]
                advice = client.post(base + "/ai-suggest").json()
                decision = client.post(base + "/confirm", json={
                    "decision_id": uuid.uuid4().hex, "changes": advice.get("fields", {}),
                })
                results["review_" + issue["id"]] = decision.status_code
            results["finish"] = client.post(task_url + "/normalize/finish", follow_redirects=False).status_code
            results["preview"] = client.get(task_url + "/normalize/preview").status_code
            download = client.get(task_url + "/normalize/download")
            results["download"] = download.status_code
            if download.status_code == 200:
                from io import BytesIO

                from openpyxl import load_workbook
                workbook = load_workbook(BytesIO(download.content))
                results["workbook"] = 200 if workbook.sheetnames == ["normalized", "changes", "unresolved"] and workbook["normalized"].max_row == 37 else 500
                workbook.close()
    passed = all(code in (200, 303) for code in results.values())
    output = {"passed": passed, "version": VERSION, "checks": results}
    target = DEMO_DATA / "runtime" / "logs" / "smoke-result.json"
    target.write_text(json.dumps(output, indent=2), encoding="utf-8")
    log(f"Smoke test: {output}")
    return 0 if passed else 1


def run_window(url: str, server, thread) -> None:
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(f"FlowRemote Demo {VERSION}")
    root.geometry("520x300")
    root.minsize(480, 280)
    root.configure(bg="#f4f7fb")

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"), background="#f4f7fb")
    style.configure("Body.TLabel", font=("Segoe UI", 10), background="#f4f7fb")
    style.configure("Status.TLabel", font=("Segoe UI", 10, "bold"), foreground="#147a68",
                    background="#f4f7fb")

    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="FlowRemote AI-RPA Demo", style="Title.TLabel").pack(anchor="w")
    ttk.Label(
        frame,
        text="Local server, database and browser demo",
        style="Body.TLabel",
    ).pack(anchor="w", pady=(4, 18))
    ttk.Label(frame, text="● Running", style="Status.TLabel").pack(anchor="w")
    ttk.Label(frame, text=url, style="Body.TLabel").pack(anchor="w", pady=(4, 18))
    ttk.Label(
        frame,
        text=(
            "Demo data is stored in:\n"
            f"{DEMO_DATA}\n\n"
            "Close this window to stop the local services."
        ),
        style="Body.TLabel",
    ).pack(anchor="w")

    actions = ttk.Frame(frame)
    actions.pack(fill="x", side="bottom", pady=(18, 0))

    def stop() -> None:
        server.should_exit = True
        thread.join(timeout=5)
        root.destroy()

    ttk.Button(actions, text="Open browser", command=lambda: webbrowser.open(url)).pack(side="left")
    ttk.Button(
        actions,
        text="Open data folder",
        command=lambda: os.startfile(DEMO_DATA),
    ).pack(side="left", padx=8)
    ttk.Button(actions, text="Stop", command=stop).pack(side="right")
    root.protocol("WM_DELETE_WINDOW", stop)
    webbrowser.open(url + "/demo")
    root.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--headless", action="store_true")
    args, _unknown = parser.parse_known_args()
    try:
        prepare_demo_tree()
        if args.smoke_test:
            return smoke_test()

        port, existing = choose_port()
        log(f"Selected port {port}; existing={bool(existing)}")
        if existing:
            webbrowser.open(existing + "/demo")
            return 0

        app = create_application()
        server, thread = start_server(app, port)
        url = f"http://127.0.0.1:{port}"
        if not wait_until_ready(url):
            log("API failed to become healthy")
            server.should_exit = True
            return 1
        if args.no_browser:
            webbrowser.open = lambda _url: False
        if args.headless:
            log(f"Headless server ready at {url}")
            while not server.should_exit:
                time.sleep(0.5)
            return 0
        run_window(url, server, thread)
    except Exception:  # noqa: BLE001 - GUI toolkit errors vary by Windows version.
        log("Launcher failed:\n" + traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
