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

Delivery is durable: match and contact alerts are enqueued (see
PetRepository.enqueue_notification) and delivered by a worker with bounded
exponential backoff, so a transient provider outage never silently drops an
alert. Only the coalesced digest buffer below is in-memory; the scheduler
persists it into the same durable queue on flush.
"""
from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from k9overwatch.db.models import ContactRequest, PetMatch, PetRow
from k9overwatch.db.repository import PetRepository, UserRepository

CONF_RANK = {"low": 0, "medium": 1, "high": 2}

# In-memory digest buffer (per process), keyed by email. The daily digest job
# drains and persists it into the durable NotificationQueue so it is not lost
# across restarts. Each item is (subject, body, unsubscribe_token, user_id).
_digest: dict[str, list[tuple[str, str, str, str]]] = {}


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
        # Durable: enqueue for the delivery worker rather than sending inline,
        # so a transient provider failure never drops the reunion alert.
        enqueued = await PetRepository(session).enqueue_notification(
            user_id=user.id,
            subject=subject,
            body=body,
            kind="match",
            dedupe_key=f"match:{user.id}:{event.lost_pet.id}:{event.other_pet.id}",
            confidence=event.match.confidence,
        )
        return enqueued is not None
    # digest
    _digest.setdefault(user.email, []).append(
        (subject, body, prefs.unsubscribe_token, user.id)
    )
    return True


def drain_digest() -> dict[str, list[tuple[str, str, str, str]]]:
    """Return a copy of the pending digest buffer and clear it.

    The scheduler job enqueues each buffered digest into the durable
    NotificationQueue and then flushes the queue. Returning the buffer (rather
    than sending inline) makes digest delivery durable and multi-worker safe.
    """
    pending = dict(_digest)
    _digest.clear()
    return pending


async def flush_notification_queue(session, limit: int = 50) -> int:
    """Deliver eligible saved-search alerts with atomic claims and retries."""
    from datetime import UTC, datetime

    from k9overwatch.db.repository import PetRepository

    user_repo = UserRepository(session)
    queue_repo = PetRepository(session)
    queue_rows = await queue_repo.claim_notification_queue(limit=limit)
    now = datetime.now(UTC).replace(tzinfo=None)
    sent = 0
    for row in queue_rows:
        user = await user_repo.get_by_id(row.user_id)
        prefs = await user_repo.get_prefs(row.user_id)
        if not user or not prefs or prefs.frequency == "off" or not prefs.email_enabled:
            row.status = "skipped"
            continue
        delivered = True
        if _smtp_configured():
            delivered = _send_email(user.email, row.subject, row.body, prefs.unsubscribe_token)
        if delivered:
            row.status = "sent"
            row.sent_at = now
            row.next_attempt_at = None
            sent += 1
        else:
            await queue_repo.mark_notification_failed(row, "notification provider rejected delivery", now=now)
    await session.flush()
    return sent


async def notify_contact_request(session, contact: ContactRequest, pet: PetRow) -> bool:
    """Notify a report owner of a relay message without exposing either address."""
    repo = UserRepository(session)
    prefs = await repo.get_prefs(contact.recipient_id)
    recipient = await repo.get_by_id(contact.recipient_id)
    if not recipient or not prefs or prefs.frequency == "off" or not prefs.email_enabled:
        return False
    requester = await repo.get_by_id(contact.requester_id)
    if not requester:
        return False

    subject = "Someone wants to contact you about your K9-Overwatch report"
    body = (
        f"Hi {recipient.display_name or 'there'},\n\n"
        f"{requester.display_name or 'Another K9-Overwatch user'} sent a private message about "
        f"{pet.name or 'your pet'}:\n\n{contact.message}\n\n"
        f"Reply securely here: {os.getenv('APP_BASE_URL', '')}/account\n"
    )
    # Durable: enqueue rather than send inline so a transient provider
    # failure doesn't drop the contact handoff alert.
    enqueued = await PetRepository(session).enqueue_notification(
        user_id=recipient.id,
        subject=subject,
        body=body,
        kind="contact",
        dedupe_key=f"contact:{contact.id}",
    )
    return enqueued is not None
