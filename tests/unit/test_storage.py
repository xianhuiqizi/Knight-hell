"""Storage configuration provides a stable local-to-enterprise switch."""

import pytest

from flowremote.control_plane.db import (
    Database,
    StorageBackend,
    resolve_storage_config,
)


def clear_storage_env(monkeypatch):
    for name in (
        "FLOWREMOTE_DATABASE_URL",
        "FLOWREMOTE_STORAGE_MODE",
        "FLOWREMOTE_ENTERPRISE_DATABASE_URL",
        "DATABASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_local_sqlite_is_the_default(monkeypatch):
    clear_storage_env(monkeypatch)
    config = resolve_storage_config()
    assert config.mode == "local"
    assert config.engine == "sqlite"
    assert config.url.startswith("sqlite:///")
    assert isinstance(Database(), StorageBackend)


def test_explicit_postgresql_url_selects_enterprise_mode(monkeypatch):
    clear_storage_env(monkeypatch)
    url = "postgresql://flowremote:secret@db.example.com:5432/flowremote"
    config = resolve_storage_config(url)
    assert config.mode == "enterprise"
    assert config.engine == "postgres"
    assert config.source == "explicit"


def test_flowremote_database_url_has_priority(monkeypatch):
    clear_storage_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///legacy.db")
    monkeypatch.setenv("FLOWREMOTE_DATABASE_URL", "sqlite:///preferred.db")
    config = resolve_storage_config()
    assert config.url == "sqlite:///preferred.db"
    assert config.source == "FLOWREMOTE_DATABASE_URL"


def test_enterprise_mode_requires_an_enterprise_url(monkeypatch):
    clear_storage_env(monkeypatch)
    monkeypatch.setenv("FLOWREMOTE_STORAGE_MODE", "enterprise")
    with pytest.raises(ValueError, match="no PostgreSQL URL"):
        resolve_storage_config()

    monkeypatch.setenv(
        "FLOWREMOTE_ENTERPRISE_DATABASE_URL",
        "postgresql://enterprise:secret@db.example.com/flowremote",
    )
    config = resolve_storage_config()
    assert config.mode == "enterprise"
    assert config.engine == "postgres"
    assert config.source == "FLOWREMOTE_ENTERPRISE_DATABASE_URL"


def test_enterprise_mode_rejects_sqlite(monkeypatch):
    clear_storage_env(monkeypatch)
    monkeypatch.setenv("FLOWREMOTE_STORAGE_MODE", "enterprise")
    monkeypatch.setenv("FLOWREMOTE_ENTERPRISE_DATABASE_URL", "sqlite:///wrong.db")
    with pytest.raises(ValueError, match="requires a PostgreSQL"):
        resolve_storage_config()


def test_invalid_storage_url_does_not_echo_credentials(monkeypatch):
    clear_storage_env(monkeypatch)
    secret_url = "mysql://user:top-secret@db.example.com/flowremote"
    with pytest.raises(ValueError) as exc_info:
        resolve_storage_config(secret_url)
    assert "top-secret" not in str(exc_info.value)
