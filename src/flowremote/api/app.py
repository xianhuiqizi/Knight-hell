"""Application factory.

``create_app`` takes the database URL and the session secret as arguments so
tests can build an isolated app without touching the development database.
The module-level ``app`` is what uvicorn imports.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from flowremote.api.routes import session as session_routes
from flowremote.api.routes import approval as approval_routes
from flowremote.api.routes import review as review_routes
from flowremote.api.routes import tasks as task_routes
from flowremote.api.sessions import SessionSigner, load_or_create_secret
from flowremote.control_plane.db import PROJECT_ROOT, Database
from flowremote.control_plane.db import database_url as resolve_database_url

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = PACKAGE_ROOT / "ui"
SECRET_PATH = PROJECT_ROOT / "data" / "runtime" / "session.key"


def create_app(database_url: str | None = None, session_secret: str | None = None) -> FastAPI:
    url = resolve_database_url(database_url)
    secret = session_secret or os.environ.get("SESSION_SECRET") or load_or_create_secret(SECRET_PATH)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Make sure the schema exists before the first request.
        with Database(url) as db:
            db.apply_migrations()
        yield

    app = FastAPI(title="FlowRemote", version="0.2.0", lifespan=lifespan)
    app.state.database_url = url
    app.state.signer = SessionSigner(secret)
    app.state.templates = Jinja2Templates(directory=str(UI_ROOT / "templates"))
    app.mount("/static", StaticFiles(directory=str(UI_ROOT / "static")), name="static")
    app.include_router(session_routes.router)
    app.include_router(task_routes.router)
    app.include_router(review_routes.router)
    app.include_router(approval_routes.router)
    return app


app = create_app()
