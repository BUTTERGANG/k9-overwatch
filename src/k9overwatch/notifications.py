"""
Match notifications — deliberately low-spam by design.

Rules (per user NotificationPrefs):
  * Off entirely if frequency == "off" or email_enabled is False.
  * Only for matches at/above the user's min_confidence (default "medium" =>
    we never email about low-confidence "possible" matches — no false hope).
  * "instant": email as the match is found.
  * "digest": accumulate and send at most one email per day (see digest job).
  * Respect an unsubscribe token (footer link) without needing login.

Email sending is config-gated: if SMTP_HOST is not set, notifications are
logged and skipped (so local/dev runs never fail). This keeps the feature
real but safe to deploy incrementally.
"""
from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from k9overwatch.db.models import PetMatch, PetRow
from k9overwatch.db.repository import UserRepository

CONF_RANK = {"low": 0, "medium": 1, "high": 2}

# In-memory digest buffer (per process). The daily digest job flushes it.
_digest: dict[str, list] = {}


@dataclass
class MatchEvent:
    lost_pet: PetRow
    other_pet: PetRow
    match: PetMatch


def _smtp_configured() -> bool:
    return bool(os.getenv("SMTP_HOST"))


def _send_email(to_email: str, subject: str, body: str, unsubscribe_token: str) -> bool:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")
    from_addr = os.getenv("SMTP_FROM", "noreply@k9-overwatch.example")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email
    unsub_url = f"{os.getenv('APP_BASE_URL', '')}/unsubscribe?token={unsubscribe_token}"
    msg.set_content(body + f"\n\nTo stop these emails: {unsub_url}\n")
    try:
        with smtplib.SMTP(host, port, timeout=15) as s:
            if os.getenv("SMTP_TLS", "1") == "1":
                s.starttls()
            if user:
                s.login(user, password)
            s.send_message(msg)
        return True
    except Exception as exc:  # never block the pipeline on mail failure
        import logging
        logging.getLogger(__name__).warning(f"Notification email failed: {exc}")
        return False


async def notify_new_match(session, event: MatchEvent) -> bool:
    """
    Notify the owner of the LOST pet (if it's a user-submitted report) about a
    possible match. Returns True if an email was sent or queued.
    `session` is an open AsyncSession (caller's).
    """
    lost = event.lost_pet
    if lost.source != "user" or not lost.owner_id:
        return False  # only notify owners of reports they submitted

    repo = UserRepository(session)
    prefs = await repo.get_prefs(lost.owner_id)
    if prefs is None or prefs.frequency == "off" or not prefs.email_enabled:
        return False
    if CONF_RANK.get(event.match.confidence, 0) < CONF_RANK.get(prefs.min_confidence, 1):
        return False
    if event.match.match_type == "lost_found" and not prefs.notify_on_found_match:
        return False

    user = await repo.get_by_id(lost.owner_id)
    if not user:
        return False

    subject = "Possible match for your lost pet on K9-Overwatch"
    body = (
        f"Hi {user.display_name},\n\n"
        f"We found a possible match for {lost.name or 'your pet'} "
        f"({lost.breed or 'unknown breed'}) reported {lost.record_type}.\n\n"
        f"Match: {event.other_pet.name or 'Unknown'} "
        f"({event.other_pet.breed or 'unknown breed'}, {event.other_pet.record_type}) "
        f"in {event.other_pet.city or 'the area'}.\n"
        f"Confidence: {event.match.confidence}.\n\n"
        f"View it here: {os.getenv('APP_BASE_URL', '')}/pets/{event.other_pet.id}\n"
    )

    if prefs.frequency == "instant":
        if _smtp_configured():
            return _send_email(user.email, subject, body, prefs.unsubscribe_token)
        import logging
        logging.getLogger(__name__).info(f"[notify:instant] would email {user.email}: {subject}")
        return True
    # digest
    _digest.setdefault(user.email, []).append((subject, body, prefs.unsubscribe_token))
    return True


async def flush_digest() -> int:
    """Send at most one email per address summarizing the day's matches."""
    if not _digest:
        return 0
    sent = 0
    for email, items in _digest.items():
        token = items[-1][2]
        body = "\n---\n".join(b for _, b, _ in items)
        subject = f"{len(items)} possible match(es) for your lost pet"
        if _smtp_configured():
            if _send_email(email, subject, body, token):
                sent += 1
        else:
            import logging
            logging.getLogger(__name__).info(f"[notify:digest] would email {email}: {subject}")
            sent += 1
    _digest.clear()
    return sent
