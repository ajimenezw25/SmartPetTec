"""
launcher.py
-----------
Windows launcher for SmartPetHome.

* Fixes Windows console encoding so no garbled characters appear.
* Prints a clear startup sequence.
* Loads .env from the EXE directory (frozen) or script directory (source).
* In source/dev mode: installs requirements from requirements.txt first.
* Starts MQTT, Telegram bot, and scheduler.
* Opens the browser automatically.
* On ANY error: prints full traceback, writes crash.log, keeps window open.
"""

import sys
import os

# ── Fix Windows console encoding (must happen before any print) ──────────────
# Prevents garbled output like "GreatPetHome GreekCo starting..." on cp1252 consoles.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── Startup banner ────────────────────────────────────────────────────────────
print()
print("=" * 52)
print("  SmartPetHome - starting...")
print("=" * 52)
print()


# ── Crash reporter ────────────────────────────────────────────────────────────
import traceback

def _crash(exc=None):
    """Print traceback, write crash.log next to the exe, keep window open."""
    tb  = traceback.format_exc() if exc is not None else ""
    msg = (
        "\n" + "=" * 60 + "\n"
        "  SmartPetHome - STARTUP ERROR\n"
        + "=" * 60 + "\n"
        + (str(exc) + "\n\n" if exc else "")
        + tb
    )
    print(msg)

    log_dir = (
        os.path.dirname(sys.executable)
        if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(__file__))
    )
    log_path = os.path.join(log_dir, "crash.log")
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(msg)
        print(f"  Crash log written to: {log_path}")
    except Exception as log_err:
        print(f"  (Could not write crash.log: {log_err})")

    print()
    input("Press ENTER to close...")
    sys.exit(1)


try:
    import threading
    import webbrowser
    import time
    import subprocess

    # ── Locate project root ───────────────────────────────────────────────────
    if getattr(sys, "frozen", False):
        _root = os.path.dirname(sys.executable)
    else:
        _root = os.path.dirname(os.path.abspath(__file__))

    if _root not in sys.path:
        sys.path.insert(0, _root)

    # ── In source/dev mode: install requirements first ────────────────────────
    _is_frozen = getattr(sys, "frozen", False)

    if not _is_frozen:
        _req = os.path.join(_root, "requirements.txt")
        if os.path.exists(_req):
            print("[INFO] Installing requirements...")
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "-r", _req, "--quiet"],
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
            print("[INFO] Requirements OK.")
            print()
        else:
            print("[WARNING] requirements.txt not found - skipping install.")
            print()

    print("[INFO] Launching SmartPetHome...")
    print()

    # ── Load .env ─────────────────────────────────────────────────────────────
    _env_path = os.path.join(_root, ".env")
    if os.path.exists(_env_path):
        from dotenv import load_dotenv
        load_dotenv(_env_path, override=False)
        print(f"[INFO] Loaded .env from {_env_path}")
    else:
        print(f"[WARNING] .env not found at {_env_path}")
        print("          Copy .env.example to .env and fill in your credentials.")
        print()

    # ── Logging setup ─────────────────────────────────────────────────────────
    import logging

    _log_level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(
        level=_log_level,
        format="  [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("hpack").setLevel(logging.WARNING)

    # Tell app.py not to open the browser - launcher handles it.
    os.environ["SMARTPETHOME_LAUNCHER"] = "1"

    # ── Import app modules ────────────────────────────────────────────────────
    print("[INFO] Importing application modules...")
    from config import FLASK_SECRET_KEY, MQTT_HOST, MQTT_PORT
    import app as _app_module
    flask_app = _app_module.app
    print("[INFO] Application modules loaded OK.")
    print()

    # ── Port ──────────────────────────────────────────────────────────────────
    _PORT        = int(os.environ.get("PORT", 5000))
    _URL         = f"http://127.0.0.1:{_PORT}"
    _is_reloader = os.environ.get("WERKZEUG_RUN_MAIN") == "true"

    # ── Start background services (once: frozen OR werkzeug child process) ────
    if _is_frozen or _is_reloader:

        print("[INFO] Starting MQTT...")
        import mqtt_client
        mqtt_client.start_mqtt()

        print("[INFO] Starting Telegram bot...")
        import telegram_bot
        telegram_bot.start_bot()

        print("[INFO] Starting scheduler...")
        import scheduler
        scheduler.start_scheduler()

        # Open browser after a short delay
        def _open_browser():
            time.sleep(2.0)
            webbrowser.open(_URL)
        threading.Thread(target=_open_browser, daemon=True).start()

        print()
        print("=" * 52)
        print("  SmartPetHome - running")
        print(f"  Local : {_URL}")
        print(f"  MQTT  : {MQTT_HOST}:{MQTT_PORT}")
        print("=" * 52)
        print()

    # ── Run Flask ─────────────────────────────────────────────────────────────
    flask_app.run(
        host="127.0.0.1",
        port=_PORT,
        debug=not _is_frozen,
        use_reloader=not _is_frozen,
    )

except KeyboardInterrupt:
    print("\n[INFO] Stopped by user.")
except Exception as exc:
    _crash(exc)
