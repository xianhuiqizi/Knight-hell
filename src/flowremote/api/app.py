"""Application factory.

``create_app`` takes the database URL and the session secret as arguments so
tests can build an isolated app without touching the development database.
The module-level ``app`` is what uvicorn imports.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from flowremote.agent.providers import SuggestionProvider, provider_from_env
from flowremote.api.routes import ai_settings as ai_settings_routes
from flowremote.api.routes import approval as approval_routes
from flowremote.api.routes import execution as execution_routes
from flowremote.api.routes import review as review_routes
from flowremote.api.routes import session as session_routes
from flowremote.api.routes import suggestions as suggestion_routes
from flowremote.api.routes import tasks as task_routes
from flowremote.api.routes import uploads as upload_routes
from flowremote.api.sessions import SessionSigner, load_or_create_secret
from flowremote.control_plane.ai_settings import AISettingCipher
from flowremote.control_plane.db import (
    PROJECT_ROOT,
    Database,
    StorageBackend,
    resolve_storage_config,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = PACKAGE_ROOT / "ui"
SECRET_PATH = PROJECT_ROOT / "data" / "runtime" / "session.key"
load_dotenv(PROJECT_ROOT / ".env")


def create_app(
    database_url: str | None = None,
    session_secret: str | None = None,
    upload_dir: Path | None = None,
    suggestion_provider: SuggestionProvider | None = None,
    customer_registry: Path | None = None,
    database_factory: Callable[[str | None], StorageBackend] = Database,
) -> FastAPI:
    storage = resolve_storage_config(database_url)
    url = storage.url
    secret = session_secret or os.environ.get("SESSION_SECRET") or load_or_create_secret(SECRET_PATH)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Make sure the schema exists before the first request.
        with database_factory(url) as db:
            db.apply_migrations()
        yield

    app = FastAPI(title="FlowRemote", version="0.3.0", lifespan=lifespan)
    app.state.database_url = url
    app.state.database_factory = database_factory
    app.state.storage = storage
    app.state.upload_dir = Path(upload_dir or os.environ.get("FLOWREMOTE_UPLOAD_DIR")
                               or PROJECT_ROOT / "data" / "runtime" / "uploads")
    app.state.suggestion_provider_override = suggestion_provider
    app.state.suggestion_provider = suggestion_provider or provider_from_env()
    app.state.ai_settings_cipher = AISettingCipher(secret)
    app.state.customer_registry = Path(
        customer_registry
        or os.environ.get("FLOWREMOTE_CUSTOMER_REGISTRY")
        or PROJECT_ROOT / "data" / "seed" / "customer_registry.csv"
    )
    app.state.signer = SessionSigner(secret)
    app.state.templates = Jinja2Templates(directory=str(UI_ROOT / "templates"))
    app.mount("/static", StaticFiles(directory=str(UI_ROOT / "static")), name="static")
    app.include_router(ai_settings_routes.router)
    app.include_router(session_routes.router)
    app.include_router(upload_routes.router)
    app.include_router(task_routes.router)
    app.include_router(review_routes.router)
    app.include_router(suggestion_routes.router)
    app.include_router(approval_routes.router)
    app.include_router(execution_routes.router)
    return app


app = create_app()
