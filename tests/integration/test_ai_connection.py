"""HTTP tests for the visible AI connection test and offline fallback."""

from __future__ import annotations

import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from flowremote.agent.connection import ConnectionResult
from flowremote.api.app import create_app
from flowremote.control_plane.auth import create_user
from flowremote.control_plane.db import PROJECT_ROOT, Database

SECRET = "ai-connection-test-secret"


@pytest.fixture()
def ai_connection_app(monkeypatch):
    for name in (
        "OPENAI_API_KEY",
        "FLOWREMOTE_DEMO_MODE",
        "FLOWREMOTE_AI_PROVIDER",
        "FLOWREMOTE_AI_MODEL",
        "FLOWREMOTE_AI_BASE_URL",
        "OPENAI_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    root = PROJECT_ROOT / "data" / "runtime" / "tests"
    root.mkdir(parents=True, exist_ok=True)
    temp = TemporaryDirectory(dir=root)
    folder = Path(temp.name)
    url = f"sqlite:///{(folder / 'ai-connection.db').as_posix()}"
    with Database(url) as db:
        db.apply_migrations()
        for name in ("A", "B"):
            create_user(
                db,
                name=name,
                email=f"{name.lower()}@example.com",
                password="password123",
                user_id=name,
            )
    app = create_app(url, SECRET, folder / "uploads")
    with TestClient(app) as client:
        yield app, client, url
    temp.cleanup()


def login(client: TestClient, who: str = "A") -> None:
    response = client.post(
        "/login",
        data={"email": f"{who.lower()}@example.com", "password": "password123"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_default_connection_target_is_deepseek_flash(ai_connection_app):
    _app, client, _url = ai_connection_app
    login(client)
    data = client.get("/settings/ai", headers={"Accept": "application/json"}).json()
    assert data["provider"] == "offline"
    assert data["model"] == "deepseek-flash"
    assert data["base_url"] == "https://api.deepseek.com"
    assert data["key_configured"] is False


def test_connection_requires_sign_in(ai_connection_app):
    _app, client, _url = ai_connection_app
    response = client.post(
        "/settings/ai/test",
        data={"provider": "offline"},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 401


def test_offline_connection_is_saved_and_returns_model_and_latency(ai_connection_app):
    _app, client, url = ai_connection_app
    login(client)
    started = time.perf_counter()
    response = client.post(
        "/settings/ai/test",
        data={"provider": "offline", "model": "", "base_url": "", "api_key": ""},
        headers={"Accept": "application/json"},
    )
    elapsed = time.perf_counter() - started
    assert response.status_code == 200
    assert elapsed < 3
    data = response.json()
    assert data["ok"] is True
    assert data["connected"] is True
    assert data["fallback"] is False
    assert data["provider"] == "offline"
    assert data["model"] == "grounded-rules-v1"
    assert data["latency_ms"] == 0
    assert data["settings"]["provider"] == "offline"
    with Database(url) as db:
        assert db.scalar("SELECT provider FROM ai_settings WHERE user_id = 'A'") == "offline"


def test_openai_success_saves_encrypted_key_and_never_echoes_it(ai_connection_app):
    _app, client, url = ai_connection_app
    login(client)
    key = "sk-test-connection-WXYZ"
    result = ConnectionResult(
        ok=True,
        provider="openai",
        model="demo-model",
        latency_ms=123,
        message="Connected. The model is available.",
    )
    with patch(
        "flowremote.api.routes.ai_settings.probe_connection", return_value=result
    ) as probe:
        response = client.post(
            "/settings/ai/test",
            data={
                "provider": "openai",
                "model": "demo-model",
                "base_url": "https://ai.example.com/v1",
                "api_key": key,
            },
            headers={"Accept": "application/json"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["connected"] is True
    assert data["fallback"] is False
    assert data["provider"] == "openai"
    assert data["model"] == "demo-model"
    assert data["latency_ms"] == 123
    assert data["settings"]["key_hint"] == "••••WXYZ"
    assert data["settings"]["key_source"] == "saved"
    assert key not in response.text
    probe.assert_called_once()
    assert probe.call_args.args[0] == "openai"
    assert probe.call_args.args[3] == key
    with Database(url) as db:
        row = db.query("SELECT * FROM ai_settings WHERE user_id = 'A'")[0]
    assert row["api_key_encrypted"] != key
    assert key not in row["api_key_encrypted"]
    assert row["api_key_hint"] == "WXYZ"
    assert row["provider"] == "openai"
    public = client.get("/settings/ai", headers={"Accept": "application/json"}).json()
    assert key not in str(public)
    assert public["key_hint"] == "••••WXYZ"


def test_saved_key_is_reused_when_the_test_field_is_blank(ai_connection_app):
    _app, client, url = ai_connection_app
    login(client)
    saved_key = "saved-key-ABCD"
    saved = client.post(
        "/settings/ai",
        data={
            "provider": "openai",
            "model": "demo-model",
            "base_url": "https://ai.example.com/v1",
            "api_key": saved_key,
        },
        headers={"Accept": "application/json"},
    )
    assert saved.status_code == 200
    result = ConnectionResult(
        ok=True,
        provider="openai",
        model="demo-model",
        latency_ms=20,
        message="Connected.",
    )
    with patch(
        "flowremote.api.routes.ai_settings.probe_connection", return_value=result
    ) as probe:
        response = client.post(
            "/settings/ai/test",
            data={
                "provider": "openai",
                "model": "demo-model",
                "base_url": "https://ai.example.com/v1",
                "api_key": "",
            },
            headers={"Accept": "application/json"},
        )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert probe.call_args.args[3] == saved_key
    with Database(url) as db:
        assert db.scalar("SELECT api_key_hint FROM ai_settings WHERE user_id = 'A'") == "ABCD"


def test_invalid_key_auto_switches_to_offline_and_is_readable(ai_connection_app):
    _app, client, url = ai_connection_app
    login(client)
    key = "wrong-key-DEFG"
    result = ConnectionResult(
        ok=False,
        provider="openai",
        model=None,
        latency_ms=48,
        error_code="invalid_key",
        message="The AI provider rejected this API key.",
        action="Paste a valid key, or switch to Offline Demo AI.",
    )
    with patch(
        "flowremote.api.routes.ai_settings.probe_connection", return_value=result
    ):
        response = client.post(
            "/settings/ai/test",
            data={
                "provider": "openai",
                "model": "demo-model",
                "base_url": "https://ai.example.com/v1",
                "api_key": key,
            },
            headers={"Accept": "application/json"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["connected"] is False
    assert data["fallback"] is True
    assert data["provider"] == "offline"
    assert data["attempted_model"] == "demo-model"
    assert data["model"] == "grounded-rules-v1"
    assert data["error_code"] == "invalid_key"
    assert data["latency_ms"] == 48
    assert "API key" in data["message"]
    assert "Offline Demo AI" in data["message"]
    assert "Offline Demo AI" in data["action"]
    assert key not in response.text
    assert data["settings"]["provider"] == "offline"
    with Database(url) as db:
        row = db.query("SELECT * FROM ai_settings WHERE user_id = 'A'")[0]
        assert row["provider"] == "offline"
        assert key not in (row["api_key_encrypted"] or "")
        assert row["api_key_encrypted"] is None


def test_no_key_auto_uses_offline_without_network(ai_connection_app):
    _app, client, _url = ai_connection_app
    login(client)
    with patch(
        "flowremote.api.routes.ai_settings.probe_connection",
        side_effect=AssertionError("network should not be used without a key"),
    ) as probe:
        response = client.post(
            "/settings/ai/test",
            data={
                "provider": "openai",
                "model": "demo-model",
                "base_url": "https://ai.example.com/v1",
                "api_key": "",
            },
            headers={"Accept": "application/json"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["connected"] is True
    assert data["fallback"] is True
    assert data["provider"] == "offline"
    assert data["error_code"] == "no_key"
    assert data["model"] == "grounded-rules-v1"
    assert "Offline Demo AI" in data["message"]
    assert data["settings"]["provider"] == "offline"
    probe.assert_not_called()


def test_network_failure_auto_switches_to_offline(ai_connection_app):
    _app, client, _url = ai_connection_app
    login(client)
    result = ConnectionResult(
        ok=False,
        provider="openai",
        model=None,
        latency_ms=2500,
        error_code="network",
        message="FlowRemote could not reach the AI provider.",
        action="Check the network or base URL, or switch to Offline Demo AI.",
    )
    with patch(
        "flowremote.api.routes.ai_settings.probe_connection", return_value=result
    ):
        response = client.post(
            "/settings/ai/test",
            data={
                "provider": "openai",
                "model": "demo-model",
                "base_url": "https://ai.example.com/v1",
                "api_key": "network-key",
            },
            headers={"Accept": "application/json"},
        )
    data = response.json()
    assert data["fallback"] is True
    assert data["provider"] == "offline"
    assert data["error_code"] == "network"
    assert data["latency_ms"] == 2500
    assert data["settings"]["provider"] == "offline"


def test_demo_mode_env_prefills_safe_fields_without_exposing_key(
    ai_connection_app, monkeypatch
):
    _app, client, _url = ai_connection_app
    login(client)
    monkeypatch.setenv("FLOWREMOTE_DEMO_MODE", "1")
    monkeypatch.setenv("FLOWREMOTE_AI_PROVIDER", "openai")
    monkeypatch.setenv("FLOWREMOTE_AI_MODEL", "demo-model")
    monkeypatch.setenv("FLOWREMOTE_AI_BASE_URL", "https://demo.example.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "env-secret-1234")
    public = client.get("/settings/ai", headers={"Accept": "application/json"})
    assert public.status_code == 200
    data = public.json()
    assert data["provider"] == "openai"
    assert data["model"] == "demo-model"
    assert data["base_url"] == "https://demo.example.com/v1"
    assert data["key_configured"] is True
    assert data["key_source"] == "environment"
    assert data["key_hint"] == ""
    assert "env-secret-1234" not in public.text


def test_settings_page_has_connection_controls_and_password_input(ai_connection_app):
    _app, client, _url = ai_connection_app
    login(client)
    page = client.get("/settings/ai")
    assert page.status_code == 200
    assert "Test online connection" in page.text
    assert 'type="password"' in page.text
    assert "No saved API key" in page.text
    assert "Connection testing is intentionally" not in page.text
    home = client.get("/")
    assert "data-ai-settings-open" in home.text
    assert "data-ai-connection-bar" not in home.text


def test_connection_test_does_not_create_task_or_activity_records(ai_connection_app):
    _app, client, url = ai_connection_app
    login(client)
    result = ConnectionResult(
        ok=True,
        provider="openai",
        model="demo-model",
        latency_ms=12,
        message="Connected.",
    )
    with patch(
        "flowremote.api.routes.ai_settings.probe_connection", return_value=result
    ):
        client.post(
            "/settings/ai/test",
            data={
                "provider": "openai",
                "model": "demo-model",
                "base_url": "https://ai.example.com/v1",
                "api_key": "secret-activity-key",
            },
            headers={"Accept": "application/json"},
        )
    with Database(url) as db:
        assert db.scalar("SELECT COUNT(*) FROM activity_events") == 0
        assert db.scalar("SELECT COUNT(*) FROM ai_suggestion_runs") == 0
        assert "secret-activity-key" not in str(
            db.query("SELECT * FROM ai_settings WHERE user_id = 'A'")
        )
