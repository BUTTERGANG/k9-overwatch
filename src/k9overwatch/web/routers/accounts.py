"""Account routes: register, login, logout, notification preferences."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.models import User
from k9overwatch.db.repository import UserRepository
from k9overwatch.notifications import flush_digest
from k9overwatch.web.auth import COOKIE_NAME, make_session_token, verify_password
from k9overwatch.web.dependencies import get_current_user_id, get_db
from k9overwatch.web.templates_config import templates

router = APIRouter()


def _set_session(resp, user: User) -> None:
    resp.set_cookie(
        COOKIE_NAME,
        make_session_token(user.id),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )


def _clear_session(resp) -> None:
    resp.delete_cookie(COOKIE_NAME)


@router.get("/login")
async def login_page(request: Request):
    if await get_current_user_id(request):
        return RedirectResponse(url="/map", status_code=302)
    return templates.TemplateResponse(request, "accounts/login.html", {})


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    users = UserRepository(db)
    user = await users.get_by_email(email)
    if user is None or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request, "accounts/login.html", {"error": "Email or password is incorrect."}, status_code=401
        )
    if not user.is_active:
        return templates.TemplateResponse(
            request, "accounts/login.html", {"error": "This account is disabled."}, status_code=403
        )
    resp = RedirectResponse(url="/map", status_code=302)
    _set_session(resp, user)
    return resp


@router.get("/register")
async def register_page(request: Request):
    if await get_current_user_id(request):
        return RedirectResponse(url="/map", status_code=302)
    return templates.TemplateResponse(request, "accounts/register.html", {})


@router.post("/register")
async def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    display_name: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    email = email.strip().lower()
    if "@" not in email or len(password) < 8:
        return templates.TemplateResponse(
            request,
            "accounts/register.html",
            {"error": "Enter a valid email and a password of at least 8 characters."},
            status_code=400,
        )
    users = UserRepository(db)
    if await users.get_by_email(email):
        return templates.TemplateResponse(
            request,
            "accounts/register.html",
            {"error": "An account with that email already exists."},
            status_code=409,
        )
    user = await users.create(email, password, display_name or None)
    await db.commit()
    resp = RedirectResponse(url="/account", status_code=302)
    _set_session(resp, user)
    return resp


@router.get("/logout")
async def logout():
    resp = RedirectResponse(url="/map", status_code=302)
    _clear_session(resp)
    return resp


@router.get("/account")
async def account_page(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await get_current_user_id(request)
    if not user_id:
        return RedirectResponse(url="/login", status_code=302)
    users = UserRepository(db)
    user = await users.get_by_id(user_id)
    prefs = await users.get_prefs(user_id)
    # Reports this user submitted
    from sqlalchemy import select

    from k9overwatch.db.models import PetRow

    stmt = select(PetRow).where(PetRow.owner_id == user_id).order_by(PetRow.date_posted.desc())
    my_reports = list((await db.execute(stmt)).scalars().all())
    return templates.TemplateResponse(
        request, "accounts/account.html", {"user": user, "prefs": prefs, "my_reports": my_reports}
    )


@router.post("/account/preferences")
async def save_preferences(
    request: Request,
    frequency: str = Form("digest"),
    min_confidence: str = Form("medium"),
    notify_on_found_match: bool = Form(False),
    email_enabled: bool = Form(True),
    db: AsyncSession = Depends(get_db),
):
    user_id = await get_current_user_id(request)
    if not user_id:
        return RedirectResponse(url="/login", status_code=302)
    if frequency not in ("off", "digest", "instant"):
        frequency = "digest"
    if min_confidence not in ("low", "medium", "high"):
        min_confidence = "medium"
    users = UserRepository(db)
    await users.save_prefs(
        user_id,
        frequency=frequency,
        min_confidence=min_confidence,
        notify_on_found_match=notify_on_found_match,
        email_enabled=email_enabled,
    )
    await db.commit()
    return RedirectResponse(url="/account?saved=1", status_code=302)


@router.get("/unsubscribe")
async def unsubscribe(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    """One-click opt-out from the email footer — no login required."""
    from k9overwatch.db.models import NotificationPrefs

    stmt = select(NotificationPrefs).where(NotificationPrefs.unsubscribe_token == token)
    prefs = (await db.execute(stmt)).scalar_one_or_none()
    if prefs is None:
        return templates.TemplateResponse(
            request, "accounts/message.html",
            {"title": "Already unsubscribed", "message": "That link is no longer valid."},
            status_code=404,
        )
    prefs.frequency = "off"
    prefs.email_enabled = False
    await db.commit()
    return templates.TemplateResponse(
        request, "accounts/message.html",
        {"title": "You're unsubscribed", "message": "You won't get match emails from K9-Overwatch anymore."},
    )


@router.post("/admin/flush-digest")
async def flush_digest_endpoint(db: AsyncSession = Depends(get_db)):
    """Triggers the daily digest send (normally run by the scheduler)."""
    sent = await flush_digest()
    return {"sent": sent}

