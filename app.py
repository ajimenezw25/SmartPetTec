"""
app.py
------
Flask application entry point.
Starts MQTT background thread when Flask launches.
"""

import sys
import os
import logging

# ── Logging setup ─────────────────────────────────────────────
# Set LOG_LEVEL=DEBUG in .env (or environment) to enable verbose output.
# Default is INFO — clean console suitable for demos.
_log_level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)

logging.basicConfig(
    level=_log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Silence noisy third-party libraries regardless of LOG_LEVEL
# (set to WARNING so their errors/warnings still surface)
logging.getLogger("werkzeug").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("hpack").setLevel(logging.WARNING)

# PyInstaller frozen path fix
if getattr(sys, "frozen", False):
    _base_dir = getattr(
        sys,
        "_MEIPASS",
        os.path.dirname(os.path.abspath(__file__))
    )
else:
    _base_dir = os.path.dirname(os.path.abspath(__file__))

from flask import Flask, request, abort
from config import FLASK_SECRET_KEY

from auth import auth_bp
from dashboard import dashboard_bp
from pets import pets_bp
from devices import devices_bp
from feeder import feeder_bp
from alerts import alerts_bp
from history import history_bp
import importlib

profile_bp = getattr(importlib.import_module("profile"), "profile_bp")
from locations import locations_bp
from api import api_bp
from telemetry import telemetry_bp


app = Flask(
    __name__,
    template_folder=os.path.join(_base_dir, "templates"),
    static_folder=os.path.join(_base_dir, "static"),
)

app.secret_key = FLASK_SECRET_KEY

app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(pets_bp)
app.register_blueprint(devices_bp)
app.register_blueprint(feeder_bp)
app.register_blueprint(alerts_bp)
app.register_blueprint(history_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(locations_bp)
app.register_blueprint(api_bp)
app.register_blueprint(telemetry_bp)


@app.route("/end-app", methods=["POST"])
def end_app():
    """Local-only shutdown. Only accepts requests from localhost."""
    if request.remote_addr not in ("127.0.0.1", "::1"):
        abort(403)

    import threading, time

    def _exit():
        time.sleep(1)
        os._exit(0)

    threading.Thread(target=_exit, daemon=True).start()

    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>SmartPetHome</title></head>"
        "<body style='font-family:sans-serif;display:flex;align-items:center;"
        "justify-content:center;height:100vh;margin:0;background:#f7f6f3;'>"
        "<div style='text-align:center'>"
        "<p style='font-size:2rem'>🐾</p>"
        "<h2>SmartPetHome is closing.</h2>"
        "<p style='color:#6b6560'>You can close this tab.</p>"
        "</div></body></html>"
    )


@app.template_filter("datefmt")
def datefmt(value, fmt="%Y-%m-%d %H:%M"):
    if not value:
        return "—"

    try:
        from datetime import datetime
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.strftime(fmt)
    except Exception:
        return str(value)


def _start_mqtt():
    """Start MQTT only once when Flask launches."""
    import mqtt_client
    mqtt_client.start_mqtt()


def _start_telegram_bot():
    """Start Telegram bot polling only once when Flask launches."""
    import telegram_bot
    telegram_bot.start_bot()


if __name__ == "__main__":
    is_frozen   = getattr(sys, "frozen", False)
    is_reloader = os.environ.get("WERKZEUG_RUN_MAIN") == "true"

    if is_frozen or is_reloader:
        _start_mqtt()
        _start_telegram_bot()

        # Open browser once, unless launcher.py is already handling it.
        # launcher.py sets this env var so we don't open a duplicate tab.
        if not os.environ.get("SMARTPETHOME_LAUNCHER"):
            import threading, webbrowser, time
            def _open():
                time.sleep(1.5)
                webbrowser.open("http://127.0.0.1:5000")
            threading.Thread(target=_open, daemon=True).start()

    # Print startup banner manually.
    # Werkzeug is silenced to WARNING so its own "Running on …" line is
    # suppressed (along with per-request spam). We replace it here.
    # Only print in the reloader subprocess (or frozen build) to avoid
    # double-printing when Werkzeug forks a child process.
    if is_frozen or is_reloader:
        from config import MQTT_HOST, MQTT_PORT
        port = 5000
        print()
        print("=" * 44)
        print("  SmartPetTec — running")
        print(f"  Local:  http://127.0.0.1:{port}")
        print(f"  MQTT:   {MQTT_HOST}:{MQTT_PORT}")
        print("=" * 44)
        print()

    app.run(
        debug=not is_frozen,
        port=5000,
        use_reloader=not is_frozen
    )