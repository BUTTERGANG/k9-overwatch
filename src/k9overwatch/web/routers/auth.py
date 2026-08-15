"""Authentication routes: register, login, logout."""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.repository import UserRepository
from k9overwatch.web.dependencies import get_db
from k9overwatch.web.templates_config import templates

router = APIRouter(prefix="/auth", tags=["auth"])

_ph = PasswordHasher()
_SESSION_DAYS = 30
_COOKIE_NAME = "session_id"


def _session_cookie_kwargs(value: str, max_age: int) -> dict:
    return {
        "key": _COOKIE_NAME,
        "value": value,
        "httponly": True,
        "samesite": "lax",           # lax allows GET redirects from other sites
        "secure": os.getenv("HTTPS", "false").lower() == "true",
        "max_age": max_age,
        "path": "/",
    }


# ── Register ──────────────────────────────────────────────────────────────────

@router.get("/register")
async def register_page(request: Request):
    return templates.TemplateResponse(request, "auth/register.html", {"error": None})


@router.post("/register")
async def register(
    request: Request,
    email: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    repo = UserRepository(db)

    # Validate
    email = email.strip().lower()
    display_name = display_name.strip()
    if not email or not display_name or not password:
        return templates.TemplateResponse(
            request, "auth/register.html",
            {"error": "All fields are required."},
            status_code=422,
        )
    if len(password) < 8:
        return templates.TemplateResponse(
            request, "auth/register.html",
            {"error": "Password must be at least 8 characters."},
            status_code=422,
        )

    existing = await repo.get_user_by_email(email)
    if existing:
        return templates.TemplateResponse(
            request, "auth/register.html",
            {"error": "An account with that email already exists."},
            status_code=422,
        )

    user = await repo.create_user(
        email=email,
        display_name=display_name,
        password_hash=_ph.hash(password),
    )

    now = datetime.now(UTC).replace(tzinfo=None)
    session = await repo.create_session(
        user_id=user.id,
        expires_at=now + timedelta(days=_SESSION_DAYS),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    response = RedirectResponse(url="/map", status_code=303)
    response.set_cookie(**_session_cookie_kwargs(session.id, _SESSION_DAYS * 86400))
    return response


# ── Login ─────────────────────────────────────────────────────────────────────

@router.get("/login")
async def login_page(request: Request, next: str = "/map"):
    return templates.TemplateResponse(request, "auth/login.html", {"error": None, "next": next})


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form(default="/map"),
    db: AsyncSession = Depends(get_db),
):
    repo = UserRepository(db)
    email = email.strip().lower()

    user = await repo.get_user_by_email(email)
    if user is None or user.password_hash is None:
        return templates.TemplateResponse(
            request, "auth/login.html",
            {"error": "Invalid email or password.", "next": next},
            status_code=401,
        )

    try:
        _ph.verify(user.password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return templates.TemplateResponse(
            request, "auth/login.html",
            {"error": "Invalid email or password.", "next": next},
            status_code=401,
        )

    if not user.active or user.banned:
        return templates.TemplateResponse(
            request, "auth/login.html",
            {"error": "This account is not active.", "next": next},
            status_code=403,
        )

    await repo.update_last_login(user.id)

    now = datetime.now(UTC).replace(tzinfo=None)
    session = await repo.create_session(
        user_id=user.id,
        expires_at=now + timedelta(days=_SESSION_DAYS),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    # Sanitize redirect — only allow relative paths
    if not next.startswith("/") or "//" in next:
        next = "/map"

    response = RedirectResponse(url=next, status_code=303)
    response.set_cookie(**_session_cookie_kwargs(session.id, _SESSION_DAYS * 86400))
    return response


# ── Logout ────────────────────────────────────────────────────────────────────

@router.post("/logout")
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    session_id = request.cookies.get(_COOKIE_NAME)
    if session_id:
        repo = UserRepository(db)
        await repo.revoke_session(session_id)

    response = RedirectResponse(url="/map", status_code=303)
    response.delete_cookie(_COOKIE_NAME, path="/")
    return response
