"""Registered accounts persist in the selected database across app restarts."""

from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from flowremote.api.app import create_app
from flowremote.control_plane.db import PROJECT_ROOT, Database


def test_registered_user_can_log_in_after_application_restart():
    root = PROJECT_ROOT / "data" / "runtime" / "tests"
    root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=root) as temporary:
        folder = Path(temporary)
        url = f"sqlite:///{(folder / 'persistent-users.db').as_posix()}"
        secret = "persistent-user-test-secret"
        app_one = create_app(url, secret, folder / "uploads")
        with TestClient(app_one) as client:
            response = client.post(
                "/signup",
                data={
                    "name": "Persistent User",
                    "email": "persistent@example.com",
                    "password": "password123",
                    "password_again": "password123",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert app_one.state.storage.mode == "local"

        with Database(url) as db:
            row = db.query(
                "SELECT email, password_hash FROM users WHERE email = ?",
                ("persistent@example.com",),
            )[0]
        assert row["password_hash"] != "password123"
        assert row["password_hash"].startswith("pbkdf2_sha256$")

        app_two = create_app(url, secret, folder / "uploads")
        with TestClient(app_two) as restarted:
            login = restarted.post(
                "/login",
                data={"email": "persistent@example.com", "password": "password123"},
                follow_redirects=False,
            )
            assert login.status_code == 303
            page = restarted.get("/")
            assert page.status_code == 200
            assert "Persistent User" in page.text
            assert "No tasks yet" in page.text
