============================================================
  SmartPetHome - Windows Release
  IoT Pet Care Platform
============================================================

QUICK START
-----------
1. Make sure .env is present in this folder.
   If it is missing, copy .env.example to .env and fill in:

     SUPABASE_URL=
     SUPABASE_KEY=
     SUPABASE_SERVICE_KEY=
     FLASK_SECRET_KEY=
     MQTT_HOST=broker.emqx.io
     MQTT_PORT=1883
     MQTT_TLS=false
     MQTT_CLIENT_ID=smartpethome-backend
     TELEGRAM_BOT_TOKEN=    (optional - for Telegram alerts)
     LOG_LEVEL=INFO

2. Double-click SmartPetHome.exe

3. A console window opens showing the startup sequence:

     SmartPetHome - starting...
     [INFO] Launching SmartPetHome...
     [INFO] Loaded .env from <path>
     [INFO] Importing application modules...
     [INFO] Application modules loaded OK.
     [INFO] Starting MQTT...
     [INFO] Starting Telegram bot...
     [INFO] Starting scheduler...
     SmartPetHome - running
     Local : http://127.0.0.1:5000

4. Your browser opens automatically at http://127.0.0.1:5000
   If it does not open, navigate there manually.

5. Keep the console window open while using the app.
   Closing it stops SmartPetHome.

6. To stop: close the console, or click "End App" on the login page.


IMPORTANT NOTES
---------------
- This is a fully bundled executable.
  Python does NOT need to be installed on the target machine.

- The .env file must be in the same folder as SmartPetHome.exe.
  The app will warn you if it is missing or incomplete.

- The app runs locally only (127.0.0.1).
  It is not exposed to the internet or your local network.

- MQTT uses the EMQX public broker (broker.emqx.io).
  Internet access is required for ESP32 device communication.


TELEGRAM ALERTS (optional)
---------------------------
1. Open @smartpettec_alerts_bot on Telegram.
2. Send /start -- the bot replies with your Chat ID.
3. In the app: menu -> Telegram -> paste Chat ID -> Save.


IF SOMETHING GOES WRONG
------------------------
- Read the console window -- it shows the full error.
- A crash.log file is created in this folder if the app crashes
  on startup. Share it when reporting issues.

Common issues:
  * Missing or incomplete .env file
  * Wrong SUPABASE_URL / SUPABASE_KEY
  * Port 5000 already in use (close other apps using that port)
  * No internet connection (Supabase and MQTT require internet)


FILE STRUCTURE
--------------
  SmartPetHome.exe      <- Launch this
  _internal\            <- Bundled Python runtime (do not delete)
  .env.example          <- Template -- copy to .env and fill in
  .env                  <- YOUR credentials (never share this file)
  requirements.txt      <- Reference only (not needed by the EXE)
  README_RUN.txt        <- This file
  crash.log             <- Created only if the app crashes on startup


RUNNING FROM SOURCE (developers)
---------------------------------
1. Python 3.11+ must be on PATH.
2. Copy .env.example to .env and fill in credentials.
3. Double-click run_app.bat
   - Creates .venv on first run
   - Installs requirements.txt
   - Opens browser at http://127.0.0.1:5000


============================================================
  SmartPetHome - Keeping Pets Happy
============================================================
