"""Unit tests for the bounded OpenAI-compatible connection probe."""

from __future__ import annotations

import httpx

from flowremote.agent.connection import (
    MAX_CONNECTION_SECONDS,
    OFFLINE_MODEL,
    normalize_api_base,
    probe_connection,
)
from flowremote.control_plane.db import PROJECT_ROOT


def transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_offline_probe_never_calls_network():
    called = []

    def handler(request):
        called.append(request)
        return httpx.Response(200)

    result = probe_connection(
        "offline", "", "anything", "", transport=transport(handler)
    )
    assert result.ok is True
    assert result.provider == "offline"
    assert result.model == OFFLINE_MODEL
    assert result.latency_ms == 0
    assert called == []


def test_openai_models_success_returns_model_and_latency():
    def handler(request):
        assert request.method == "GET"
        assert str(request.url) == "https://ai.example.com/v1/models"
        assert request.headers["authorization"] == "Bearer secret-key"
        return httpx.Response(200, json={"data": [{"id": "demo-model"}]})

    result = probe_connection(
        "openai",
        "https://ai.example.com/v1",
        "demo-model",
        "secret-key",
        transport=transport(handler),
    )
    assert result.ok is True
    assert result.provider == "openai"
    assert result.model == "demo-model"
    assert result.error_code is None
    assert result.latency_ms >= 0


def test_openai_completion_fallback_when_models_endpoint_is_missing():
    seen = []

    def handler(request):
        seen.append((request.method, str(request.url)))
        if request.url.path.endswith("/models"):
            return httpx.Response(404)
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(200, json={"choices": []})

    result = probe_connection(
        "openai",
        "https://ai.example.com/v1",
        "demo-model",
        "secret-key",
        transport=transport(handler),
    )
    assert result.ok is True
    assert result.model == "demo-model"
    assert [method for method, _url in seen] == ["GET", "POST"]


def test_invalid_key_is_actionable_and_does_not_echo_the_key():
    result = probe_connection(
        "openai",
        "https://ai.example.com/v1",
        "demo-model",
        "super-secret-key",
        transport=transport(lambda request: httpx.Response(401)),
    )
    assert result.ok is False
    assert result.error_code == "invalid_key"
    assert "API key" in result.message
    assert "Offline Demo AI" in result.action
    assert "super-secret-key" not in str(result.as_dict())


def test_quota_is_actionable():
    result = probe_connection(
        "openai",
        "https://ai.example.com/v1",
        "demo-model",
        "secret",
        transport=transport(lambda request: httpx.Response(429)),
    )
    assert result.ok is False
    assert result.error_code == "quota"
    assert "quota" in result.action.lower()


def test_network_error_is_mapped():
    def handler(request):
        raise httpx.ConnectError("network down", request=request)

    result = probe_connection(
        "openai",
        "https://ai.example.com/v1",
        "demo-model",
        "secret",
        transport=transport(handler),
    )
    assert result.ok is False
    assert result.error_code == "network"
    assert "network" in result.action.lower() or "base URL" in result.action


def test_timeout_is_mapped():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    result = probe_connection(
        "openai",
        "https://ai.example.com/v1",
        "demo-model",
        "secret",
        transport=transport(handler),
    )
    assert result.ok is False
    assert result.error_code == "network"
    assert "5-second" in result.message


def test_missing_key_and_model_are_local_errors():
    called = []

    def handler(request):
        called.append(request)
        return httpx.Response(200)

    key_result = probe_connection(
        "openai", "https://ai.example.com/v1", "model", "", transport=transport(handler)
    )
    model_result = probe_connection(
        "openai", "https://ai.example.com/v1", "", "key", transport=transport(handler)
    )
    assert key_result.error_code == "no_key"
    assert model_result.error_code == "config"
    assert called == []


def test_unknown_provider_is_a_config_error():
    result = probe_connection("other", "", "model", "key")
    assert result.ok is False
    assert result.error_code == "config"


def test_base_url_requires_a_safe_scheme_and_gets_v1_default():
    assert normalize_api_base("https://ai.example.com") == "https://ai.example.com/v1"
    assert normalize_api_base("https://ai.example.com/v1/") == "https://ai.example.com/v1"
    assert normalize_api_base("http://127.0.0.1:9000") == "http://127.0.0.1:9000/v1"

    for unsafe in (
        "http://ai.example.com/v1",
        "https://user:pass@ai.example.com/v1",
        "https://ai.example.com/v1?x=1",
    ):
        result = probe_connection("openai", unsafe, "model", "key")
        assert result.ok is False
        assert result.error_code == "config"


def test_models_endpoint_without_requested_model_is_still_connected():
    result = probe_connection(
        "openai",
        "https://ai.example.com/v1",
        "private-model",
        "secret",
        transport=transport(lambda request: httpx.Response(200, json={"data": []})),
    )
    assert result.ok is True
    assert result.model == "private-model"
    assert "not listed" in result.message


def test_empty_base_url_uses_deepseek_default():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"data": []})

    result = probe_connection(
        "openai", "", "demo-model", "secret", transport=transport(handler)
    )
    assert result.ok is True
    assert seen == ["https://api.deepseek.com/v1/models"]


def test_connection_budget_is_under_five_seconds():
    assert 0 < MAX_CONNECTION_SECONDS <= 5


def test_ai_connection_javascript_never_uses_browser_storage_for_keys():
    source = (
        PROJECT_ROOT / "src" / "flowremote" / "ui" / "static" / "app.js"
    ).read_text(encoding="utf-8")
    ai_block = source[source.index("const aiDialog"):]
    assert "localStorage" not in ai_block
    assert "indexedDB" not in ai_block
    assert "apiKey.value = \"\"" in ai_block
    assert "API key detected. OpenAI-compatible is selected" in ai_block
