# SmartPetTec — Handoff Document

## Stack
- **Backend:** Python + Flask (app.py is the entry point — do not rename)
- **Database:** Supabase PostgreSQL + Supabase Auth
- **Frontend:** HTML/CSS/Jinja templates + vanilla JavaScript (`static/app.js`)
- **IoT:** MQTT via EMQX Public Broker (`broker.emqx.io:1883`, no TLS, no auth)
- **Notifications:** Telegram Bot API
- **Build:** PyInstaller `6.20.0` (Windows executable)

---

## Critical Rules (from CLAUDE.md)
- **Do NOT** change the Supabase schema — no new tables, no renamed columns.
- **Do NOT** migrate Flask to FastAPI.
- **Do NOT** use React, Node.js, npm, Tailwind, or Docker.
- **Do NOT** use `pyinstaller==6.6.0` — keep `pyinstaller==6.20.0`.
- Keep the current Flask + Supabase + Jinja + vanilla JS architecture.
- Keep the current auth/session flow.

---

## MQTT Config
```
MQTT_HOST=broker.emqx.io
MQTT_PORT=1883
MQTT_USERNAME=
MQTT_PASSWORD=
MQTT_TLS=false
MQTT_CLIENT_ID=smartpethome-backend
```

---

## ESP32 — FEEDER-001 (Automatic Feeder)

**Hardware:**
| Pin | Role |
|-----|------|
| GPIO 27 | Servo signal |
| GPIO 34 | Potentiometer (food sensor) |
| GPIO 25 | Red LED (low food) |
| GPIO 26 | Green LED (normal) |

**Threshold:** `umbralPeso = 1800` raw ADC  
**Servo:** open = 90°, closed = 0°

**Key fix applied:** `mqttClient.setBufferSize(512)` — the default 256-byte buffer silently dropped the ~286-byte telemetry payload. Without this line the ESP32 appears to publish (Serial says it did) but Flask never receives telemetry.

**Sketch location:** `esp32/feeder_001/feeder_001.ino`

**Required Arduino libraries:** `WiFi`, `PubSubClient`, `ESP32Servo`, `ArduinoJson`

---

## Working Features (as of this handoff)

| Feature | Status |
|---------|--------|
| ESP32 connects to WiFi + EMQX | ✅ |
| Telemetry published every 1 s | ✅ |
| Status heartbeat every 10 s | ✅ |
| Device goes online in dashboard | ✅ |
| `dispense_food` command → servo opens 2 s | ✅ |
| ACK returns and shows ✅ in app | ✅ |
| `low_food_detected` feeding event on state change | ✅ |
| `food_level_ok` feeding event on recovery | ✅ |
| `manual_dispense` event on ACK of dispense_food | ✅ |
| Dashboard shows only meaningful feeding events | ✅ |
| `low_food` + `pet_underfed` alerts (deduplicated) | ✅ |
| Alerts page live-refresh on Resolve (no page reload) | ✅ |
| Console logging — clean demo output | ✅ |
| Startup banner shows `http://127.0.0.1:5000` | ✅ |

---

## Key Architecture Notes

### Feeding Events (state-transition only)
`telemetry_handlers.py` uses an **in-memory dict** `_feeder_last_state` to track the previous food state per device. A `feeding_events` row is only inserted on transitions:

```
None → low   →  low_food_detected
ok   → low   →  low_food_detected
low  → ok    →  food_level_ok
ok   → ok    →  (no insert)
low  → low   →  (no insert)
```

Manual dispenses are recorded via `dispatch_ack()` when the `dispense_food` ACK arrives.  
**Caveat:** `_feeder_last_state` resets to empty on Flask restart. The first telemetry packet re-initialises it; if the device is low at restart a new `low_food_detected` event is inserted (correct behaviour).

### Command → ACK → manual_dispense correlation
`mqtt_client.pending_commands` (in-memory dict) stores `command_id → {command, serial_number, params}` when a command is published (in `api.py send_command()`). When the ACK arrives, `dispatch_ack()` reads `pending_commands` to know which command was acknowledged.

### Dashboard Resilience
`/api/dashboard/summary` wraps each Supabase query in its own `try/except` so a failure in one section (e.g. no feeding events table access) returns `[]`/`0` for that section without returning a 400 that blocks the whole page.

---

## Known Issues / Limitations

1. **In-memory state is not persistent.** `_feeder_last_state` and `pending_commands` live in Flask process memory. A restart clears them. For a prototype this is fine; for production, persist last state in `devices.metadata` (JSONB column already exists).

2. **EMQX public broker is shared.** Any device with the same topic prefix can publish/subscribe. This is intentional for the university prototype — do not send sensitive data.

3. **Single feeder tested.** Only `FEEDER-001` / `automatic_feeder` has a physical ESP32. All other device types have handlers but no hardware.

4. **`LOG_LEVEL=DEBUG`** is needed to see raw telemetry in the console. By default (INFO) normal per-second logs are suppressed. Set `LOG_LEVEL=DEBUG` in `.env` to re-enable for debugging.

5. **`pending_commands` is never pruned if ACK never arrives.** Low risk for a prototype — the dict stays small. For production, add a TTL cleanup.

---

## Environment Setup

```bash
# Copy and fill in credentials
copy .env.example .env

# Run
python app.py

# Console shows:
# ============================================
#   SmartPetTec — running
#   Local:  http://127.0.0.1:5000
#   MQTT:   broker.emqx.io:1883
# ============================================
```

**`.env` required keys:**
```
SUPABASE_URL=
SUPABASE_KEY=
SUPABASE_SERVICE_KEY=   # needed for MQTT telemetry inserts (bypasses RLS)
FLASK_SECRET_KEY=
MQTT_HOST=broker.emqx.io
MQTT_PORT=1883
MQTT_TLS=false
MQTT_CLIENT_ID=smartpethome-backend
TELEGRAM_BOT_TOKEN=     # optional
LOG_LEVEL=INFO          # set to DEBUG for verbose output
```

> **Important:** `SUPABASE_SERVICE_KEY` must be set. Without it, telemetry inserts via MQTT fail silently because there is no user session in the background thread.

---

## Next Tasks (suggested priority)

1. **Persist feeder last state** — store in `devices.metadata` JSONB so Flask restarts don't create spurious `low_food_detected` events.
2. **Second physical device** — add a `water_dispenser` or `environmental_monitor` ESP32 sketch following the same pattern as `feeder_001.ino`.
3. **History page** — filter/export feeding events by date range for demo.
4. **PyInstaller build** — run `pyinstaller app.spec` (or create spec) to produce the Windows `.exe` for demo distribution.
5. **Alert auto-resolve** — when `food_level_ok` event is recorded, automatically resolve any open `low_food` alert for that device.
