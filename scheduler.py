"""
scheduler.py
------------
Backend local-time listener for scheduled device actions.

Uses ONLY datetime.now() — the computer's local clock.
Never uses Supabase timestamps, UTC, or database server time.

Startup: called from launcher.py and app.py.
Thread guard: checks threading.enumerate() so it is safe to call
start_scheduler() from multiple entry points without creating duplicates.

Deduplication order (critical):
  1. Check if already ran today (DB date or in-memory set)
  2. Publish MQTT command
  3. Only if MQTT publish returns True:
     - mark as executed (update DB / in-memory set)
     - create scheduled_action alert
     - send Telegram
  If MQTT fails → do NOT mark executed → will retry next check cycle.
"""

import logging
import threading
import time
from datetime import datetime, date, time as dt_time

from config import supabase_admin

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 10  # seconds — check every 10 s so a scheduled minute is never missed

# ── Status tracking (readable by routes) ─────────────────────
_status = {
    "running":    False,
    "last_check": None,   # ISO string of last check time
}
_status_lock = threading.Lock()

# ── In-memory dedup for feeder and door (secondary guard) ────
# Key: "{sched_id}:{YYYY-MM-DD}" for feeder
#      "{door_sched_id}:{action}:{YYYY-MM-DD}" for door
_fired: set[str] = set()
_fired_lock = threading.Lock()


def get_status() -> dict:
    """Return a snapshot of scheduler status for display in templates/API."""
    with _status_lock:
        alive = any(t.name == "sph-scheduler" for t in threading.enumerate())
        return {
            "running":    alive,
            "last_check": _status["last_check"],
        }


# ── Time-field normalizers ────────────────────────────────────

def _to_hhmm(val) -> str:
    """Normalize any Supabase time value to 'HH:MM' string."""
    if val is None:
        return ""
    if isinstance(val, dt_time):
        return val.strftime("%H:%M")
    if isinstance(val, datetime):
        return val.strftime("%H:%M")
    return str(val).strip()[:5]   # "HH:MM:SS" → "HH:MM"


def _to_date_str(val) -> str:
    """Normalize any Supabase date value to 'YYYY-MM-DD' string."""
    if val is None:
        return ""
    if isinstance(val, (date, datetime)):
        return val.isoformat()[:10]
    return str(val).strip()[:10]


# ── Alert helper ──────────────────────────────────────────────

def _create_alert(device_id: str, owner_id: str,
                  alert_type: str, severity: str,
                  title: str, message: str) -> None:
    """Insert alert row then send Telegram. Called only after MQTT succeeds."""
    try:
        supabase_admin.table("alerts").insert({
            "device_id":     device_id,
            "owner_id":      owner_id,
            "alert_type":    alert_type,
            "severity":      severity,
            "title":         title,
            "message":       message,
            "is_read":       False,
            "telegram_sent": False,
        }).execute()
        logger.info("[SCHEDULER] scheduled_action alert created: %s", title)
    except Exception as e:
        logger.error("[SCHEDULER] Alert insert failed: %s", e)
        return

    from telegram_utils import send_telegram_alert
    sent = send_telegram_alert(owner_id, title, message, severity)
    if sent:
        logger.info("[SCHEDULER] Telegram sent for: %s", title)
        try:
            supabase_admin.table("alerts") \
                .update({"telegram_sent": True}) \
                .eq("device_id",  device_id) \
                .eq("alert_type", alert_type) \
                .is_("resolved_at", "null") \
                .execute()
        except Exception:
            pass
    else:
        logger.info("[SCHEDULER] Telegram not sent (not configured or error)")


# ── Shared MQTT publish wrapper ───────────────────────────────

def _publish(serial: str, command: str, params: dict | None = None) -> bool:
    """
    Publish command to device. Returns True on success.
    Uses the same commands.publish_command path as the manual button.
    """
    import mqtt_client
    import commands as cmd_module

    client = mqtt_client.get_client()
    if not mqtt_client.is_connected() or not client:
        logger.error("[SCHEDULER] MQTT not connected — cannot send %s to %s", command, serial)
        return False

    topic = f"smartpethome/devices/{serial}/command"
    try:
        command_id = cmd_module.publish_command(client, serial, command, params or {})
        logger.info("[SCHEDULER] Publishing MQTT topic=%s payload={command:%s} result=true",
                    topic, command)
        return command_id  # truthy string
    except Exception as e:
        logger.error("[SCHEDULER] MQTT publish error for %s %s: %s", serial, command, e)
        return False


# ── Public execute functions (also called by test buttons) ────

def execute_door_action(device_id: str, serial: str, owner_id: str,
                         action: str) -> bool:
    """
    Publish open_door or close_door. Create alert only on success.
    Called by scheduler loop AND by test button routes.
    Returns True if MQTT published successfully.
    """
    logger.info("[SCHEDULER] Executing door action: %s → %s", action, serial)
    result = _publish(serial, action, {})
    if not result:
        logger.error("[SCHEDULER] MQTT publish result=false for %s %s", serial, action)
        return False

    logger.info("[SCHEDULER] MQTT publish result=true for %s %s", serial, action)
    human  = "opened" if action == "open_door" else "closed"
    title  = f"Scheduled Door {'Opened' if action == 'open_door' else 'Closed'}"
    msg    = f"Scheduled action executed: {serial} {human}."
    _create_alert(device_id, owner_id, "scheduled_action", "info", title, msg)
    return True


def execute_feeder(device_id: str, serial: str, owner_id: str,
                    grams: float) -> bool:
    """
    Publish dispense_food with grams. Create alert only on success.
    Called by scheduler loop AND by test button routes.
    Returns True if MQTT published successfully.
    """
    import mqtt_client
    import commands as cmd_module

    logger.info("[SCHEDULER] Executing feeder: dispense_food %s grams=%.0f", serial, grams)
    client = mqtt_client.get_client()
    if not mqtt_client.is_connected() or not client:
        logger.error("[SCHEDULER] MQTT not connected — dispense_food skipped for %s", serial)
        return False

    topic = f"smartpethome/devices/{serial}/command"
    try:
        command_id = cmd_module.publish_command(
            client, serial, "dispense_food", {"grams": grams}
        )
        # Register in pending_commands so dispatch_ack records manual_dispense event
        mqtt_client.pending_commands[command_id] = {
            "command":       "dispense_food",
            "serial_number": serial,
            "params":        {"grams": grams},
        }
        logger.info("[SCHEDULER] MQTT publish result=true: dispense_food %s grams=%.0f",
                    serial, grams)
    except Exception as e:
        logger.error("[SCHEDULER] MQTT publish result=false for dispense_food %s: %s", serial, e)
        return False

    _create_alert(device_id, owner_id, "scheduled_action", "info",
                  "Scheduled Feeding",
                  f"Scheduled feeding executed: {serial} dispensed {grams:.0f} g.")
    return True


# ── Door schedule checker ─────────────────────────────────────

def _check_door_schedules(current_hhmm: str, current_date: date) -> None:
    today_str = current_date.isoformat()

    try:
        res = (
            supabase_admin.table("door_schedules")
            .select("id, open_time, close_time, enabled, "
                    "last_open_run_date, last_close_run_date, "
                    "devices(id, serial_number, device_name, owner_id)")
            .eq("enabled", True)
            .execute()
        )
        schedules = res.data or []
    except Exception as e:
        logger.warning("[SCHEDULER] door_schedules query failed: %s", e)
        return

    logger.info("[SCHEDULER] Loaded %d door schedule(s)", len(schedules))

    for s in schedules:
        device = s.get("devices") or {}
        if not device:
            continue

        sched_id  = s["id"]
        device_id = device["id"]
        serial    = device.get("serial_number", "?")
        owner_id  = device["owner_id"]
        open_hhmm  = _to_hhmm(s.get("open_time"))
        close_hhmm = _to_hhmm(s.get("close_time"))

        logger.info("[SCHEDULER] Checking %s open=%s close=%s now=%s enabled=true",
                    serial, open_hhmm or "—", close_hhmm or "—", current_hhmm)

        slots = [
            ("open_door",  open_hhmm,  "last_open_run_date"),
            ("close_door", close_hhmm, "last_close_run_date"),
        ]
        for action, sched_time, run_col in slots:
            if not sched_time or sched_time != current_hhmm:
                continue

            # Primary dedup: DB column
            last_run = _to_date_str(s.get(run_col))
            if last_run == today_str:
                logger.info("[SCHEDULER] Duplicate scheduled execution skipped: %s %s (DB)",
                            serial, action)
                continue

            # Secondary dedup: in-memory (handles DB update failures)
            mem_key = f"{sched_id}:{action}:{today_str}"
            with _fired_lock:
                if mem_key in _fired:
                    logger.info("[SCHEDULER] Duplicate scheduled execution skipped: %s %s (mem)",
                                serial, action)
                    continue

            logger.info("[SCHEDULER] %s due for %s",
                        "Door OPEN" if action == "open_door" else "Door CLOSE", serial)

            success = execute_door_action(device_id, serial, owner_id, action)
            if success:
                # Mark only after MQTT succeeds
                with _fired_lock:
                    _fired.add(mem_key)
                try:
                    supabase_admin.table("door_schedules") \
                        .update({run_col: today_str}) \
                        .eq("id", sched_id) \
                        .execute()
                except Exception as e:
                    logger.error("[SCHEDULER] Could not update %s: %s", run_col, e)
            else:
                logger.warning("[SCHEDULER] MQTT failed — will retry next check for %s %s",
                               serial, action)


# ── Feeder schedule checker ───────────────────────────────────

def _check_feeder_schedules(current_hhmm: str, current_date: date) -> None:
    today_str = current_date.isoformat()

    try:
        cfg_res = (
            supabase_admin.table("feeder_configurations")
            .select("id, device_id, devices(id, serial_number, device_name, owner_id)")
            .execute()
        )
        config_map = {c["id"]: c for c in (cfg_res.data or [])}
    except Exception as e:
        logger.error("[SCHEDULER] Feeder config query failed: %s", e)
        return

    try:
        sched_res = (
            supabase_admin.table("feeding_schedules")
            .select("id, feeder_config_id, feeding_time, target_grams")
            .eq("enabled", True)
            .execute()
        )
        schedules = sched_res.data or []
    except Exception as e:
        logger.error("[SCHEDULER] feeding_schedules query failed: %s", e)
        return

    logger.info("[SCHEDULER] Loaded %d feeder schedule(s)", len(schedules))

    for s in schedules:
        cfg    = config_map.get(s.get("feeder_config_id") or "") or {}
        device = cfg.get("devices") or {}
        if not device:
            continue

        sched_id   = s["id"]
        device_id  = device["id"]
        serial     = device.get("serial_number", "?")
        owner_id   = device["owner_id"]
        sched_time = _to_hhmm(s.get("feeding_time"))
        grams      = float(s.get("target_grams") or 0)

        logger.info("[SCHEDULER] Checking feeder %s time=%s grams=%.0f now=%s enabled=true",
                    serial, sched_time, grams, current_hhmm)

        if sched_time != current_hhmm:
            continue

        mem_key = f"{sched_id}:{today_str}"
        with _fired_lock:
            if mem_key in _fired:
                logger.info("[SCHEDULER] Duplicate scheduled execution skipped: feeder %s %s",
                            serial, sched_time)
                continue

        logger.info("[SCHEDULER] Feeder due for %s grams=%.0f", serial, grams)

        success = execute_feeder(device_id, serial, owner_id, grams)
        if success:
            with _fired_lock:
                _fired.add(mem_key)
        else:
            logger.warning("[SCHEDULER] Feeder MQTT failed — will retry next check for %s", serial)


# ── Main loop ─────────────────────────────────────────────────

def _loop() -> None:
    print("[SCHEDULER] Local-time listener started", flush=True)
    logger.info("[SCHEDULER] Local-time listener started (interval=%ds)", CHECK_INTERVAL)

    with _status_lock:
        _status["running"] = True

    while True:
        try:
            now          = datetime.now()      # LOCAL computer clock — never UTC
            current_date = now.date()
            current_hhmm = now.strftime("%H:%M")
            ts           = now.strftime("%Y-%m-%d %H:%M:%S")

            with _status_lock:
                _status["last_check"] = ts

            logger.info("[SCHEDULER] Local time: %s", ts)
            logger.info("[SCHEDULER] Thread alive=true")

            _check_feeder_schedules(current_hhmm, current_date)
            _check_door_schedules(current_hhmm, current_date)

        except Exception as e:
            logger.error("[SCHEDULER] Loop error: %s", e, exc_info=True)

        time.sleep(CHECK_INTERVAL)


# ── Startup ───────────────────────────────────────────────────

def start_scheduler() -> None:
    """
    Start the background scheduler thread.
    Safe to call multiple times — uses threading.enumerate() to detect
    if a thread named 'sph-scheduler' already exists in this process.
    """
    for t in threading.enumerate():
        if t.name == "sph-scheduler":
            logger.info("[SCHEDULER] Thread already running in this process — skip duplicate start")
            return

    t = threading.Thread(target=_loop, daemon=True, name="sph-scheduler")
    t.start()
    logger.info("[SCHEDULER] Thread started. Using local computer time (datetime.now()).")
