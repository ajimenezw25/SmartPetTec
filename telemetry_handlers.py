"""
telemetry_handlers.py
---------------------
Processes incoming MQTT telemetry payloads from ESP devices.

For each device type:
  1. Parse the JSON payload.
  2. Look up the device by serial_number in Supabase (using admin client
     so this works without a user session / JWT).
  3. Insert the event row into the correct existing event table.
     Extra fields that don't have a column go into the JSONB metadata field.
  4. Check alert conditions.
  5. Insert alert into the existing alerts table if triggered.
  6. Send Telegram notification to the device owner.
  7. Update devices.last_seen_at and devices.status.

NO NEW TABLES ARE CREATED. Extra values use the metadata JSONB column.
"""

import logging
from datetime import datetime, timezone

from config import supabase_admin
from telegram_utils import send_telegram_alert

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_device(serial_number: str) -> dict | None:
    """Fetch device + device_type slug by serial_number."""
    try:
        res = (
            supabase_admin.table("devices")
            .select("*, device_types(slug, name)")
            .eq("serial_number", serial_number)
            .single()
            .execute()
        )
        return res.data
    except Exception as e:
        logger.error("Device lookup failed for serial '%s': %s", serial_number, e)
        return None


def _update_device_seen(device_id: str, status: str = "online") -> None:
    """Mark device as online and update last_seen_at."""
    try:
        supabase_admin.table("devices").update({
            "last_seen_at": _now_iso(),
            "status":       status,
        }).eq("id", device_id).execute()
    except Exception as e:
        logger.error("Could not update device status: %s", e)


def _has_open_alert(device_id: str, alert_type: str) -> bool:
    """
    Return True if there is already an unresolved alert of this type
    for this device. Used to prevent duplicate alert spam when telemetry
    arrives every second while the condition persists.
    """
    try:
        res = (
            supabase_admin.table("alerts")
            .select("id")
            .eq("device_id",  device_id)
            .eq("alert_type", alert_type)
            .is_("resolved_at", "null")
            .limit(1)
            .execute()
        )
        return bool(res.data)
    except Exception as e:
        logger.error("Could not check for open alert (device=%s type=%s): %s",
                     device_id, alert_type, e)
        return False          # on error, allow the insert so we don't lose alerts


def _insert_alert(device_id: str, owner_id: str, alert_type: str,
                  severity: str, title: str, message: str) -> None:
    """Insert an alert row and send Telegram notification."""
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
        logger.info("ALERT created — device=%s type=%s severity=%s",
                    device_id, alert_type, severity)
    except Exception as e:
        logger.error("ALERT insert FAILED — device=%s type=%s error=%s",
                     device_id, alert_type, e)
        return

    # Send Telegram (no-op if token not configured)
    sent = send_telegram_alert(owner_id, title, message, severity)
    if sent:
        try:
            supabase_admin.table("alerts").update({"telegram_sent": True}) \
                .eq("device_id", device_id) \
                .eq("alert_type", alert_type) \
                .is_("resolved_at", "null") \
                .execute()
        except Exception:
            pass


# ── Feeder state tracker ─────────────────────────────────────
# In-memory dict: device_id → "ok" | "low"
# Tracks the previous food state so feeding_events rows are only
# inserted on transitions, not on every 1-second telemetry packet.
# Resets to None on Flask restart (first packet re-initialises it).
_feeder_last_state: dict[str, str] = {}


# ── Per-device-type handlers ──────────────────────────────────

def handle_feeder(device: dict, data: dict) -> None:
    """
    automatic_feeder telemetry → feeding_events.

    A feeding_events row is inserted ONLY on meaningful state transitions:
      ok  → low   : event_type = "low_food_detected"
      low → ok    : event_type = "food_level_ok"
      None → low  : event_type = "low_food_detected"  (boot while low)
      None → ok   : no row inserted (normal startup, nothing to report)

    Manual dispenses are recorded separately by dispatch_ack() when the
    dispense_food ACK arrives with status "ok"/"success".
    """
    owner_id  = device["owner_id"]
    device_id = device["id"]

    low_food     = bool(data.get("low_food",     False))
    pet_underfed = bool(data.get("pet_underfed", False))
    status_color = data.get("status_color", "green")
    remaining    = data.get("food_remaining_grams")

    # Derive simple binary state from payload
    current_state = "low" if (low_food or status_color == "red") else "ok"
    prev_state    = _feeder_last_state.get(device_id)   # None on first packet

    # Always update the in-memory state
    _feeder_last_state[device_id] = current_state

    logger.debug("FEEDER state device=%s prev=%s current=%s",
                 device_id, prev_state, current_state)

    # ── Decide whether to insert a feeding_events row ──────────
    event_type: str | None = None

    if prev_state is None:
        # First packet since Flask started — only record if already low
        if current_state == "low":
            event_type = "low_food_detected"
        # If "ok" on first packet: no row (nothing happened yet)
    elif prev_state == "ok" and current_state == "low":
        event_type = "low_food_detected"
    elif prev_state == "low" and current_state == "ok":
        event_type = "food_level_ok"
    # else: same state as before — skip insert entirely

    if event_type:
        safe_color = "red" if current_state == "low" else "green"
        row = {
            "device_id":       device_id,
            "owner_id":        owner_id,
            "dispensed_grams": data.get("dispensed_grams"),
            "consumed_grams":  data.get("consumed_grams"),
            "leftover_grams":  data.get("leftover_grams"),
            "status_color":    safe_color,
            "metadata": {
                "event_type":           event_type,
                "food_remaining_grams": remaining,
                "bowl_weight_grams":    data.get("bowl_weight_grams"),
            },
        }
        logger.debug("FEEDER inserting feeding_events event_type=%s device=%s",
                     event_type, device_id)
        try:
            supabase_admin.table("feeding_events").insert(row).execute()
            logger.info("FEEDER event recorded: %s (device=%s)", event_type, device_id)
        except Exception as e:
            logger.error("FEEDER feeding_events insert FAILED: %s", e)

    # ── Alert logic — threshold-based, mutually exclusive ─────────
    # CRITICAL < 1800  — matches ESP32 umbralPeso (red LED on).
    # WARNING  1800–3000 — "almost low" zone above the ESP32 threshold.
    # > 3000            — no alert.
    _CRITICAL_THRESHOLD = 1800
    _WARNING_THRESHOLD  = 3000

    reading = data.get("food_remaining_grams") or data.get("bowl_weight_grams")

    try:
        reading_val = float(reading) if reading is not None else None
    except (TypeError, ValueError):
        reading_val = None

    if reading_val is None:
        pass  # no reading — skip silently
    elif reading_val < _CRITICAL_THRESHOLD:
        # ── Critical zone ──────────────────────────────────────

        if _has_open_alert(device_id, "pet_underfed"):
            logger.debug("FEEDER critical alert already open — skipping (reading=%.0f)", reading_val)
        else:
            logger.info("FEEDER alert: CRITICAL created (reading=%.0f)", reading_val)
            _insert_alert(
                device_id, owner_id,
                alert_type = "pet_underfed",
                severity   = "critical",
                title      = "🚨 Alimento Crítico — Recipiente Casi Vacío",
                message    = (
                    f"El nivel de alimento es crítico en '{device['device_name']}'. "
                    f"Lectura actual: {reading_val:.0f}. "
                    "Recarga el recipiente inmediatamente."
                ),
            )
    elif reading_val <= _WARNING_THRESHOLD:
        # ── Warning zone ───────────────────────────────────────
        if _has_open_alert(device_id, "low_food"):
            logger.debug("FEEDER warning alert already open — skipping (reading=%.0f)", reading_val)
        else:
            logger.info("FEEDER alert: WARNING created (reading=%.0f)", reading_val)
            _insert_alert(
                device_id, owner_id,
                alert_type = "low_food",
                severity   = "warning",
                title      = "⚠️ Alimento Bajo",
                message    = (
                    f"El nivel de alimento está bajo en '{device['device_name']}'. "
                    f"Lectura actual: {reading_val:.0f}. "
                    "Considera recargar el recipiente pronto."
                ),
            )
    # else: reading > WARNING_THRESHOLD — no alert, no log spam


def handle_water(device: dict, data: dict) -> None:
    """water_dispenser telemetry → water_events."""
    owner_id  = device["owner_id"]
    device_id = device["id"]

    level_before  = data.get("water_level_before")
    level_after   = data.get("water_level_after")
    refill        = bool(data.get("refill_triggered", False))
    supply_fail   = bool(data.get("supply_failure", False))

    try:
        supabase_admin.table("water_events").insert({
            "device_id":         device_id,
            "owner_id":          owner_id,
            "water_level_before": level_before,
            "water_level_after":  level_after,
            "refill_triggered":   refill,
            "supply_failure":     supply_fail,
            "metadata": {
                "water_level": data.get("water_level"),
                "valve_state": data.get("valve_state"),
                "raw": data,
            },
        }).execute()
    except Exception as e:
        logger.error("water_events insert failed: %s", e)

    if data.get("low_water"):
        _insert_alert(device_id, owner_id, "low_water", "warning",
                      "⚠️ Low Water Level",
                      f"Water level is low on device '{device['device_name']}'.")

    if supply_fail:
        _insert_alert(device_id, owner_id, "failed_water_refill", "critical",
                      "🚨 Water Refill Failed",
                      f"Water supply failure on device '{device['device_name']}'. "
                      "Check water supply connection.")


def handle_motion(device: dict, data: dict) -> None:
    """motion_monitoring_network telemetry → motion_events."""
    owner_id  = device["owner_id"]
    device_id = device["id"]

    detected_at = data.get("detected_at") or _now_iso()

    # Find sensor if sensor_code provided
    sensor_id = None
    sensor_code = data.get("sensor_code")
    if sensor_code:
        try:
            s = supabase_admin.table("motion_sensors") \
                .select("id") \
                .eq("motion_network_device_id", device_id) \
                .eq("sensor_code", sensor_code) \
                .execute()
            if s.data:
                sensor_id = s.data[0]["id"]
        except Exception:
            pass

    try:
        supabase_admin.table("motion_events").insert({
            "device_id":       device_id,
            "owner_id":        owner_id,
            "motion_sensor_id": sensor_id,
            "detected_at":     detected_at,
            "metadata": {
                "motion_detected":  data.get("motion_detected"),
                "sensor_code":      sensor_code,
                "inactivity_minutes": data.get("inactivity_minutes"),
                "sensor_status":    data.get("sensor_status"),
                "raw": data,
            },
        }).execute()
    except Exception as e:
        logger.error("motion_events insert failed: %s", e)

    inactivity = data.get("inactivity_minutes", 0)
    if inactivity and inactivity > 0:
        # Load configured threshold
        try:
            cfg = supabase_admin.table("motion_network_configurations") \
                .select("max_inactivity_minutes") \
                .eq("device_id", device_id).execute()
            threshold = cfg.data[0]["max_inactivity_minutes"] if cfg.data else 60
        except Exception:
            threshold = 60

        if inactivity >= threshold:
            _insert_alert(device_id, owner_id, "inactivity", "warning",
                          "⚠️ Pet Inactivity Detected",
                          f"No motion detected for {inactivity} minutes on "
                          f"device '{device['device_name']}'.")


def handle_audio(device: dict, data: dict) -> None:
    """audio_communication telemetry → audio_events."""
    owner_id  = device["owner_id"]
    device_id = device["id"]

    status = data.get("status", "sent")
    if status not in ("sent","delivered","played","failed"):
        status = "sent"

    try:
        supabase_admin.table("audio_events").insert({
            "device_id":  device_id,
            "owner_id":   owner_id,
            "audio_url":  data.get("audio_file"),
            "status":     status,
            "played_at":  data.get("playback_finished"),
            "sent_at":    data.get("playback_started") or _now_iso(),
            "metadata": {
                "volume_level":  data.get("volume_level"),
                "error_message": data.get("error_message"),
                "raw": data,
            },
        }).execute()
    except Exception as e:
        logger.error("audio_events insert failed: %s", e)

    if status == "failed" or data.get("error_message"):
        _insert_alert(device_id, owner_id, "audio_playback_failed", "warning",
                      "⚠️ Audio Playback Failed",
                      f"Audio playback failed on device '{device['device_name']}': "
                      f"{data.get('error_message','unknown error')}")


def handle_environmental(device: dict, data: dict) -> None:
    """environmental_monitor telemetry → environmental_events."""
    owner_id  = device["owner_id"]
    device_id = device["id"]

    temperature     = data.get("temperature")
    actuator_trig   = bool(data.get("actuator_triggered", False))
    status          = data.get("status", "normal")
    if status not in ("normal","too_low","too_high"):
        status = "normal"

    try:
        supabase_admin.table("environmental_events").insert({
            "device_id":         device_id,
            "owner_id":          owner_id,
            "temperature":       temperature,
            "actuator_triggered": actuator_trig,
            "status":            status,
            "metadata": {
                "humidity":       data.get("humidity"),
                "actuator_state": data.get("actuator_state"),
                "min_temperature": data.get("min_temperature"),
                "max_temperature": data.get("max_temperature"),
                "raw": data,
            },
        }).execute()
    except Exception as e:
        logger.error("environmental_events insert failed: %s", e)

    if status in ("too_low", "too_high"):
        if _has_open_alert(device_id, "temperature_out_of_range"):
            logger.debug(
                "ENV duplicate alert skipped — open temperature_out_of_range exists (device=%s status=%s)",
                device_id, status,
            )
        else:
            actuator_label = "activated" if actuator_trig else "not activated"
            _insert_alert(
                device_id, owner_id,
                alert_type = "temperature_out_of_range",
                severity   = "critical",
                title      = "Temperatura fuera de rango",
                message    = (
                    f"Temperatura {temperature}C en '{device['device_name']}' "
                    f"(estado: {status}). Control automatico {actuator_label}."
                ),
            )


def handle_door(device: dict, data: dict) -> None:
    """automatic_access_door telemetry → access_door_events."""
    owner_id  = device["owner_id"]
    device_id = device["id"]

    action  = data.get("action", "open")
    source  = data.get("source", "manual")
    success = bool(data.get("success", True))

    if action not in ("open","close"):
        action = "open"
    if source not in ("manual","scheduled","sensor"):
        source = "manual"

    try:
        supabase_admin.table("access_door_events").insert({
            "device_id": device_id,
            "owner_id":  owner_id,
            "action":    action,
            "source":    source,
            "success":   success,
            "metadata": {
                "door_state":    data.get("door_state"),
                "error_message": data.get("error_message"),
                "raw": data,
            },
        }).execute()
    except Exception as e:
        logger.error("access_door_events insert failed: %s", e)

    if not success:
        _insert_alert(device_id, owner_id,
                      f"door_failed_to_{action}", "critical",
                      f"🚨 Door Failed to {action.capitalize()}",
                      f"Door on device '{device['device_name']}' failed to {action}. "
                      f"Error: {data.get('error_message','unknown')}")


def handle_reward(device: dict, data: dict) -> None:
    """interactive_reward_system telemetry → reward_events."""
    owner_id  = device["owner_id"]
    device_id = device["id"]

    pressed_button    = data.get("pressed_button", 0)
    winning_button    = data.get("winning_button", 0)
    reward_dispensed  = bool(data.get("reward_dispensed", False))
    daily_count       = data.get("daily_reward_count", 0)

    try:
        supabase_admin.table("reward_events").insert({
            "device_id":         device_id,
            "owner_id":          owner_id,
            "pressed_button":    int(pressed_button),
            "winning_button":    int(winning_button),
            "reward_dispensed":  reward_dispensed,
            "daily_reward_count": int(daily_count),
            "metadata": {
                "cooldown_active": data.get("cooldown_active"),
                "button_count":    data.get("button_count"),
                "raw": data,
            },
        }).execute()
    except Exception as e:
        logger.error("reward_events insert failed: %s", e)

    # Load max_rewards_per_day from config
    try:
        cfg = supabase_admin.table("reward_system_configurations") \
            .select("max_rewards_per_day") \
            .eq("device_id", device_id).execute()
        max_rewards = cfg.data[0]["max_rewards_per_day"] if cfg.data else 10
    except Exception:
        max_rewards = 10

    if daily_count >= max_rewards:
        _insert_alert(device_id, owner_id, "reward_limit_reached", "info",
                      "ℹ️ Daily Reward Limit Reached",
                      f"Your pet has reached the daily reward limit ({max_rewards}) "
                      f"on device '{device['device_name']}'.")


def handle_ball_launcher(device: dict, data: dict) -> None:
    """automatic_ball_launcher telemetry → ball_launcher_events."""
    owner_id  = device["owner_id"]
    device_id = device["id"]

    launch_source = data.get("launch_source", "app")
    success       = bool(data.get("success", True))
    ball_count    = data.get("ball_count_after_launch", data.get("ball_count"))

    if launch_source not in ("app","button","scheduled"):
        launch_source = "app"

    try:
        supabase_admin.table("ball_launcher_events").insert({
            "device_id":             device_id,
            "owner_id":              owner_id,
            "launch_source":         launch_source,
            "trajectory_number":     data.get("trajectory_number"),
            "ball_count_after_launch": ball_count,
            "success":               success,
            "metadata": {
                "empty_container": data.get("empty_container"),
                "error_message":   data.get("error_message"),
                "raw": data,
            },
        }).execute()
    except Exception as e:
        logger.error("ball_launcher_events insert failed: %s", e)

    if data.get("empty_container") or (ball_count is not None and ball_count <= 0):
        _insert_alert(device_id, owner_id, "ball_container_empty", "warning",
                      "⚠️ Ball Container Empty",
                      f"The ball launcher '{device['device_name']}' has run out of balls. "
                      "Please refill the container.")

    if not success:
        _insert_alert(device_id, owner_id, "launch_failed", "warning",
                      "⚠️ Ball Launch Failed",
                      f"Ball launcher '{device['device_name']}' failed to launch. "
                      f"Error: {data.get('error_message','unknown')}")


# ── Router: dispatch by device type slug ─────────────────────

HANDLERS = {
    "automatic_feeder":          handle_feeder,
    "water_dispenser":           handle_water,
    "motion_monitoring_network": handle_motion,
    "audio_communication":       handle_audio,
    "environmental_monitor":     handle_environmental,
    "automatic_access_door":     handle_door,
    "interactive_reward_system": handle_reward,
    "automatic_ball_launcher":   handle_ball_launcher,
}


def dispatch_telemetry(serial_number: str, payload: dict) -> None:
    """
    Main entry point called by mqtt_client when a telemetry
    message arrives. Looks up the device, finds the right handler,
    and calls it.
    """
    logger.debug("TELEMETRY received — serial_number='%s'  payload=%s", serial_number, payload)

    device = _get_device(serial_number)
    if not device:
        logger.warning("TELEMETRY ignored — no device found for serial '%s'", serial_number)
        return

    device_id = device["id"]
    slug = (device.get("device_types") or {}).get("slug", "")
    logger.debug("TELEMETRY device_id='%s'  device_type_slug='%s'", device_id, slug)

    handler = HANDLERS.get(slug)
    if not handler:
        logger.warning("TELEMETRY ignored — no handler for slug '%s'", slug)
        return

    data = payload.get("data", payload)  # support both wrapped {data:{}} and flat payloads
    logger.debug("TELEMETRY data extracted: %s", data)

    handler(device, data)
    _update_device_seen(device_id, "online")


def dispatch_status(serial_number: str, payload: dict) -> None:
    """Handle heartbeat/status messages. Just updates last_seen_at."""
    device = _get_device(serial_number)
    if device:
        status = payload.get("status", "online")
        if status not in ("online","offline","error","maintenance"):
            status = "online"
        _update_device_seen(device["id"], status)


def dispatch_ack(serial_number: str, payload: dict, ack_store: dict,
                  pending_commands: dict | None = None) -> None:
    """
    Handle command acknowledgement.
    Stores in ack_store so the frontend can poll for results.
    If the ACK is for a successful dispense_food, inserts a
    manual_dispense feeding_events row.
    """
    command_id = payload.get("command_id", "unknown")
    ack_status = payload.get("status", "unknown")

    ack_store[command_id] = {
        "command_id": command_id,
        "status":     ack_status,
        "message":    payload.get("message", ""),
        "data":       payload.get("data", {}),
        "received_at": _now_iso(),
    }
    # Keep store bounded to last 100 acks
    if len(ack_store) > 100:
        oldest = list(ack_store.keys())[0]
        del ack_store[oldest]

    logger.info("ACK received for command %s: %s", command_id, ack_status)

    # ── Record manual_dispense feeding event ───────────────────
    pending = (pending_commands or {}).get(command_id, {})
    command_name = pending.get("command", "")

    if command_name == "dispense_food" and ack_status in ("ok", "success"):
        device = _get_device(serial_number)
        if device:
            params    = pending.get("params") or {}
            dispensed = params.get("grams") or params.get("dispensed_grams") or None
            try:
                supabase_admin.table("feeding_events").insert({
                    "device_id":       device["id"],
                    "owner_id":        device["owner_id"],
                    "dispensed_grams": dispensed,
                    "consumed_grams":  None,
                    "leftover_grams":  None,
                    "status_color":    "green",
                    "metadata": {
                        "event_type": "manual_dispense",
                        "command_id": command_id,
                        "params":     params,
                    },
                }).execute()
                logger.info("FEEDER manual_dispense event recorded (device=%s)", device["id"])
                # Optimistically mark state as ok after a manual dispense
                _feeder_last_state[device["id"]] = "ok"
            except Exception as e:
                logger.error("FEEDER manual_dispense insert FAILED: %s", e)

    # Remove from pending_commands once processed
    if pending_commands is not None and command_id in pending_commands:
        del pending_commands[command_id]
