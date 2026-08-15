"""Lightweight alerting helpers — fires webhook notifications on critical events."""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

import aiohttp

logger = logging.getLogger(__name__)


async def send_scraper_alert(
    source: str,
    consecutive_errors: int,
    error_message: str,
) -> None:
    """
    POST a notification to ALERT_WEBHOOK_URL (Discord/Slack/generic) when a
    scraper has failed multiple times in a row.

    Supports:
    - Discord: webhook URL ending in /slack or standard discord.com/api/webhooks/...
    - Slack:   incoming webhook URL (hooks.slack.com)
    - Generic: any endpoint that accepts a JSON POST with {"text": "..."}

    Set ALERT_WEBHOOK_URL in the environment to enable. If unset, logs critically
    but does not raise.
    """
    url = os.getenv("ALERT_WEBHOOK_URL", "").strip()
    if not url:
        logger.critical(
            f"[{source}] Scraper has failed {consecutive_errors} times in a row. "
            f"Set ALERT_WEBHOOK_URL to receive webhook alerts. Error: {error_message}"
        )
        return

    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    text = (
        f":rotating_light: *K9-Overwatch scraper alert* — `{source}`\n"
        f"Failed *{consecutive_errors}* consecutive times as of {ts}.\n"
        f"Last error: `{error_message[:300]}`"
    )

    # Discord uses "content", Slack uses "text"; send both so either works.
    payload = {"text": text, "content": text}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status not in (200, 204):
                    body = await resp.text()
                    logger.warning(
                        f"Alert webhook returned {resp.status}: {body[:200]}"
                    )
                else:
                    logger.info(f"[{source}] Alert webhook sent (status {resp.status})")
    except Exception as exc:
        logger.warning(f"Failed to send alert webhook: {exc}")
