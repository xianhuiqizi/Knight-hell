"""Unit tests for AI connection testing."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from flowremote.control_plane.ai_settings import check_connection


def test_offline_provider_instant_success():
    """Offline provider returns immediately with no network call."""
    result = check_connection(
        provider="offline",
        base_url="",
        model="",
        api_key="",
    )
    
    assert result.ok is True
    assert result.provider == "offline"
    assert result.model == "grounded-rules-v1"
    assert result.latency_ms == 0
    assert "Offline Demo AI" in result.message
    assert "no network" in result.message


def test_unknown_provider():
    """Unknown provider returns error without network call."""
    result = check_connection(
        provider="unknown-provider",
        base_url="https://api.example.com",
        model="test-model",
        api_key="test-key",
    )
    
    assert result.ok is False
    assert result.provider == "unknown-provider"
    assert result.model is None
    assert result.latency_ms == 0
    assert "Unknown provider" in result.message


def test_openai_missing_model():
    """OpenAI provider without model returns error."""
    result = check_connection(
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="",
        api_key="sk-test-key",
    )
    
    assert result.ok is False
    assert result.provider == "openai_compatible"
    assert result.model is None
    assert "Model name is required" in result.message


def test_openai_missing_api_key():
    """OpenAI provider without API key returns error."""
    result = check_connection(
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4",
        api_key="",
    )
    
    assert result.ok is False
    assert result.provider == "openai_compatible"
    assert result.model is None
    assert "API key is required" in result.message


@patch("httpx.Client")
def test_openai_successful_connection(mock_client_class):
    """Successful OpenAI connection returns model and latency."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {"id": "gpt-4", "object": "model"},
            {"id": "gpt-3.5-turbo", "object": "model"},
        ]
    }
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=None)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    result = check_connection(
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4",
        api_key="sk-test-key",
    )
    
    assert result.ok is True
    assert result.provider == "openai_compatible"
    assert result.model == "gpt-4"
    assert result.latency_ms >= 0
    assert "Connected successfully" in result.message
    
    # Verify correct API call
    mock_client.get.assert_called_once()
    call_args = mock_client.get.call_args
    assert "/models" in call_args[0][0]
    assert call_args[1]["headers"]["Authorization"] == "Bearer sk-test-key"


@patch("httpx.Client")
def test_openai_401_invalid_key(mock_client_class):
    """401 response maps to invalid key message."""
    mock_response = Mock()
    mock_response.status_code = 401
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=None)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    result = check_connection(
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4",
        api_key="sk-wrong-key",
    )
    
    assert result.ok is False
    assert result.provider == "openai_compatible"
    assert result.model is None
    assert "Invalid API key" in result.message


@patch("httpx.Client")
def test_openai_403_forbidden(mock_client_class):
    """403 response maps to access forbidden message."""
    mock_response = Mock()
    mock_response.status_code = 403
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=None)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    result = check_connection(
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4",
        api_key="sk-restricted-key",
    )
    
    assert result.ok is False
    assert "Access forbidden" in result.message
    assert "permissions" in result.message


@patch("httpx.Client")
def test_openai_429_rate_limit(mock_client_class):
    """429 response maps to rate limit message."""
    mock_response = Mock()
    mock_response.status_code = 429
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=None)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    result = check_connection(
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4",
        api_key="sk-test-key",
    )
    
    assert result.ok is False
    assert "Rate limit" in result.message
    assert "quota" in result.message


@patch("httpx.Client")
def test_openai_timeout(mock_client_class):
    """Timeout exception maps to timeout message."""
    import httpx
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=None)
    mock_client.get.side_effect = httpx.TimeoutException("Connection timed out")
    mock_client_class.return_value = mock_client
    
    result = check_connection(
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4",
        api_key="sk-test-key",
    )
    
    assert result.ok is False
    assert "timeout" in result.message.lower()
    assert result.latency_ms >= 0


@patch("httpx.Client")
def test_openai_connect_error(mock_client_class):
    """Connection error maps to network error message."""
    import httpx
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=None)
    mock_client.get.side_effect = httpx.ConnectError("Cannot connect")
    mock_client_class.return_value = mock_client
    
    result = check_connection(
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4",
        api_key="sk-test-key",
    )
    
    assert result.ok is False
    assert "Cannot reach server" in result.message
    assert "network" in result.message


@patch("httpx.Client")
def test_openai_404_falls_back_to_completion(mock_client_class):
    """404 on /models tries completion endpoint as fallback."""
    # First call to /models returns 404
    models_response = Mock()
    models_response.status_code = 404
    
    # Second call to /chat/completions returns 200
    completion_response = Mock()
    completion_response.status_code = 200
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=None)
    mock_client.get.return_value = models_response
    mock_client.post.return_value = completion_response
    mock_client_class.return_value = mock_client
    
    result = check_connection(
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4",
        api_key="sk-test-key",
    )
    
    assert result.ok is True
    assert result.provider == "openai_compatible"
    assert result.model == "gpt-4"
    assert "Connected successfully" in result.message
    
    # Verify both endpoints were called
    mock_client.get.assert_called_once()
    mock_client.post.assert_called_once()


@patch("httpx.Client")
def test_openai_model_not_in_list_but_connection_ok(mock_client_class):
    """Model not in list but connection works shows warning."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {"id": "gpt-3.5-turbo", "object": "model"},
        ]
    }
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=None)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    result = check_connection(
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4",
        api_key="sk-test-key",
    )
    
    assert result.ok is True
    assert result.model == "gpt-4"
    assert "not listed but may be available" in result.message


def test_openai_compatible_provider():
    """openai_compatible provider is treated same as openai."""
    result = check_connection(
        provider="openai_compatible",
        base_url="",
        model="",
        api_key="",
    )
    
    assert result.provider == "openai_compatible"
    assert result.ok is False
    assert "Model name is required" in result.message


@patch("httpx.Client")
def test_invalid_base_url(mock_client_class):
    """Invalid base URL returns error before making request."""
    result = check_connection(
        provider="openai",
        base_url="ftp://invalid-scheme.com",
        model="gpt-4",
        api_key="sk-test-key",
    )
    
    assert result.ok is False
    assert result.provider == "openai_compatible"
    # Should not make any HTTP call
    mock_client_class.assert_not_called()


def test_latency_measurement():
    """Latency is measured and returned in milliseconds."""
    result = check_connection(
        provider="offline",
        base_url="",
        model="",
        api_key="",
    )
    
    # Offline should be 0ms
    assert result.latency_ms == 0
    assert isinstance(result.latency_ms, int)
