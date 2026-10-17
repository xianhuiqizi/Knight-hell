"""Shared request dependencies: a database handle and the signed-in user."""

from __future__ import annotations

from typing import Iterator

from fastapi import Depends, Request

from flowremote.api.sessions import COOKIE_NAME
from flowremote.contracts.models import User
from flowremote.control_plane.auth import get_user_row, to_user
from flowremote.control_plane.db import Database


def get_db(request: Request) -> Iterator[Database]:
    """One connection per request, closed afterwards.

    SQLite connections are cheap, and a per-request connection avoids sharing a
    connection between the threadpool threads FastAPI uses for sync handlers.
    """
    db = Database(request.app.state.database_url).connect()
    try:
        yield db
    finally:
        db.close()


def current_user(request: Request, db: Database = Depends(get_db)) -> User | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    user_id = request.app.state.signer.verify(token)
    if not user_id:
        return None
    row = get_user_row(db, user_id)
    return to_user(row) if row else None
