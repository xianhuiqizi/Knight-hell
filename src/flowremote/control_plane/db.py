"""Database access for FlowRemote: one connection string, portable SQL.

Development runs on SQLite (a single file, nothing to install) while the target
deployment is PostgreSQL. The two stay interchangeable because of five rules
that every module follows:

1. ``DATABASE_URL`` is the only place the engine is chosen.
2. SQL stays inside the subset both engines share: TEXT / INTEGER / REAL,
   CHECK and UNIQUE constraints, no engine specific syntax.
3. Timestamps are stored as UTC ISO-8601 text, for example
   ``2026-09-30T14:31:00Z``. SQLite has no real date type, and text keeps the
   two engines identical.
4. Placeholders are written as ``?`` in the source and translated to ``%s``
   for PostgreSQL.
5. SQLite runs with foreign keys ON (SQLite does not enforce them by default),
   WAL journaling, and a busy timeout.

Everything in the project goes through this module, so a mistake in those rules
shows up in one file instead of twenty.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, Self, runtime_checkable

# src/flowremote/control_plane/db.py -> project root is three levels up.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
DEFAULT_SQLITE_PATH = PROJECT_ROOT / "data" / "runtime" / "flowremote.db"


@dataclass(frozen=True)
class StorageConfig:
    """Resolved storage location and its deployment mode."""

    url: str
    mode: str
    source: str

    @property
    def engine(self) -> str:
        return "sqlite" if self.url.startswith("sqlite:") else "postgres"


@runtime_checkable
class StorageBackend(Protocol):
    """The database surface used by routes and control-plane modules.

    A different enterprise database adapter can implement this protocol and be
    injected into ``create_app`` without changing authentication or routes.
    """

    url: str
    engine: str

    def connect(self) -> Self: ...

    def close(self) -> None: ...

    def __enter__(self) -> Self: ...

    def __exit__(self, *_exc: object) -> None: ...

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any: ...

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict]: ...

    def scalar(
        self, sql: str, params: Sequence[Any] = (), default: Any = None
    ) -> Any: ...

    def transaction(self) -> Any: ...

    def apply_migrations(self, directory: Path | None = None) -> list[str]: ...


def utc_now() -> str:
    """Current UTC time as ISO-8601 text with second precision."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    """Short unique identifier, for example EXC-3F9C2A1B07."""
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def _storage_config(url: str, source: str) -> StorageConfig:
    if url.startswith("sqlite:"):
        return StorageConfig(url=url, mode="local", source=source)
    if url.startswith(("postgresql:", "postgres:")):
        return StorageConfig(url=url, mode="enterprise", source=source)
    raise ValueError(f"unsupported database URL in {source}")


def resolve_storage_config(url: str | None = None) -> StorageConfig:
    """Resolve local or enterprise storage without changing application code.

    Precedence:
    1. explicit argument;
    2. ``FLOWREMOTE_DATABASE_URL``;
    3. enterprise variables when ``FLOWREMOTE_STORAGE_MODE=enterprise``;
    4. legacy ``DATABASE_URL``;
    5. local SQLite.
    """
    if url:
        return _storage_config(url.strip(), "explicit")

    configured = os.environ.get("FLOWREMOTE_DATABASE_URL", "").strip()
    if configured:
        return _storage_config(configured, "FLOWREMOTE_DATABASE_URL")

    mode = os.environ.get("FLOWREMOTE_STORAGE_MODE", "").strip().lower()
    if mode in {"enterprise", "server"}:
        enterprise = os.environ.get("FLOWREMOTE_ENTERPRISE_DATABASE_URL", "").strip()
        if not enterprise:
            enterprise = os.environ.get("DATABASE_URL", "").strip()
        if not enterprise:
            raise ValueError(
                "Enterprise storage is selected but no PostgreSQL URL is configured."
            )
        config = _storage_config(enterprise, "FLOWREMOTE_ENTERPRISE_DATABASE_URL")
        if config.engine != "postgres":
            raise ValueError("Enterprise storage mode requires a PostgreSQL database URL.")
        return config
    if mode and mode != "local":
        raise ValueError(
            "FLOWREMOTE_STORAGE_MODE must be 'local' or 'enterprise', "
            f"got {mode!r}"
        )

    legacy = os.environ.get("DATABASE_URL", "").strip()
    if legacy:
        return _storage_config(legacy, "DATABASE_URL")
    return _storage_config(
        "sqlite:///" + DEFAULT_SQLITE_PATH.as_posix(),
        "local default",
    )


def database_url(url: str | None = None) -> str:
    """Backward-compatible connection-string helper."""
    return resolve_storage_config(url).url


class Database:
    """A small wrapper so no other module has to think about the engine."""

    def __init__(self, url: str | None = None) -> None:
        self.storage = resolve_storage_config(url)
        self.url = self.storage.url
        self.engine = self.storage.engine
        self.mode = self.storage.mode
        self._conn: Any = None

    # -- connection ------------------------------------------------------
    @property
    def is_memory(self) -> bool:
        """True for the in-memory URL, which tests use to avoid the disk."""
        return self.engine == "sqlite" and self.url.split("sqlite://", 1)[1].lstrip("/") == ":memory:"

    def sqlite_path(self) -> Path:
        raw = self.url.split("sqlite:///", 1)[1]
        path = Path(raw)
        return path if path.is_absolute() else PROJECT_ROOT / path

    def connect(self) -> Self:
        if self.engine == "sqlite":
            if self.is_memory:
                conn = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
            else:
                path = self.sqlite_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                # FastAPI runs a sync dependency and a sync handler in different
                # threadpool threads, so the connection must be allowed to move
                # between them. sqlite3 is serialized by default, and one
                # connection is used by one request at a time.
                conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA busy_timeout = 5000")
        else:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError(
                    "PostgreSQL is selected in DATABASE_URL but the driver is missing. "
                    'Install it with: pip install "psycopg[binary]"'
                ) from exc
            conn = psycopg.connect(self.url, autocommit=True, row_factory=dict_row)
        self._conn = conn
        return self

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> Self:
        return self.connect()

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _require(self) -> Any:
        if self._conn is None:
            raise RuntimeError("Database.connect() was not called")
        return self._conn

    # -- statements ------------------------------------------------------
    def _sql(self, sql: str) -> str:
        return sql if self.engine == "sqlite" else sql.replace("?", "%s")

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        return self._require().execute(self._sql(sql), tuple(params))

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        rows = self.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def scalar(self, sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
        rows = self.query(sql, params)
        if not rows:
            return default
        return next(iter(rows[0].values()))

    @contextmanager
    def transaction(self) -> Iterator[None]:
        conn = self._require()
        if self.engine == "sqlite":
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except Exception:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        else:
            with conn.transaction():
                yield

    # -- schema ----------------------------------------------------------
    def apply_migrations(self, directory: Path | None = None) -> list[str]:
        """Apply every migration file that has not run yet, in name order."""
        folder = directory or MIGRATIONS_DIR
        self.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            " version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        applied = {row["version"] for row in self.query("SELECT version FROM schema_version")}
        done: list[str] = []
        for path in sorted(folder.glob("*.sql")):
            version = path.stem
            if version in applied:
                continue
            statements = split_statements(path.read_text(encoding="utf-8"))
            with self.transaction():
                for statement in statements:
                    self.execute(statement)
                self.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (version, utc_now()),
                )
            done.append(version)
        return done


def split_statements(sql_text: str) -> list[str]:
    """Split a migration file into statements.

    One statement ends with a semicolon at the end of a line, and no semicolon
    appears inside a string literal. Keeping that rule is far cheaper than
    writing a SQL parser, and our migrations never need more.
    """
    statements: list[str] = []
    current: list[str] = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            statements.append("\n".join(current).rstrip().rstrip(";"))
            current = []
    if current:
        raise ValueError("migration ends with an unterminated statement: " + "\n".join(current))
    return statements


def open_database(url: str | None = None) -> StorageBackend:
    """Application database factory, replaceable for another enterprise adapter."""
    return Database(url)


def main() -> int:
    """Apply migrations and report where the database lives."""
    with Database() as db:
        applied = db.apply_migrations()
        print(f"engine  : {db.engine}")
        print(f"url     : {db.url}")
        print(f"applied : {', '.join(applied) if applied else 'nothing new'}")
        tables = db.query(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ) if db.engine == "sqlite" else []
        if tables:
            print("tables  : " + ", ".join(row["name"] for row in tables))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
