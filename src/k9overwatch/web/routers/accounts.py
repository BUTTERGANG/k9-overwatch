"""Account routes: register, login, logout, notification preferences."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.models import SavedSearch, User
from k9overwatch.db.repository import UserRepository
from k9overwatch.notifications import flush_digest
from k9overwatch.web.account_tokens import consume_token, issue_token
from k9overwatch.web.auth import (
    COOKIE_NAME,
    hash_password,
    is_production,
    make_session_token,
    verify_password,
)
from k9overwatch.web.dependencies import get_current_user_id, get_db, verify_admin
from k9overwatch.web.rate_limit import rate_limit
from k9overwatch.web.templates_config import templates

router = APIRouter()

_RECORD_TYPES = {"lost", "found", "sighting", "adoptable"}
_ANIMAL_TYPES = {"dog", "cat", "bird", "rabbit", "other"}
_CONFIDENCE = {"low", "medium", "high"}


def _saved_search_values(name, record_type, animal_type, species, latitude, longitude, radius_miles, days, min_confidence):
    name = name.strip()
    if not name or len(name) > 120:
        raise HTTPException(status_code=400, detail="Search name must be 1–120 characters.")
    if record_type not in _RECORD_TYPES or (animal_type and animal_type not in _ANIMAL_TYPES):
        raise HTTPException(status_code=400, detail="Invalid search type.")
    try:
        parsed_days = int(days or 30)
        parsed_radius = int(radius_miles) if radius_miles else None
        lat = float(latitude) if latitude else None
        lon = float(longitude) if longitude else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Search numbers must be valid.") from exc
    if not 1 <= parsed_days <= 365:
        raise HTTPException(status_code=400, detail="Recency must be between 1 and 365 days.")
    if parsed_radius is not None and not 1 <= parsed_radius <= 100:
        raise HTTPException(status_code=400, detail="Radius must be between 1 and 100 miles.")
    if ((lat is None) != (lon is None) or (lat is not None and not -90 <= lat <= 90)
            or (lon is not None and not -180 <= lon <= 180)):
        raise HTTPException(status_code=400, detail="Latitude and longitude must be a valid pair.")
    if min_confidence not in _CONFIDENCE:
        raise HTTPException(status_code=400, detail="Invalid confidence threshold.")
    return {"name": name, "record_type": record_type, "animal_type": animal_type or None,
            "species": species.strip()[:120] or None, "latitude": lat, "longitude": lon,
            "radius_miles": parsed_radius, "days": parsed_days, "min_confidence": min_confidence}


def _set_session(resp, user: User) -> None:
    resp.set_cookie(
        COOKIE_NAME,
        make_session_token(user.id),
        httponly=True,
        secure=is_production(),
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


@router.post("/login", dependencies=[Depends(rate_limit("login", limit=10))])
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
    if not user.email_verified:
        return templates.TemplateResponse(
            request, "accounts/login.html",
            {"error": "Please verify your email before logging in."}, status_code=403
        )
    resp = RedirectResponse(url="/map", status_code=302)
    _set_session(resp, user)
    return resp


@router.get("/register")
async def register_page(request: Request):
    if await get_current_user_id(request):
        return RedirectResponse(url="/map", status_code=302)
    return templates.TemplateResponse(request, "accounts/register.html", {})


@router.post("/register", dependencies=[Depends(rate_limit("register", limit=5))])
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
    await issue_token(db, user, "email_verification")
    await db.commit()
    return templates.TemplateResponse(
        request, "accounts/message.html",
        {"title": "Check your email", "message": "Your account is ready. Use the verification link in the queued email to activate login."},
    )


@router.get("/account/email-verification")
async def verify_email(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    issued = await consume_token(db, token, "email_verification")
    if issued is None:
        return templates.TemplateResponse(
            request, "accounts/message.html",
            {"title": "Invalid verification link", "message": "This link is expired, already used, or invalid."}, status_code=400,
        )
    user = await db.get(User, issued.user_id)
    user.email_verified = True
    await db.commit()
    return templates.TemplateResponse(
        request, "accounts/message.html",
        {"title": "Email verified", "message": "Your email is verified. You can now log in."},
    )


@router.get("/forgot-password")
async def forgot_password_page(request: Request):
    return templates.TemplateResponse(request, "accounts/forgot_password.html", {})


@router.post("/forgot-password", dependencies=[Depends(rate_limit("forgot-password", limit=5))])
async def forgot_password(request: Request, email: str = Form(...), db: AsyncSession = Depends(get_db)):
    user = await UserRepository(db).get_by_email(email)
    if user:
        await issue_token(db, user, "password_reset")
        await db.commit()
    return templates.TemplateResponse(
        request, "accounts/message.html",
        {"title": "Check your email", "message": "If an account matches that email, a reset link has been queued."},
    )


@router.get("/reset-password")
async def reset_password_page(request: Request, token: str):
    return templates.TemplateResponse(request, "accounts/reset_password.html", {"token": token})


@router.post("/reset-password", dependencies=[Depends(rate_limit("reset-password", limit=5))])
async def reset_password(
    request: Request, token: str = Form(...), password: str = Form(...), db: AsyncSession = Depends(get_db)
):
    if len(password) < 8:
        return templates.TemplateResponse(request, "accounts/reset_password.html", {"token": token, "error": "Password must be at least 8 characters."}, status_code=400)
    issued = await consume_token(db, token, "password_reset")
    if issued is None:
        return templates.TemplateResponse(request, "accounts/message.html", {"title": "Invalid reset link", "message": "This link is expired, already used, or invalid."}, status_code=400)
    user = await db.get(User, issued.user_id)
    user.password_hash = hash_password(password)
    await db.commit()
    return templates.TemplateResponse(request, "accounts/message.html", {"title": "Password reset", "message": "Your password has been reset. You can now log in."})


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
    from k9overwatch.db.models import ContactRequest
    contact_stmt = select(ContactRequest, PetRow, User).join(
        PetRow, PetRow.id == ContactRequest.pet_id
    ).join(User, User.id == ContactRequest.requester_id).where(
        ContactRequest.recipient_id == user_id,
        ContactRequest.status.in_(["open", "in_conversation"]),
    ).order_by(ContactRequest.created_at.desc())
    contact_requests = [
        {"contact": contact, "pet": pet, "requester": requester}
        for contact, pet, requester in (await db.execute(contact_stmt)).all()
    ]
    outgoing_stmt = select(ContactRequest, PetRow, User).join(
        PetRow, PetRow.id == ContactRequest.pet_id
    ).join(User, User.id == ContactRequest.recipient_id).where(
        ContactRequest.requester_id == user_id,
    ).order_by(ContactRequest.created_at.desc())
    outgoing_requests = [
        {"contact": contact, "pet": pet, "recipient": recipient}
        for contact, pet, recipient in (await db.execute(outgoing_stmt)).all()
    ]
    saved_searches = list((await db.execute(
        select(SavedSearch).where(SavedSearch.user_id == user_id).order_by(SavedSearch.created_at.desc())
    )).scalars().all())
    return templates.TemplateResponse(
        request, "accounts/account.html", {
            "user": user, "prefs": prefs, "my_reports": my_reports,
            "contact_requests": contact_requests, "outgoing_requests": outgoing_requests,
            "saved_searches": saved_searches,
        }
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


@router.post("/account/saved-searches")
async def create_saved_search(
    request: Request,
    name: str = Form(...), record_type: str = Form("lost"), animal_type: str = Form(""),
    species: str = Form(""), latitude: str = Form(""), longitude: str = Form(""),
    radius_miles: str = Form(""), days: str = Form("30"), min_confidence: str = Form("medium"),
    db: AsyncSession = Depends(get_db),
):
    user_id = await get_current_user_id(request)
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    values = _saved_search_values(name, record_type, animal_type, species, latitude, longitude, radius_miles, days, min_confidence)
    db.add(SavedSearch(user_id=user_id, **values))
    await db.commit()
    return RedirectResponse(url="/account?saved_search=1", status_code=303)


@router.post("/account/saved-searches/{search_id}")
async def update_saved_search(
    search_id: str, request: Request, name: str = Form(...), record_type: str = Form("lost"),
    animal_type: str = Form(""), species: str = Form(""), latitude: str = Form(""),
    longitude: str = Form(""), radius_miles: str = Form(""), days: str = Form("30"),
    min_confidence: str = Form("medium"), db: AsyncSession = Depends(get_db),
):
    user_id = await get_current_user_id(request)
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    saved = (await db.execute(select(SavedSearch).where(
        SavedSearch.id == search_id, SavedSearch.user_id == user_id
    ))).scalar_one_or_none()
    if saved is None:
        raise HTTPException(status_code=404, detail="Saved search not found")
    for key, value in _saved_search_values(name, record_type, animal_type, species, latitude, longitude, radius_miles, days, min_confidence).items():
        setattr(saved, key, value)
    await db.commit()
    return RedirectResponse(url="/account?saved_search=1", status_code=303)


@router.post("/account/saved-searches/{search_id}/delete")
async def delete_saved_search(search_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await get_current_user_id(request)
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    saved = (await db.execute(select(SavedSearch).where(
        SavedSearch.id == search_id, SavedSearch.user_id == user_id
    ))).scalar_one_or_none()
    if saved is None:
        raise HTTPException(status_code=404, detail="Saved search not found")
    await db.delete(saved)
    await db.commit()
    return RedirectResponse(url="/account?saved_search=1", status_code=303)


@router.post("/account/saved-searches/{search_id}/toggle")
async def toggle_saved_search(
    search_id: str,
    request: Request,
    enabled: bool = Form(False),
    db: AsyncSession = Depends(get_db),
):
    """Enable or disable a saved search without deleting it."""
    user_id = await get_current_user_id(request)
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    saved = (await db.execute(select(SavedSearch).where(
        SavedSearch.id == search_id, SavedSearch.user_id == user_id
    ))).scalar_one_or_none()
    if saved is None:
        raise HTTPException(status_code=404, detail="Saved search not found")
    saved.enabled = enabled
    await db.commit()
    return RedirectResponse(url="/account?saved_search=1", status_code=303)


@router.post("/contact-requests/{contact_id}/status")
async def update_contact_status(
    contact_id: str,
    request: Request,
    status_value: str = Form(..., alias="status"),
    db: AsyncSession = Depends(get_db),
):
    """Allow only the two relay participants to advance a handoff status."""
    user_id = await get_current_user_id(request)
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    allowed_statuses = {"open", "in_conversation", "handoff_arranged", "reunited", "closed"}
    if status_value not in allowed_statuses:
        raise HTTPException(status_code=400, detail="Invalid contact request status.")
    from k9overwatch.db.models import ContactRequest
    contact = await db.get(ContactRequest, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact request not found")
    if user_id not in (contact.requester_id, contact.recipient_id):
        raise HTTPException(status_code=403, detail="You are not a participant in this contact request.")
    contact.status = status_value
    await db.commit()
    return RedirectResponse(url="/account", status_code=303)


@router.post("/reports/{report_id}/status")
async def update_report_status(
    report_id: str,
    request: Request,
    status_value: str = Form(..., alias="status"),
    db: AsyncSession = Depends(get_db),
):
    """Let a report owner close the loop when their pet is found or reunited."""
    user_id = await get_current_user_id(request)
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    from k9overwatch.db.models import PetRow

    allowed = {"open", "resolved", "reunited", "closed"}
    if status_value not in allowed:
        raise HTTPException(status_code=400, detail="Invalid report status.")
    report = (await db.execute(select(PetRow).where(
        PetRow.id == report_id, PetRow.owner_id == user_id, PetRow.source == "user"
    ))).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    report.owner_report_status = status_value
    report.active = status_value == "open"
    await db.commit()
    return RedirectResponse(url="/account?report_saved=1", status_code=303)


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


@router.post("/admin/flush-digest", dependencies=[Depends(verify_admin)])
async def flush_digest_endpoint(db: AsyncSession = Depends(get_db)):
    """Triggers the daily digest send (normally by the scheduler)."""
    sent = await flush_digest()
    return {"sent": sent}


# ── Contact request reply ───────────────────────────────────────────────


@router.post("/contact-requests/{contact_id}/reply")
async def reply_to_contact_request(
    contact_id: str,
    request: Request,
    message: str = Form(..., min_length=1, max_length=2000),
    db: AsyncSession = Depends(get_db),
):
    """Send a threaded reply inside a contact relay conversation."""
    from k9overwatch.db.models import ContactBlock, ContactMessage, ContactRequest

    user_id = await get_current_user_id(request)
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    contact = await db.get(ContactRequest, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact request not found")
    if user_id not in (contact.requester_id, contact.recipient_id):
        raise HTTPException(status_code=403, detail="You are not a participant in this contact request.")
    # Check blocks: if either party has blocked the other, deny the reply
    blocked = await db.execute(
        select(ContactBlock).where(
            ContactBlock.blocker_id == contact.recipient_id,
            ContactBlock.blocked_id == user_id,
        )
    )
    if blocked.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="You have been blocked by the recipient.")
    msg = ContactMessage(contact_id=contact_id, sender_id=user_id, message=message.strip())
    db.add(msg)
    if contact.status in ("open",):
        contact.status = "in_conversation"
    await db.commit()
    return RedirectResponse(url="/account", status_code=303)


# ── Block user on contact ──────────────────────────────────────────────


@router.post("/contact-requests/{contact_id}/block")
async def block_user_on_contact(
    contact_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Block the other party on a contact request and close it."""
    from k9overwatch.db.models import ContactBlock, ContactRequest

    user_id = await get_current_user_id(request)
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    contact = await db.get(ContactRequest, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact request not found")
    if user_id not in (contact.requester_id, contact.recipient_id):
        raise HTTPException(status_code=403, detail="You are not a participant in this contact request.")
    blocked_id = contact.recipient_id if user_id == contact.requester_id else contact.requester_id
    existing = await db.get(ContactBlock, (user_id, blocked_id))
    if not existing:
        db.add(ContactBlock(blocker_id=user_id, blocked_id=blocked_id))
    contact.status = "closed"
    await db.commit()
    return RedirectResponse(url="/account", status_code=303)


# ── Messages for a contact request (HTMX JSON) ─────────────────────────


@router.get("/contact-requests/{contact_id}/messages")
async def get_contact_request_messages(
    contact_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Return messages for a contact request as an HTML partial for HTMX."""
    from k9overwatch.db.models import ContactMessage, ContactRequest

    user_id = await get_current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Login required")
    contact = await db.get(ContactRequest, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact request not found")
    if user_id not in (contact.requester_id, contact.recipient_id):
        raise HTTPException(status_code=403, detail="You are not a participant.")
    stmt = (
        select(ContactMessage)
        .where(ContactMessage.contact_id == contact_id)
        .order_by(ContactMessage.created_at.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return templates.TemplateResponse(
        request, "accounts/_messages.html",
        {"messages": rows, "current_user_id": user_id},
    )


# ── Edit report form ────────────────────────────────────────────────────


@router.get("/reports/{report_id}/edit")
async def edit_report_form(
    report_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Pre-populated edit form for the report owner."""
    from k9overwatch.db.models import PetRow

    user_id = await get_current_user_id(request)
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    report = (await db.execute(
        select(PetRow).where(PetRow.id == report_id, PetRow.owner_id == user_id)
    )).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return templates.TemplateResponse(request, "accounts/edit_report.html", {"report": report})


# ── Edit report submission ──────────────────────────────────────────────


@router.post("/reports/{report_id}/edit")
async def edit_report(
    report_id: str,
    request: Request,
    name: str = Form(default=""),
    breed: str = Form(default=""),
    color_primary: str = Form(default=""),
    gender: str = Form(default=""),
    distinctive_features: str = Form(default=""),
    description: str = Form(default=""),
    location_text: str = Form(default=""),
    contact_name: str = Form(default=""),
    contact_email: str = Form(default=""),
    contact_phone: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    """Owner updates report fields; re-geocode if location changed."""
    from k9overwatch.db.models import PetRow

    user_id = await get_current_user_id(request)
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    report = (await db.execute(
        select(PetRow).where(PetRow.id == report_id, PetRow.owner_id == user_id)
    )).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    location_changed = location_text.strip() != (report.location_text or "")
    report.name = name.strip() or None
    report.breed = breed.strip() or None
    report.color_primary = color_primary.strip() or None
    report.gender = gender.strip() or None
    report.distinctive_features = distinctive_features.strip() or None
    report.description = description.strip() or None
    report.location_text = location_text.strip() or None
    report.contact_name = contact_name.strip() or None
    report.contact_email = contact_email.strip() or None
    report.contact_phone = contact_phone.strip() or None

    if location_changed and report.location_text:
        from k9overwatch.models.pet_record import PetRecord
        from k9overwatch.scheduler.jobs import _make_geocoder_from_env

        # Convert PetRow → PetRecord for the geocoder, then copy coords back
        pr = PetRecord(
            source=report.source,
            source_id=report.source_id,
            record_type=report.record_type,
            location_text=report.location_text,
            city=report.city,
            state=report.state,
            zip=report.zip,
            country=report.country or "US",
        )
        geocoder = _make_geocoder_from_env(db)
        pr = await geocoder.geocode(pr)
        report.lat = pr.lat
        report.lon = pr.lon
        report.geocode_source = pr.geocode_source
        report.geocode_confidence = pr.geocode_confidence

    await db.commit()
    return RedirectResponse(url=f"/pets/{report_id}", status_code=303)


# ── Flag report (as ContentReport) ─────────────────────────────────────


@router.post("/reports/{report_id}/flag")
async def flag_report(
    report_id: str,
    request: Request,
    reason: str = Form(..., min_length=1, max_length=1000),
    db: AsyncSession = Depends(get_db),
):
    """Create a ContentReport targeting a pet report."""
    from k9overwatch.db.models import ContentReport, PetRow

    user_id = await get_current_user_id(request)
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    pet = await db.get(PetRow, report_id)
    if pet is None:
        raise HTTPException(status_code=404, detail="Report not found")
    db.add(ContentReport(
        reporter_id=user_id,
        target_type="report",
        target_id=report_id,
        reason=reason.strip(),
    ))
    await db.commit()
    return RedirectResponse(url=f"/pets/{report_id}?flagged=1", status_code=303)


# ── Flag contact request ───────────────────────────────────────────────


@router.post("/contact-requests/{contact_id}/flag")
async def flag_contact_request(
    contact_id: str,
    request: Request,
    reason: str = Form(..., min_length=1, max_length=1000),
    db: AsyncSession = Depends(get_db),
):
    """Create a ContentReport targeting a contact request."""
    from k9overwatch.db.models import ContactRequest, ContentReport

    user_id = await get_current_user_id(request)
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    contact = await db.get(ContactRequest, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact request not found")
    db.add(ContentReport(
        reporter_id=user_id,
        target_type="contact_request",
        target_id=contact_id,
        reason=reason.strip(),
    ))
    await db.commit()
    return RedirectResponse(url="/account", status_code=303)

