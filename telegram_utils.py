"""
telegram_utils.py
-----------------
Telegram alert delivery using the Bot API.

PHONE NUMBER vs CHAT ID — HOW THIS WORKS:
==========================================
Telegram's Bot API requires a numeric chat_id to send messages.
The SmartPetHome UI collects a PHONE NUMBER from the user (stored
in profiles.telegram_chat_id as TEXT).

The profiles.telegram_chat_id column can hold:
  A) JSON string:  {"phone": "+50688881234", "chat_id": "123456789"}
     → Production mode. chat_id was linked via the bot /link command.
     → Alerts are delivered immediately.

  B) Plain numeric string: "123456789"
     → Legacy or manually configured chat_id.
     → Alerts are delivered immediately.

  C) Phone number string: "+50688881234"
     → Phone entered but not yet linked to Telegram.
     → Alert is inserted in DB but Telegram delivery is SKIPPED.
     → A warning is logged.

PRODUCTION LINKING FLOW (to be implemented in a future sprint):
  1. User opens the SmartPetHome Telegram bot (@YourBotName).
  2. They send:  /link +50688881234
  3. The bot calls a webhook or polls for updates.
  4. The backend finds the profile with that phone number.
  5. Updates telegram_chat_id to: {"phone": "+506...", "chat_id": "987654321"}
  6. Future alerts reach the user automatically.

IMPLEMENTATION:
  Call send_telegram_alert(owner_id, title, message, severity) from
  telemetry_handlers or any other server-side code that generates alerts.
"""

import json
import logging
import requests
from config import TELEGRAM_BOT_TOKEN, supabase_admin

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _resolve_chat_id(telegram_chat_id_field: str) -> str | None:
    """
    Given the raw value stored in profiles.telegram_chat_id, return
    a usable numeric chat_id string, or None if not available.
    """
    if not telegram_chat_id_field:
        return None

    value = telegram_chat_id_field.strip()

    # Try to parse as JSON (production format with phone + chat_id)
    if value.startswith("{"):
        try:
            data = json.loads(value)
            chat_id = data.get("chat_id", "")
            if chat_id and str(chat_id).lstrip("-").isdigit():
                return str(chat_id)
            logger.warning(
                "Telegram JSON found but no valid chat_id. "
                "Phone number stored but bot linking not complete: %s",
                data.get("phone", "unknown")
            )
            return None
        except json.JSONDecodeError:
            pass

    # Check if it's already a plain numeric chat_id (old-style or manual entry)
    if value.lstrip("-").isdigit():
        return value

    # It looks like a phone number — not yet linked
    logger.warning(
        "Telegram alert SKIPPED: phone number '%s' is stored but "
        "has not been linked to a Telegram chat_id. "
        "User must start a conversation with the bot and run /link.",
        value
    )
    return None


def send_telegram_alert(owner_id: str, title: str, message: str, severity: str = "warning") -> bool:
    """
    Send a Telegram alert message to the owner.
    Returns True if sent, False otherwise.
    """
    if not TELEGRAM_BOT_TOKEN:
        logger.debug("TELEGRAM_BOT_TOKEN not set — Telegram alerts disabled.")
        return False

    try:
        # Load the owner's profile to get their telegram_chat_id
        res = (
            supabase_admin.table("profiles")
            .select("telegram_chat_id, display_name")
            .eq("id", owner_id)
            .single()
            .execute()
        )
        profile = res.data
    except Exception as e:
        logger.error("Could not load profile for Telegram alert: %s", e)
        return False

    if not profile or not profile.get("telegram_chat_id"):
        logger.debug("No telegram_chat_id set for owner %s", owner_id)
        return False

    chat_id = _resolve_chat_id(profile["telegram_chat_id"])
    if not chat_id:
        return False  # Already logged in _resolve_chat_id

    # Format the message as plain text (no parse_mode to avoid entity errors)
    severity_emoji = {"info": "i", "warning": "!", "critical": "!!"}.get(severity, "!")
    text = (
        f"[{severity_emoji}] SmartPetHome Alert\n\n"
        f"{title}\n"
        f"{message}\n\n"
        f"Severity: {severity.upper()}"
    )

    try:
        resp = requests.post(
            TELEGRAM_API.format(token=TELEGRAM_BOT_TOKEN),
            json={
                "chat_id": chat_id,
                "text":    text,
            },
            timeout=10,
        )
        if resp.ok:
            logger.info("Telegram alert sent to chat_id %s: %s", chat_id, title)
            return True
        else:
            logger.warning("Telegram API error %s: %s", resp.status_code, resp.text)
            return False
    except requests.RequestException as e:
        logger.error("Telegram request failed: %s", e)
        return False
