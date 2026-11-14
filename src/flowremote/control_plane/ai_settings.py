"""Per-user AI connection settings and encrypted API-key storage."""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

from flowremote.control_plane.db import Database, utc_now

PROVIDERS = {"offline", "openai"}
DEFAULT_MODEL = "gpt-6-astra"


class AISettingsError(ValueError):
    """A submitted AI connection setting is invalid."""


@dataclass(frozen=True)
class PublicAISettings:
    provider: str
    model: str
    base_url: str
    key_configured: bool
    key_hint: str
    key_source: str

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "key_configured": self.key_configured,
            "key_hint": self.key_hint,
            "key_source": self.key_source,
        }


class AISettingCipher:
    """Encrypt API keys with a key derived from the application session secret."""

    def __init__(self, secret: str) -> None:
        if not secret:
            raise ValueError("an application secret is required")
        raw = hashlib.sha256(("flowremote-ai-settings:" + secret).encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(raw))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str | None) -> str | None:
        if not value:
            return None
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise AISettingsError(
                "The saved API key cannot be decrypted with the current application secret."
            ) from exc


def _clean_base_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AISettingsError("The API base URL cannot contain credentials, a query or a fragment.")
    if parsed.scheme == "https" and parsed.netloc:
        return value.rstrip("/")
    if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return value.rstrip("/")
    raise AISettingsError(
        "Use an HTTPS API base URL, or HTTP only for localhost during development."
    )


def _row(db: Database, user_id: str) -> dict | None:
    rows = db.query("SELECT * FROM ai_settings WHERE user_id = ?", (user_id,))
    return rows[0] if rows else None


def public_settings(db: Database, user_id: str) -> PublicAISettings:
    row = _row(db, user_id)
    if not row:
        env_key = bool(os.environ.get("OPENAI_API_KEY"))
        return PublicAISettings(
            provider="offline",
            model=DEFAULT_MODEL,
            base_url="",
            key_configured=env_key,
            key_hint="",
            key_source="environment" if env_key else "none",
        )
    hint = row.get("api_key_hint") or ""
    env_key = bool(os.environ.get("OPENAI_API_KEY"))
    saved_key = bool(row.get("api_key_encrypted"))
    return PublicAISettings(
        provider=row["provider"],
        model=row.get("model") or DEFAULT_MODEL,
        base_url=row.get("base_url") or "",
        key_configured=saved_key or env_key,
        key_hint=f"••••{hint}" if hint else "",
        key_source="saved" if saved_key else ("environment" if env_key else "none"),
    )


def save_settings(
    db: Database,
    cipher: AISettingCipher,
    *,
    user_id: str,
    provider: str,
    model: str,
    base_url: str,
    api_key: str,
    clear_key: bool,
) -> PublicAISettings:
    provider = provider.strip().lower()
    if provider not in PROVIDERS:
        raise AISettingsError("Choose either the offline provider or the OpenAI Responses API.")
    model = model.strip() or (DEFAULT_MODEL if provider == "openai" else "")
    if provider == "openai" and not model:
        raise AISettingsError("Enter the model name exposed by your API.")
    if len(model) > 160:
        raise AISettingsError("The model name is too long.")
    base_url = _clean_base_url(base_url)
    api_key = api_key.strip()
    if api_key and clear_key:
        raise AISettingsError("Enter a new API key or clear the saved key, not both.")
    if len(api_key) > 4096:
        raise AISettingsError("The API key is too long.")

    existing = _row(db, user_id)
    encrypted = existing.get("api_key_encrypted") if existing else None
    hint = existing.get("api_key_hint") if existing else None
    if clear_key:
        encrypted = None
        hint = None
    elif api_key:
        encrypted = cipher.encrypt(api_key)
        hint = api_key[-4:]

    now = utc_now()
    with db.transaction():
        if existing:
            db.execute(
                "UPDATE ai_settings SET provider = ?, model = ?, base_url = ?,"
                " api_key_encrypted = ?, api_key_hint = ?, updated_at = ?"
                " WHERE user_id = ?",
                (provider, model or None, base_url or None, encrypted, hint, now, user_id),
            )
        else:
            db.execute(
                "INSERT INTO ai_settings (user_id, provider, model, base_url,"
                " api_key_encrypted, api_key_hint, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, provider, model or None, base_url or None, encrypted, hint, now),
            )
    return public_settings(db, user_id)


def configured_api_key(db: Database, cipher: AISettingCipher, user_id: str) -> str | None:
    row = _row(db, user_id)
    return cipher.decrypt(row.get("api_key_encrypted")) if row else None


@dataclass(frozen=True)
class ConnectionTestResult:
    ok: bool
    provider: str
    model: str | None
    latency_ms: int
    message: str

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "provider": self.provider,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "message": self.message,
        }


def check_connection(
    *,
    provider: str,
    base_url: str,
    model: str,
    api_key: str,
) -> ConnectionTestResult:
    """Test AI provider connection with 3s timeout.
    
    Returns connection status, model name, latency and actionable message.
    Never raises; all errors are mapped to failed results.
    """
    import time
    
    provider = provider.strip().lower()
    
    # Offline provider - instant success
    if provider == "offline":
        return ConnectionTestResult(
            ok=True,
            provider="offline",
            model="grounded-rules-v1",
            latency_ms=0,
            message="Offline Demo AI ready (rules only, no network).",
        )
    
    # OpenAI-compatible provider
    if provider not in {"openai", "openai_compatible"}:
        return ConnectionTestResult(
            ok=False,
            provider=provider,
            model=None,
            latency_ms=0,
            message="Unknown provider. Choose offline or openai_compatible.",
        )
    
    # Validate inputs
    model = model.strip()
    api_key = api_key.strip()
    
    if not model:
        return ConnectionTestResult(
            ok=False,
            provider="openai_compatible",
            model=None,
            latency_ms=0,
            message="Model name is required.",
        )
    
    if not api_key:
        return ConnectionTestResult(
            ok=False,
            provider="openai_compatible",
            model=None,
            latency_ms=0,
            message="API key is required.",
        )
    
    # Test connection with 3s timeout
    try:
        import httpx
    except ImportError:
        return ConnectionTestResult(
            ok=False,
            provider="openai_compatible",
            model=None,
            latency_ms=0,
            message="HTTP client not available.",
        )
    
    start_time = time.perf_counter()
    
    try:
        # Clean and validate base URL
        if base_url:
            test_base_url = _clean_base_url(base_url)
        else:
            test_base_url = "https://api.openai.com/v1"
        
        # Try GET /models endpoint first (cheap and standard)
        models_url = f"{test_base_url}/models"
        
        with httpx.Client(timeout=3.0) as client:
            response = client.get(
                models_url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            
            if response.status_code == 200:
                # Try to extract model info from response
                try:
                    data = response.json()
                    models_list = data.get("data", [])
                    model_ids = [m.get("id") for m in models_list if isinstance(m, dict)]
                    
                    # Check if requested model exists
                    if model in model_ids:
                        return ConnectionTestResult(
                            ok=True,
                            provider="openai_compatible",
                            model=model,
                            latency_ms=elapsed_ms,
                            message=f"Connected successfully · {len(model_ids)} models available.",
                        )
                    else:
                        # Model not in list, but connection works
                        return ConnectionTestResult(
                            ok=True,
                            provider="openai_compatible",
                            model=model,
                            latency_ms=elapsed_ms,
                            message=f"Connected · model '{model}' not listed but may be available.",
                        )
                except Exception:
                    # Response is OK but not parseable - assume success
                    return ConnectionTestResult(
                        ok=True,
                        provider="openai_compatible",
                        model=model,
                        latency_ms=elapsed_ms,
                        message="Connected successfully.",
                    )
            
            elif response.status_code == 401:
                return ConnectionTestResult(
                    ok=False,
                    provider="openai_compatible",
                    model=None,
                    latency_ms=elapsed_ms,
                    message="Invalid API key. Check your credentials.",
                )
            
            elif response.status_code == 403:
                return ConnectionTestResult(
                    ok=False,
                    provider="openai_compatible",
                    model=None,
                    latency_ms=elapsed_ms,
                    message="Access forbidden. Check your API key permissions.",
                )
            
            elif response.status_code == 404:
                # /models endpoint not supported, try minimal completion request
                return _test_with_completion(test_base_url, model, api_key, start_time)
            
            elif response.status_code == 429:
                return ConnectionTestResult(
                    ok=False,
                    provider="openai_compatible",
                    model=None,
                    latency_ms=elapsed_ms,
                    message="Rate limit exceeded. Try again later or check your quota.",
                )
            
            else:
                return ConnectionTestResult(
                    ok=False,
                    provider="openai_compatible",
                    model=None,
                    latency_ms=elapsed_ms,
                    message=f"Unexpected response: HTTP {response.status_code}.",
                )
    
    except httpx.TimeoutException:
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        return ConnectionTestResult(
            ok=False,
            provider="openai_compatible",
            model=None,
            latency_ms=elapsed_ms,
            message="Connection timeout. Check your network or base URL.",
        )
    
    except httpx.ConnectError:
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        return ConnectionTestResult(
            ok=False,
            provider="openai_compatible",
            model=None,
            latency_ms=elapsed_ms,
            message="Cannot reach server. Check your network connection.",
        )
    
    except AISettingsError as exc:
        return ConnectionTestResult(
            ok=False,
            provider="openai_compatible",
            model=None,
            latency_ms=0,
            message=str(exc),
        )
    
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        return ConnectionTestResult(
            ok=False,
            provider="openai_compatible",
            model=None,
            latency_ms=elapsed_ms,
            message=f"Connection error: {type(exc).__name__}",
        )


def _test_with_completion(base_url: str, model: str, api_key: str, start_time: float) -> ConnectionTestResult:
    """Fallback: test with minimal completion request when /models is not available."""
    import httpx
    import time
    
    try:
        completion_url = f"{base_url}/chat/completions"
        
        with httpx.Client(timeout=3.0) as client:
            response = client.post(
                completion_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "test"}],
                    "max_tokens": 1,
                },
            )
            
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            
            if response.status_code == 200:
                return ConnectionTestResult(
                    ok=True,
                    provider="openai_compatible",
                    model=model,
                    latency_ms=elapsed_ms,
                    message="Connected successfully.",
                )
            
            elif response.status_code == 401:
                return ConnectionTestResult(
                    ok=False,
                    provider="openai_compatible",
                    model=None,
                    latency_ms=elapsed_ms,
                    message="Invalid API key. Check your credentials.",
                )
            
            elif response.status_code == 404:
                return ConnectionTestResult(
                    ok=False,
                    provider="openai_compatible",
                    model=None,
                    latency_ms=elapsed_ms,
                    message=f"Model '{model}' not found. Check the model name.",
                )
            
            elif response.status_code == 429:
                return ConnectionTestResult(
                    ok=False,
                    provider="openai_compatible",
                    model=None,
                    latency_ms=elapsed_ms,
                    message="Rate limit exceeded. Try again later.",
                )
            
            else:
                return ConnectionTestResult(
                    ok=False,
                    provider="openai_compatible",
                    model=None,
                    latency_ms=elapsed_ms,
                    message=f"Unexpected response: HTTP {response.status_code}.",
                )
    
    except Exception:
        # If completion also fails, return generic error
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        return ConnectionTestResult(
            ok=False,
            provider="openai_compatible",
            model=None,
            latency_ms=elapsed_ms,
            message="Connection test failed. Check base URL and model name.",
        )
