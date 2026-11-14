"""Probe an OpenAI-compatible endpoint without leaking credentials.

The connection window calls this module; it is deliberately separate from the
suggestion provider so a probe can never create a correction suggestion or
write an audit row containing a key. Timeouts are bounded so the UI can promise
a result within five seconds.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

DEFAULT_BASE_URL = "https://api.deepseek.com"
OFFLINE_MODEL = "grounded-rules-v1"
MAX_CONNECTION_SECONDS = 5.0


@dataclass(frozen=True)
class ConnectionResult:
    ok: bool
    provider: str
    model: str | None
    latency_ms: int
    error_code: str | None = None
    message: str = ""
    action: str = ""

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "provider": self.provider,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "error_code": self.error_code,
            "message": self.message,
            "action": self.action,
        }


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def offline_result(model: str = OFFLINE_MODEL) -> ConnectionResult:
    return ConnectionResult(
        ok=True,
        provider="offline",
        model=model,
        latency_ms=0,
        message="Offline Demo AI is ready. Rules only; no network.",
        action="",
    )


def _failure(
    *,
    started: float,
    error_code: str,
    message: str,
    action: str,
    provider: str = "openai",
) -> ConnectionResult:
    return ConnectionResult(
        ok=False,
        provider=provider,
        model=None,
        latency_ms=_elapsed_ms(started),
        error_code=error_code,
        message=message,
        action=action,
    )


def normalize_api_base(base_url: str) -> str:
    """Return an API base URL, adding the conventional /v1 when necessary."""
    raw = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(
            "The API base URL cannot contain credentials, a query or a fragment."
        )
    if parsed.scheme == "https" and parsed.netloc or parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        pass
    else:
        raise ValueError(
            "Use an HTTPS base URL, or HTTP only for localhost during development."
        )
    if not parsed.path or parsed.path == "/":
        raw += "/v1"
    return raw


def _model_is_listed(payload: object, model: str) -> bool:
    if not isinstance(payload, dict):
        return False
    items = payload.get("data")
    if not isinstance(items, list):
        return False
    return any(
        isinstance(item, dict) and str(item.get("id") or "").strip() == model
        for item in items
    )


def _response_error(status_code: int, *, started: float) -> ConnectionResult:
    if status_code in (401, 403):
        return _failure(
            started=started,
            error_code="invalid_key",
            message="The AI provider rejected this API key.",
            action="Paste a valid key, or switch to Offline Demo AI.",
        )
    if status_code == 429:
        return _failure(
            started=started,
            error_code="quota",
            message="The AI provider rate-limited the request or the quota is exhausted.",
            action="Wait for quota to reset, use another key, or switch to Offline Demo AI.",
        )
    if status_code in (400, 404):
        return _failure(
            started=started,
            error_code="model_or_url",
            message="The model name or API base URL was rejected.",
            action="Check the model and base URL (usually ends in /v1), or switch to Offline Demo AI.",
        )
    return _failure(
        started=started,
        error_code="provider_error",
        message=f"The AI provider returned HTTP {status_code}.",
        action="Try again, or switch to Offline Demo AI to finish the cleanup.",
    )


def _probe_with_completion(
    client: httpx.Client,
    *,
    base_url: str,
    model: str,
    api_key: str,
    started: float,
    deadline: float,
) -> ConnectionResult:
    remaining = deadline - time.perf_counter()
    if remaining <= 0.35:
        return _failure(
            started=started,
            error_code="network",
            message="The connection test ran out of time.",
            action="Check the network or base URL, or switch to Offline Demo AI.",
        )
    try:
        response = client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
                "temperature": 0,
            },
            timeout=remaining,
        )
    except httpx.TimeoutException:
        return _failure(
            started=started,
            error_code="network",
            message="The AI provider did not answer within the 5-second window.",
            action="Check the network or base URL, or switch to Offline Demo AI.",
        )
    except (httpx.NetworkError, httpx.ConnectError):
        return _failure(
            started=started,
            error_code="network",
            message="FlowRemote could not reach the AI provider.",
            action="Check the network or base URL, or switch to Offline Demo AI.",
        )
    if response.status_code == 200:
        return ConnectionResult(
            ok=True,
            provider="openai",
            model=model,
            latency_ms=_elapsed_ms(started),
            message="Connected to the OpenAI-compatible endpoint.",
            action="",
        )
    return _response_error(response.status_code, started=started)


def probe_connection(
    provider: str,
    base_url: str,
    model: str,
    api_key: str,
    *,
    transport: httpx.BaseTransport | None = None,
    timeout_seconds: float = MAX_CONNECTION_SECONDS,
) -> ConnectionResult:
    """Return a safe, user-readable result and never raise.

    A key is never included in a result, an error message or a log line.
    """
    started = time.perf_counter()
    provider = (provider or "").strip().lower()
    if provider == "offline":
        return offline_result()
    if provider != "openai":
        return _failure(
            started=started,
            error_code="config",
            message="Choose OpenAI-compatible or Offline Demo AI.",
            action="Select a provider and try again.",
        )

    model = (model or "").strip()
    api_key = (api_key or "").strip()
    if not model:
        return _failure(
            started=started,
            error_code="config",
            message="A model name is required.",
            action="Enter the model exposed by your API, or switch to Offline Demo AI.",
        )
    if not api_key:
        return _failure(
            started=started,
            error_code="no_key",
            message="No API key was supplied.",
            action="Paste a key, or continue with Offline Demo AI.",
        )

    try:
        base = normalize_api_base(base_url)
    except ValueError as exc:
        return _failure(
            started=started,
            error_code="config",
            message=str(exc),
            action="Fix the base URL, or switch to Offline Demo AI.",
        )

    timeout = max(0.5, min(float(timeout_seconds), MAX_CONNECTION_SECONDS))
    deadline = started + timeout
    parsed_base = urlparse(base)
    is_local = parsed_base.hostname in {"localhost", "127.0.0.1", "::1"}
    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(1.5, timeout)),
            transport=transport,
            follow_redirects=False,
            # A system proxy can add seconds to loopback requests; keep the
            # localhost demo deterministic while still honouring system proxies
            # for real remote providers.
            trust_env=not is_local,
        ) as client:
            response = client.get(
                f"{base}/models",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                },
            )
            if response.status_code == 200:
                try:
                    payload = response.json()
                except (json.JSONDecodeError, ValueError):
                    payload = None
                listed = _model_is_listed(payload, model)
                return ConnectionResult(
                    ok=True,
                    provider="openai",
                    model=model,
                    latency_ms=_elapsed_ms(started),
                    message=(
                        "Connected. The model is available."
                        if listed
                        else "Connected. The model was not listed by the provider."
                    ),
                    action="",
                )
            if response.status_code in (404, 405):
                return _probe_with_completion(
                    client,
                    base_url=base,
                    model=model,
                    api_key=api_key,
                    started=started,
                    deadline=deadline,
                )
            return _response_error(response.status_code, started=started)
    except httpx.TimeoutException:
        return _failure(
            started=started,
            error_code="network",
            message="The AI provider did not answer within the 5-second window.",
            action="Check the network or base URL, or switch to Offline Demo AI.",
        )
    except (httpx.NetworkError, httpx.ConnectError):
        return _failure(
            started=started,
            error_code="network",
            message="FlowRemote could not reach the AI provider.",
            action="Check the network or base URL, or switch to Offline Demo AI.",
        )
    except (httpx.InvalidURL, ValueError):
        return _failure(
            started=started,
            error_code="config",
            message="The API base URL is not valid.",
            action="Fix the base URL, or switch to Offline Demo AI.",
        )
    except Exception:  # noqa: BLE001 - the probe must never leak a traceback.
        return _failure(
            started=started,
            error_code="provider_error",
            message="The connection test failed.",
            action="Try again, or switch to Offline Demo AI to finish the cleanup.",
        )
