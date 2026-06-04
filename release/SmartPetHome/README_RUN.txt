============================================================
  SmartPetHome -- Quick Start Guide
============================================================

RUNNING THE EXECUTABLE
------------------------
1. Open the SmartPetHome folder.

2. Check that .env exists in the same folder as SmartPetHome.exe.
   If it is missing:
     - Copy .env.example to .env
     - Open .env and fill in your credentials (see below).

3. Double-click SmartPetHome.exe.
   The app starts Flask, connects to MQTT, and opens your
   browser at http://127.0.0.1:5000 automatically.

   If the browser does not open, navigate to:
     http://127.0.0.1:5000

4. To stop the app:
     - Use the "End App" button on the login page, or
     - Close the console window.


REQUIRED .env KEYS
-------------------
SUPABASE_URL=
SUPABASE_KEY=
SUPABASE_SERVICE_KEY=
FLASK_SECRET_KEY=
MQTT_HOST=broker.emqx.io
MQTT_PORT=1883
MQTT_TLS=false
MQTT_CLIENT_ID=smartpethome-backend
TELEGRAM_BOT_TOKEN=        (optional — for Telegram alerts)
LOG_LEVEL=INFO


RUNNING FROM SOURCE (developers)
----------------------------------
1. Make sure Python 3.11+ is on PATH.
2. Copy .env.example to .env and fill in credentials.
3. Double-click run_app.bat.
   - Creates .venv on first run.
   - Installs requirements.txt.
   - Opens browser at http://127.0.0.1:5000.


TELEGRAM ALERTS (optional)
----------------------------
1. Open @smartpettec_alerts_bot on Telegram.
2. Send /start -- the bot replies with your Chat ID.
3. Log in to SmartPetHome -> menu -> Telegram -> paste ID -> Save.


TROUBLESHOOTING
----------------
- "Cannot connect to Supabase"  -> check SUPABASE_URL / SUPABASE_KEY in .env
- "MQTT not connected" badge    -> broker.emqx.io may be temporarily unavailable
- Browser does not open         -> navigate to http://127.0.0.1:5000 manually
- App closes immediately        -> check crash.log in the SmartPetHome folder

============================================================
