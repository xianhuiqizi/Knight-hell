"""Sign up, sign in and sign out."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from flowremote.api.deps import current_user, get_db
from flowremote.api.forms import read_form
from flowremote.api.rendering import render
from flowremote.api.sessions import COOKIE_NAME
from flowremote.contracts.models import User
from flowremote.control_plane.auth import AccountError, authenticate, create_user
from flowremote.control_plane.db import Database
from flowremote.control_plane.user_management import onboarding_complete

router = APIRouter()


def _safe_next(value: str | None) -> str:
    """Only allow same-site relative redirects after login."""
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return "/"


def _sign_in(request: Request, response: RedirectResponse, user_id: str) -> RedirectResponse:
    signer = request.app.state.signer
    response.set_cookie(
        COOKIE_NAME,
        signer.sign(user_id),
        max_age=signer.max_age_seconds,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


DEMO_DAY_ACCOUNT = ("demo@flowremote.dev", "DemoDay2026!")
LEGACY_DEMO_ACCOUNT = ("alex.morgan@example.com", "123456")


@router.get("/demo", response_class=HTMLResponse)
def demo_landing(
    request: Request,
    user: User | None = Depends(current_user),  # noqa: B008 - FastAPI dependency idiom.
):
    if user:
        return RedirectResponse("/?guide=start", status_code=303)
    return render(request, "demo_landing.html", {"user": None})


@router.post("/demo/enter")
def demo_enter(request: Request, db: Database = Depends(get_db)):
    """One-click entry for a seeded demo, never creating an account."""
    for email, password in (DEMO_DAY_ACCOUNT, LEGACY_DEMO_ACCOUNT):
        row = authenticate(db, email, password)
        if row:
            destination = "/" if onboarding_complete(db, row["id"]) else "/onboarding"
            return _sign_in(request, RedirectResponse(destination, status_code=303), row["id"])
    return render(
        request,
        "login.html",
        {
            "user": None,
            "next": "/",
            "email": DEMO_DAY_ACCOUNT[0],
            "error": "The demo account is not seeded yet. Run "
            "python src/flowremote/devtools/seed_demoday.py --reset, then try again.",
        },
        status_code=503,
    )


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/", user: User | None = Depends(current_user)):
    if user:
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html", {"user": None, "next": _safe_next(next), "error": None})


@router.post("/login", response_class=HTMLResponse)
async def login(request: Request, db: Database = Depends(get_db)):
    form = await read_form(request)
    email = form.get("email", "")
    password = form.get("password", "")
    target = _safe_next(form.get("next"))
    row = authenticate(db, email, password)
    if row is None:
        return render(
            request, "login.html",
            {"user": None, "next": target, "email": email,
             "error": "That email and password do not match an account."},
            status_code=401,
        )
    destination = target
    if target == "/" and not onboarding_complete(db, row["id"]):
        destination = "/onboarding"
    return _sign_in(request, RedirectResponse(destination, status_code=303), row["id"])


@router.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request, user: User | None = Depends(current_user)):
    if user:
        return RedirectResponse("/", status_code=303)
    return render(request, "signup.html", {"user": None, "error": None, "values": {}})


@router.post("/signup", response_class=HTMLResponse)
async def signup(request: Request, db: Database = Depends(get_db)):
    form = await read_form(request)
    values = {"name": form.get("name", ""), "email": form.get("email", "")}
    if form.get("password") != form.get("password_again"):
        return render(
            request, "signup.html",
            {"user": None, "values": values, "error": "The two passwords do not match."},
            status_code=400,
        )
    try:
        row = create_user(
            db,
            name=values["name"],
            email=values["email"],
            password=form.get("password", ""),
            onboarding_completed=False,
        )
    except AccountError as exc:
        return render(
            request, "signup.html",
            {"user": None, "values": values, "error": str(exc)},
            status_code=400,
        )
    return _sign_in(
        request,
        RedirectResponse("/onboarding?new=1", status_code=303),
        row["id"],
    )


@router.post("/logout")
def logout() -> RedirectResponse:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response
