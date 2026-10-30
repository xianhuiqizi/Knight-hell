"""Per-user AI connection window, encrypted keys and provider selection."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from flowremote.agent.config import provider_for_user
from flowremote.agent.providers import OfflineSuggestionProvider, OpenAISuggestionProvider
from flowremote.api.app import create_app
from flowremote.control_plane.auth import create_user
from flowremote.control_plane.db import PROJECT_ROOT, Database

SECRET = "ai-settings-test-secret"


@pytest.fixture()
def ai_app(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    root = PROJECT_ROOT / "data" / "runtime" / "tests"
    root.mkdir(parents=True, exist_ok=True)
    temp = TemporaryDirectory(dir=root)
    folder = Path(temp.name)
    url = f"sqlite:///{(folder / 'settings.db').as_posix()}"
    with Database(url) as db:
        db.apply_migrations()
        create_user(
            db,
            name="Alex",
            email="alex@example.com",
            password="password123",
            user_id="USR-A",
        )
        create_user(
            db,
            name="Bea",
            email="bea@example.com",
            password="password123",
            user_id="USR-B",
        )
    app = create_app(url, SECRET)
    with TestClient(app) as client:
        yield app, client, url
    temp.cleanup()


def login(client: TestClient, email: str = "alex@example.com") -> None:
    response = client.post(
        "/login",
        data={"email": email, "password": "password123"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def save(client: TestClient, **values):
    data = {
        "provider": "offline",
        "model": "gpt-6-astra",
        "base_url": "",
        "api_key": "",
        "clear_key": "",
    }
    data.update(values)
    return client.post(
        "/settings/ai",
        data=data,
        headers={"Accept": "application/json"},
    )


def test_anonymous_settings_request_redirects(ai_app):
    _app, client, _url = ai_app
    response = client.get("/settings/ai", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/settings/ai"


def test_logged_in_page_has_window_link_and_full_settings(ai_app):
    _app, client, _url = ai_app
    login(client)
    home = client.get("/")
    assert "data-ai-settings-open" in home.text
    assert 'id="ai-settings-dialog"' in home.text
    page = client.get("/settings/ai")
    assert page.status_code == 200
    assert "AI connection" in page.text
    assert "No saved API key" in page.text


def test_openai_settings_are_saved_without_plaintext_key(ai_app):
    _app, client, url = ai_app
    login(client)
    response = save(
        client,
        provider="openai",
        model="compatible-model",
        base_url="https://ai.example.com/v1",
        api_key="secret-value-ABCD",
    )
    assert response.status_code == 200
    assert response.json()["settings"] == {
        "provider": "openai",
        "model": "compatible-model",
        "base_url": "https://ai.example.com/v1",
        "key_configured": True,
        "key_hint": "••••ABCD",
        "key_source": "saved",
    }
    with Database(url) as db:
        row = db.query("SELECT * FROM ai_settings WHERE user_id = 'USR-A'")[0]
    assert row["api_key_encrypted"] != "secret-value-ABCD"
    assert "secret-value-ABCD" not in row["api_key_encrypted"]
    public = client.get("/settings/ai", headers={"Accept": "application/json"}).json()
    assert "secret-value-ABCD" not in str(public)


def test_blank_key_preserves_and_clear_key_removes_the_secret(ai_app):
    _app, client, url = ai_app
    login(client)
    assert save(
        client, provider="openai", model="m", api_key="secret-key-WXYZ"
    ).status_code == 200
    assert save(client, provider="openai", model="m").status_code == 200
    with Database(url) as db:
        assert db.scalar(
            "SELECT api_key_hint FROM ai_settings WHERE user_id = 'USR-A'"
        ) == "WXYZ"
    response = save(client, provider="openai", model="m", clear_key="1")
    assert response.status_code == 200
    assert response.json()["settings"]["key_configured"] is False


@pytest.mark.parametrize(
    "values",
    [
        {"provider": "unknown"},
        {"provider": "openai", "model": "m", "base_url": "http://example.com/v1"},
        {
            "provider": "openai",
            "model": "m",
            "base_url": "https://user:pass@example.com/v1",
        },
        {"provider": "openai", "model": "x" * 161},
    ],
)
def test_unsafe_urls_and_invalid_provider_are_rejected(ai_app, values):
    _app, client, _url = ai_app
    login(client)
    response = save(client, **values)
    assert response.status_code == 400


def test_saved_configuration_resolves_to_the_selected_provider(ai_app):
    app, client, url = ai_app
    login(client)
    save(
        client,
        provider="openai",
        model="compatible-model",
        base_url="https://ai.example.com/v1",
        api_key="secret-key-1234",
    )
    with Database(url) as db:
        provider = provider_for_user(
            db,
            app.state.ai_settings_cipher,
            user_id="USR-A",
            fallback=OfflineSuggestionProvider(),
        )
    assert isinstance(provider, OpenAISuggestionProvider)
    assert provider.model == "compatible-model"
    assert provider.base_url == "https://ai.example.com/v1"
    assert provider._api_key == "secret-key-1234"


def test_saved_model_configuration_is_used_by_a_suggestion_request(ai_app):
    _app, client, url = ai_app
    login(client)
    now = "2026-10-30T12:00:00Z"
    with Database(url) as db:
        db.execute(
            "INSERT INTO tasks (id, workflow, batch_size, status, source_file,"
            " source_location, primary_target, secondary_target, owner_id,"
            " created_at, updated_at) VALUES ('TASK-AI', 'AI test', 1,"
            " 'review_required', 'orders.xlsx', 'Uploaded file', 'OA', 'BI',"
            " 'USR-A', ?, ?)",
            (now, now),
        )
        db.execute(
            "INSERT INTO source_records (task_id, record_id, customer_name,"
            " customer_id, quantity, unit_price, amount, order_date, outcome)"
            " VALUES ('TASK-AI', 'ORD-001', 'Alex', '', 1, 10, 10,"
            " '2026-10-30', 'flagged')"
        )
        db.execute(
            "INSERT INTO exceptions (id, task_id, record_id, issue, flagged_fields,"
            " original_value, status, created_at) VALUES ('EXC-AI', 'TASK-AI',"
            " 'ORD-001', 'missing_value', 'customer_id', '{\"customer_id\":\"\"}',"
            " 'unresolved', ?)",
            (now,),
        )
    save(client, provider="openai", model="user-selected-model")
    response = client.post(
        "/tasks/TASK-AI/exceptions/ORD-001/suggestions",
        data={"request_id": "SETTINGS-E2E"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with Database(url) as db:
        run = db.query(
            "SELECT status, provider, model, error_code FROM ai_suggestion_runs"
        )[0]
    assert run == {
        "status": "failed",
        "provider": "openai",
        "model": "user-selected-model",
        "error_code": "provider_error",
    }


def test_settings_are_isolated_between_users(ai_app):
    _app, client, _url = ai_app
    login(client, "alex@example.com")
    save(client, provider="openai", model="alex-model", api_key="alex-key")
    client.cookies.clear()
    login(client, "bea@example.com")
    data = client.get("/settings/ai", headers={"Accept": "application/json"}).json()
    assert data["provider"] == "offline"
    assert data["key_configured"] is False


def test_non_javascript_form_redirects_after_save(ai_app):
    _app, client, _url = ai_app
    login(client)
    response = client.post(
        "/settings/ai",
        data={"provider": "offline", "model": "", "base_url": ""},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/settings/ai?saved=1"
