"""
telegram_bot.py
---------------
Telegram bot polling loop — runs in a background thread when Flask starts.

Behaviour:
  /start  → reply with a welcome message and the user's Telegram Chat ID.
  anything else → remind the user to send /start.

Token is read from TELEGRAM_BOT_TOKEN in .env via config.py.
If the token is empty the thread exits immediately with one warning.
"""

import time
import logging
import threading
import requests

from config import TELEGRAM_BOT_TOKEN

logger = logging.getLogger(__name__)

_BASE = "https://api.telegram.org/bot{token}/{method}"


def _api(method: str, **kwargs) -> dict | None:
    url = _BASE.format(token=TELEGRAM_BOT_TOKEN, method=method)
    try:
        resp = requests.post(url, json=kwargs, timeout=35)
        return resp.json()
    except requests.RequestException as e:
        logger.error("Telegram send error: %s", e)
        return None


def _send(chat_id: int | str, text: str) -> None:
    result = _api("sendMessage", chat_id=chat_id, text=text)
    if result and not result.get("ok"):
        logger.error("Telegram send error: %s", result.get("description"))


def _poll_loop() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set — Telegram bot polling disabled.")
        return

    logger.info("Telegram bot polling started")
    offset = 0

    while True:
        data = _api("getUpdates", offset=offset, timeout=30)
        if not data or not data.get("ok"):
            time.sleep(5)
            continue

        for update in data.get("result", []):
            offset = update["update_id"] + 1

            msg = update.get("message") or update.get("edited_message")
            if not msg:
                continue

            chat_id = msg["chat"]["id"]
            text = (msg.get("text") or "").strip()

            if text == "/start" or text.startswith("/start@"):
                logger.info("/start received from chat_id %s", chat_id)
                _send(
                    chat_id,
                    f"Bienvenido a SmartPetTec \U0001f43e\n"
                    f"Tu Telegram Chat ID es: {chat_id}\n"
                    "Copia este número en tu perfil de SmartPetTec para recibir alertas.",
                )
            else:
                _send(chat_id, "Escribe /start para obtener tu Telegram Chat ID.")


def start_bot() -> None:
    """Start the Telegram polling loop in a daemon thread."""
    t = threading.Thread(target=_poll_loop, name="telegram-bot", daemon=True)
    t.start()
