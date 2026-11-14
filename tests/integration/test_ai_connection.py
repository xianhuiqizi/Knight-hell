"""Integration tests for AI connection test endpoint."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, Mock

from flowremote.api.app import create_app
from flowremote.control_plane.auth import create_user
from flowremote.control_plane.db import PROJECT_ROOT, Database


SECRET = "ai-connection-test-secret"


@pytest.fixture()
def test_app():
    """Create test app with database and user."""
    root = PROJECT_ROOT / "data" / "runtime" / "tests"
    root.mkdir(parents=True, exist_ok=True)
    temp = TemporaryDirectory(dir=root)
    folder = Path(temp.name)
    url = f"sqlite:///{(folder / 'connection.db').as_posix()}"
    
    with Database(url) as db:
        db.apply_migrations()
        create_user(
            db,
            name="Test User",
            email="test@example.com",
            password="test123",
            user_id="USR-TEST",
        )
    
    app = create_app(url, SECRET)
    with TestClient(app) as client:
        yield app, client, url
    temp.cleanup()


def login(client: TestClient) -> None:
    """Login test user."""
    response = client.post(
        "/login",
        data={"email": "test@example.com", "password": "test123"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_connection_test_requires_authentication(test_app):
    """Connection test endpoint requires signed-in user."""
    _app, client, _url = test_app
    
    response = client.post(
        "/settings/ai/test",
        json={
            "provider": "offline",
            "base_url": "",
            "model": "",
            "api_key": "",
        },
    )
    
    assert response.status_code == 401
    assert response.json()["detail"] == "sign in required"


def test_connection_test_offline_success(test_app):
    """Offline provider test succeeds immediately."""
    _app, client, _url = test_app
    login(client)
    
    response = client.post(
        "/settings/ai/test",
        json={
            "provider": "offline",
            "base_url": "",
            "model": "",
            "api_key": "",
        },
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["provider"] == "offline"
    assert data["model"] == "grounded-rules-v1"
    assert data["latency_ms"] == 0
    assert "Offline Demo AI" in data["message"]


def test_connection_test_form_encoded(test_app):
    """Connection test accepts form-encoded data."""
    _app, client, _url = test_app
    login(client)
    
    response = client.post(
        "/settings/ai/test",
        data={
            "provider": "offline",
            "base_url": "",
            "model": "",
            "api_key": "",
        },
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["provider"] == "offline"


def test_connection_test_missing_model(test_app):
    """OpenAI test without model returns error."""
    _app, client, _url = test_app
    login(client)
    
    response = client.post(
        "/settings/ai/test",
        json={
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "",
            "api_key": "sk-test",
        },
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "Model name is required" in data["message"]


def test_connection_test_missing_api_key(test_app):
    """OpenAI test without API key returns error."""
    _app, client, _url = test_app
    login(client)
    
    response = client.post(
        "/settings/ai/test",
        json={
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4",
            "api_key": "",
        },
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "API key is required" in data["message"]


@patch("httpx.Client")
def test_connection_test_successful_openai(mock_client_class, test_app):
    """Successful OpenAI connection test."""
    _app, client, _url = test_app
    
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [{"id": "gpt-4", "object": "model"}]
    }
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=None)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    login(client)
    
    response = client.post(
        "/settings/ai/test",
        json={
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4",
            "api_key": "sk-test-key-123",
        },
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["provider"] == "openai_compatible"
    assert data["model"] == "gpt-4"
    assert data["latency_ms"] >= 0
    assert "Connected successfully" in data["message"]


@patch("httpx.Client")
def test_connection_test_401_invalid_key(mock_client_class, test_app):
    """401 response from OpenAI returns invalid key error."""
    _app, client, _url = test_app
    
    mock_response = Mock()
    mock_response.status_code = 401
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=None)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    login(client)
    
    response = client.post(
        "/settings/ai/test",
        json={
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4",
            "api_key": "sk-wrong-key",
        },
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "Invalid API key" in data["message"]


@patch("httpx.Client")
def test_connection_test_timeout(mock_client_class, test_app):
    """Timeout during connection test."""
    import httpx
    
    _app, client, _url = test_app
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=None)
    mock_client.get.side_effect = httpx.TimeoutException("timeout")
    mock_client_class.return_value = mock_client
    
    login(client)
    
    response = client.post(
        "/settings/ai/test",
        json={
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4",
            "api_key": "sk-test-key",
        },
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "timeout" in data["message"].lower()


def test_connection_test_invalid_json(test_app):
    """Invalid JSON request returns 400."""
    _app, client, _url = test_app
    login(client)
    
    response = client.post(
        "/settings/ai/test",
        headers={"Content-Type": "application/json"},
        content=b"{invalid json}",
    )
    
    assert response.status_code == 400
    data = response.json()
    assert data["ok"] is False
    assert "Invalid JSON" in data["message"]


def test_connection_test_unknown_provider(test_app):
    """Unknown provider returns error."""
    _app, client, _url = test_app
    login(client)
    
    response = client.post(
        "/settings/ai/test",
        json={
            "provider": "anthropic",
            "base_url": "",
            "model": "claude-3",
            "api_key": "sk-test",
        },
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "Unknown provider" in data["message"]


def test_connection_test_does_not_save_credentials(test_app):
    """Connection test does not save credentials to database."""
    _app, client, url = test_app
    login(client)
    
    # Test connection
    response = client.post(
        "/settings/ai/test",
        json={
            "provider": "offline",
            "base_url": "",
            "model": "test-model",
            "api_key": "sk-should-not-be-saved",
        },
    )
    
    assert response.status_code == 200
    
    # Check database - should have no ai_settings entry
    with Database(url) as db:
        rows = db.query("SELECT * FROM ai_settings WHERE user_id = ?", ("USR-TEST",))
        assert len(rows) == 0


@patch("httpx.Client")
def test_connection_test_custom_base_url(mock_client_class, test_app):
    """Custom base URL is used for connection test."""
    _app, client, _url = test_app
    
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": [{"id": "custom-model"}]}
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=None)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    login(client)
    
    response = client.post(
        "/settings/ai/test",
        json={
            "provider": "openai",
            "base_url": "https://custom-api.example.com/v1",
            "model": "custom-model",
            "api_key": "sk-custom-key",
        },
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    
    # Verify custom URL was used
    mock_client.get.assert_called_once()
    call_url = mock_client.get.call_args[0][0]
    assert "custom-api.example.com" in call_url
