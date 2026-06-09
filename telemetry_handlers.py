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


# ── In-memory state trackers ──────────────────────────────────
# Each dict maps device_id → last meaningful state so we only insert
# on transitions, not on every heartbeat packet.
# All reset to empty on Flask restart; first packet re-initialises from DB.
_feeder_last_state:      dict[str, str]  = {}          # "ok" | "low"
_water_last_state:       dict[str, str]  = {}          # "ok" | "low"
_door_last_state:        dict[str, dict] = {}          # {door_state, action}
_env_last_state:         dict[str, str]  = {}          # composite key "temp_cat:actuator" e.g. "normal:off"
_motion_last_state:      dict[str, bool | None] = {}   # True=detected, False=clear
_reward_last_state:      dict[str, dict] = {}          # {daily_count} for limit alerts
_launcher_last_state:    dict[str, dict] = {}          # {ball_count, empty}

# Alert latch for environmental_monitor temperature alerts.
# "normal" = no active high-temp alert, "high" = one is open and unsent.
# Primary gate — checked before any DB query so rapid MQTT packets never
# slip through a DB round-trip window and create duplicates.
# None (key absent) = not yet initialised for this device_id.
_env_temp_alert_latch:   dict[str, str]  = {}          # "normal" | "high"


def _get_env_alert_latch(device_id: str) -> str:
    """Return latch state for device, initialising from DB on first call."""
    if device_id in _env_temp_alert_latch:
        return _env_temp_alert_latch[device_id]
    # First packet after Flask start — check DB once so we don't double-alert
    # if a high-temp alert was already open before the restart.
    if _has_open_alert(device_id, "temperature_too_high"):
        _env_temp_alert_latch[device_id] = "high"
        logger.info("[ENV] latch initialised from DB: high (device=%s)", device_id)
    else:
        _env_temp_alert_latch[device_id] = "normal"
        logger.debug("[ENV] latch initialised from DB: normal (device=%s)", device_id)
    return _env_temp_alert_latch[device_id]


def _temp_category(temperature, min_temp, max_temp) -> str:
    """Classify temperature into 'low' / 'normal' / 'high'.
    Only category transitions are meaningful — raw value changes are not.
    """
    try:
        t  = float(temperature)
        lo = float(min_temp) if min_temp is not None else 18.0
        hi = float(max_temp) if max_temp is not None else 28.0
        if t < lo:
            return "low"
        if t > hi:
            return "high"
        return "normal"
    except (TypeError, ValueError):
        return "normal"   # treat unknown as normal — never use "unknown" to force inserts


def _actuator_norm(actuator_state_raw) -> str:
    """Normalise any truthy/falsy/string actuator value to 'on' or 'off'."""
    if actuator_state_raw is None:
        return "off"
    s = str(actuator_state_raw).strip().lower()
    return "on" if s in ("on", "true", "1", "active", "running") else "off"


def _env_state_key(temp_cat: str, actuator: str) -> str:
    """Composite state key used for change detection. e.g. 'normal:off'."""
    return f"{temp_cat}:{actuator}"


def _fetch_latest_env_state_key(device_id: str) -> str | None:
    """
    Query the most recent environmental_events row and reconstruct its state key.
    Returns None if no row exists or on query error.
    """
    try:
        res = (
            supabase_admin.table("environmental_events")
            .select("status, metadata")
            .eq("device_id", device_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if res.data:
            row  = res.data[0]
            meta = row.get("metadata") or {}

            # Reconstruct temp_cat: prefer stored temp_category, fall back to status mapping
            stored_cat = meta.get("temp_category")
            if stored_cat in ("low", "normal", "high"):
                temp_cat = stored_cat
            else:
                db_status = row.get("status", "normal")
                if db_status == "too_high":
                    temp_cat = "high"
                elif db_status == "too_low":
                    temp_cat = "low"
                else:
                    temp_cat = "normal"

            actuator = _actuator_norm(meta.get("actuator_state"))
            return _env_state_key(temp_cat, actuator)
    except Exception as e:
        logger.error("ENV DB state fallback failed: %s", e)
    return None


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
    """water_dispenser telemetry → water_events.

    State-machine approach (mirrors handle_feeder):
      ok  → low        : insert event row + fire low_water alert
      low → ok         : insert event row (level restored), auto-resolve alert
      low → low (same) : skip DB write — no spam
      ok  → ok  (same) : skip DB write

    supply_failure is always recorded when True (rare edge-case event).
    """
    owner_id  = device["owner_id"]
    device_id = device["id"]

    level_before = data.get("water_level_before")
    level_after  = data.get("water_level_after")
    refill       = bool(data.get("refill_triggered", False))
    supply_fail  = bool(data.get("supply_failure",   False))
    low_water    = bool(data.get("low_water",         False))

    current_state = "low" if low_water else "ok"
    prev_state    = _water_last_state.get(device_id)   # None on first packet
    _water_last_state[device_id] = current_state

    state_changed = (prev_state != current_state)

    # ── DB write: only on state change OR supply failure ──────────
    if state_changed or supply_fail:
        try:
            supabase_admin.table("water_events").insert({
                "device_id":          device_id,
                "owner_id":           owner_id,
                "water_level_before": level_before,
                "water_level_after":  level_after,
                "refill_triggered":   refill,
                "supply_failure":     supply_fail,
                "metadata": {
                    "water_level": data.get("water_level"),
                    "valve_state": data.get("valve_state"),
                    "event":       "level_low" if (state_changed and current_state == "low")
                                   else "level_restored" if (state_changed and current_state == "ok")
                                   else "supply_failure",
                    "raw": data,
                },
            }).execute()
            logger.info("WATER event recorded: %s→%s (device=%s)", prev_state, current_state, device_id)
        except Exception as e:
            logger.error("water_events insert failed: %s", e)
    else:
        logger.debug("WATER no state change (%s) — skipping DB write (device=%s)", current_state, device_id)

    # ── Refill counter: decrement when a refill cycle just completed ──
    # ESP32 sends refill_completed=true on the packet where the servo
    # finishes its 2-second open cycle and closes. It also reports
    # refills_remaining (AFTER decrement) so we persist it here.
    refill_completed = bool(data.get("refill_completed", False))
    if refill_completed:
        _handle_water_refill_completed(device, data)

    # ── Alert logic — deduplicated ────────────────────────────────
    if state_changed and current_state == "low":
        if not _has_open_alert(device_id, "low_water"):
            _insert_alert(device_id, owner_id, "low_water", "warning",
                          "⚠️ Nivel de Agua Bajo",
                          f"El nivel de agua es bajo en '{device['device_name']}'. "
                          "El dispensador intentará recarga automática.")

    if state_changed and current_state == "ok":
        logger.info("WATER level restored on device=%s", device_id)

    if supply_fail:
        if not _has_open_alert(device_id, "failed_water_refill"):
            _insert_alert(device_id, owner_id, "failed_water_refill", "critical",
                          "🚨 Fallo en Recarga de Agua",
                          f"Fallo de suministro en '{device['device_name']}'. "
                          "Revisa la conexión del depósito de recarga.")


def _handle_water_refill_completed(device: dict, data: dict) -> None:
    """
    Called when the ESP32 reports a completed refill cycle (servo opened 2s + closed).
    Persists refills_remaining from the device report and fires alerts at 1 and 0.
    """
    device_id = device["id"]
    owner_id  = device["owner_id"]
    refills   = data.get("refills_remaining")  # reported by ESP32 AFTER decrement

    logger.info("WATER refill completed — remaining=%s device=%s", refills, device_id)

    if refills is not None:
        try:
            refills = int(refills)
            res = supabase_admin.table("water_configurations").select("id") \
                      .eq("device_id", device_id).execute()
            if res.data:
                supabase_admin.table("water_configurations") \
                    .update({"refills_remaining": refills}) \
                    .eq("id", res.data[0]["id"]).execute()
        except Exception as e:
            logger.error("water_configurations refill update failed: %s", e)
            refills = -1

    # Alert at 1 remaining
    if refills == 1:
        if not _has_open_alert(device_id, "water_refill_low"):
            _insert_alert(device_id, owner_id, "water_refill_low", "warning",
                          "⚠️ Última recarga de agua disponible",
                          f"Al dispensador '{device['device_name']}' le queda solo 1 recarga. "
                          "Rellena el depósito y reinicia el contador en la app.")

    # Alert at 0 — valve locked on device
    if refills == 0:
        if not _has_open_alert(device_id, "water_refills_exhausted"):
            _insert_alert(device_id, owner_id, "water_refills_exhausted", "critical",
                          "🚨 Recargas de agua agotadas",
                          f"El dispensador '{device['device_name']}' ha agotado sus recargas. "
                          "La válvula está bloqueada. Rellena el depósito y reinicia el "
                          "contador en 'Water Settings'.")


def handle_motion(device: dict, data: dict) -> None:
    """motion_monitoring_network telemetry → motion_events.

    Inserts a row ONLY on state transitions:
      no-motion → motion-detected  : event saved
      motion-detected → no-motion  : event saved (area cleared)
      same state repeated           : skip DB write
    """
    owner_id  = device["owner_id"]
    device_id = device["id"]

    detected_at   = data.get("detected_at") or _now_iso()
    motion_now    = bool(data.get("motion_detected", False))
    prev_motion   = _motion_last_state.get(device_id)   # None on first packet

    state_changed = (prev_motion is None and motion_now) or (prev_motion != motion_now)
    _motion_last_state[device_id] = motion_now

    logger.debug("MOTION device=%s prev=%s now=%s changed=%s",
                 device_id, prev_motion, motion_now, state_changed)

    if not state_changed and not data.get("inactivity_minutes"):
        logger.debug("MOTION no state change — skipping DB write (device=%s)", device_id)
    else:
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

        if state_changed:
            try:
                supabase_admin.table("motion_events").insert({
                    "device_id":        device_id,
                    "owner_id":         owner_id,
                    "motion_sensor_id": sensor_id,
                    "detected_at":      detected_at,
                    "metadata": {
                        "motion_detected":    motion_now,
                        "sensor_code":        sensor_code,
                        "inactivity_minutes": data.get("inactivity_minutes"),
                        "sensor_status":      data.get("sensor_status"),
                        "raw": data,
                    },
                }).execute()
                event_label = "detected" if motion_now else "cleared"
                logger.info("MOTION event recorded: %s (device=%s)", event_label, device_id)
            except Exception as e:
                logger.error("motion_events insert failed: %s", e)

    inactivity = data.get("inactivity_minutes", 0)
    if inactivity and inactivity > 0:
        try:
            cfg = supabase_admin.table("motion_network_configurations") \
                .select("max_inactivity_minutes") \
                .eq("device_id", device_id).execute()
            threshold = cfg.data[0]["max_inactivity_minutes"] if cfg.data else 60
        except Exception:
            threshold = 60

        if inactivity >= threshold:
            if not _has_open_alert(device_id, "inactivity"):
                _insert_alert(device_id, owner_id, "inactivity", "warning",
                              "⚠️ Pet Inactivity Detected",
                              f"No motion detected for {inactivity} minutes on "
                              f"device '{device['device_name']}'.")
            else:
                logger.debug("MOTION inactivity alert already open — skipping (device=%s)", device_id)


def handle_audio(device: dict, data: dict) -> None:
    """audio_communication telemetry → audio_events.

    Inserts a row only for meaningful audio events:
      played / delivered / failed / error — always recorded
      idle heartbeat (no audio_file, status not meaningful) — skipped
    """
    owner_id  = device["owner_id"]
    device_id = device["id"]

    raw_status = data.get("status", "idle")
    error_msg  = data.get("error_message")

    # Normalise to valid DB values
    if raw_status in ("sent", "delivered", "played", "failed"):
        status = raw_status
    else:
        status = None  # idle / unknown — not a meaningful event

    # Skip idle heartbeats: no audio file, no error, not a real event status
    is_idle_heartbeat = (
        status is None
        and not data.get("audio_file")
        and not error_msg
    )
    if is_idle_heartbeat:
        logger.debug("AUDIO idle heartbeat — skipping DB write (device=%s)", device_id)
        return

    if status is None:
        status = "sent"  # fallback for edge cases that passed the idle check

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
                "error_message": error_msg,
                "raw": data,
            },
        }).execute()
        logger.info("AUDIO event recorded: %s (device=%s)", status, device_id)
    except Exception as e:
        logger.error("audio_events insert failed: %s", e)

    if status == "failed" or error_msg:
        if not _has_open_alert(device_id, "audio_playback_failed"):
            _insert_alert(device_id, owner_id, "audio_playback_failed", "warning",
                          "⚠️ Audio Playback Failed",
                          f"Audio playback failed on device '{device['device_name']}': "
                          f"{error_msg or 'unknown error'}")
        else:
            logger.debug("AUDIO playback_failed alert already open — skipping (device=%s)", device_id)


def handle_environmental(device: dict, data: dict) -> None:
    """environmental_monitor telemetry → environmental_events.

    DB insert: only on categorical state changes (temp_cat or actuator),
    errors, or first-boot abnormal state. Normal heartbeats are skipped.

    Alert logic: ALWAYS runs regardless of whether a DB row was inserted.
    This ensures return-to-normal is detected even when the normal heartbeat
    row itself is deduplicated and not written to the DB.
    """
    owner_id  = device["owner_id"]
    device_id = device["id"]
    serial    = device.get("serial_number", "ENV")

    temperature   = data.get("temperature")
    actuator_trig = bool(data.get("actuator_triggered", False))
    error_msg     = data.get("error_message")
    success       = bool(data.get("success", True))

    raw_status = data.get("status", "normal")
    if raw_status not in ("normal", "too_low", "too_high"):
        raw_status = "normal"

    min_t    = data.get("min_temperature")
    max_t    = data.get("max_temperature")
    temp_cat = _temp_category(temperature, min_t, max_t)   # "low" | "normal" | "high"
    actuator = _actuator_norm(data.get("actuator_state"))  # "on"  | "off"

    current_key = _env_state_key(temp_cat, actuator)

    # ── Load previous state key (cache → DB fallback → None) ─────────
    prev_key = _env_last_state.get(device_id)
    if prev_key is None:
        prev_key = _fetch_latest_env_state_key(device_id)
        if prev_key is not None:
            _env_last_state[device_id] = prev_key
            logger.debug("[ENV] loaded previous state from DB: %s (device=%s)", prev_key, device_id)

    prev_temp_cat = prev_key.split(":")[0] if prev_key else None

    # ── DB insert decision ────────────────────────────────────────────
    is_error            = (not success) or bool(error_msg)
    state_changed       = (prev_key is None and temp_cat != "normal") or (prev_key != current_key)
    first_packet_normal = (prev_key is None and temp_cat == "normal" and actuator == "off")
    should_insert       = (is_error or state_changed) and not first_packet_normal

    if should_insert:
        if prev_key and prev_key != current_key:
            logger.info("[ENV] state changed %s -> %s, inserting event (device=%s)",
                        prev_key, current_key, device_id)
        elif prev_key is None:
            logger.info("[ENV] first abnormal state %s, inserting event (device=%s)",
                        current_key, device_id)
        else:
            logger.info("[ENV] error event, inserting (device=%s error=%s)", device_id, error_msg)

        try:
            supabase_admin.table("environmental_events").insert({
                "device_id":          device_id,
                "owner_id":           owner_id,
                "temperature":        temperature,
                "actuator_triggered": actuator_trig,
                "status":             raw_status,
                "metadata": {
                    "humidity":        data.get("humidity"),
                    "actuator_state":  actuator,
                    "min_temperature": min_t,
                    "max_temperature": max_t,
                    "temp_category":   temp_cat,
                    "error_message":   error_msg,
                    "raw": data,
                },
            }).execute()
        except Exception as e:
            logger.error("environmental_events insert failed: %s", e)
            return   # do NOT update cache or fire alerts — retry on next packet

        _env_last_state[device_id] = current_key
    else:
        logger.debug("[ENV] duplicate normal heartbeat skipped (device=%s key=%s)", device_id, current_key)
        if prev_key is None:
            _env_last_state[device_id] = current_key

    # ── Alert logic — always runs, independent of DB insert ──────────
    # Uses an in-memory latch as primary gate.
    # The latch is initialised from the DB once per Flask session per device,
    # then all transitions are tracked in memory so rapid MQTT packets never
    # race against a DB round-trip and create duplicate alerts.
    try:
        temp_str = f"{float(temperature):.1f}" if temperature is not None else "?"
    except (TypeError, ValueError):
        temp_str = str(temperature) if temperature is not None else "?"

    try:
        max_str = f"{float(max_t):.1f}" if max_t is not None else "?"
    except (TypeError, ValueError):
        max_str = str(max_t) if max_t is not None else "?"

    latch = _get_env_alert_latch(device_id)

    if temp_cat == "high":
        if latch != "high":
            # Transition normal → high: send one alert, then latch
            logger.info("[ENV] temperature category changed %s -> high (device=%s)",
                        prev_temp_cat or "normal", device_id)
            _insert_alert(
                device_id, owner_id,
                alert_type = "temperature_too_high",
                severity   = "warning",
                title      = "High Temperature Detected",
                message    = (
                    f"{serial} temperature is too high: {temp_str}C. "
                    f"Maximum allowed is {max_str}C."
                ),
            )
            logger.info("[ENV] high temperature alert created (device=%s)", device_id)
            _env_temp_alert_latch[device_id] = "high"
        else:
            logger.debug("[ENV] duplicate high temperature skipped (device=%s)", device_id)

    elif temp_cat == "normal":
        if latch == "high":
            # Transition high → normal: send back-to-normal, release latch
            logger.info("[ENV] temperature category changed high -> normal (device=%s)", device_id)
            _insert_alert(
                device_id, owner_id,
                alert_type = "temperature_back_to_normal",
                severity   = "info",
                title      = "Temperature Back to Normal",
                message    = f"{serial} temperature returned to normal: {temp_str}C.",
            )
            logger.info("[ENV] back-to-normal alert created (device=%s)", device_id)
            _env_temp_alert_latch[device_id] = "normal"
            # Resolve the open DB alert so it no longer appears as unresolved
            try:
                supabase_admin.table("alerts").update({
                    "resolved_at": _now_iso(),
                    "is_read":     True,
                }).eq("device_id",  device_id) \
                  .eq("alert_type", "temperature_too_high") \
                  .is_("resolved_at", "null") \
                  .execute()
            except Exception as e:
                logger.error("[ENV] Could not resolve temperature_too_high alert: %s", e)
        else:
            logger.debug("[ENV] duplicate normal heartbeat skipped (device=%s)", device_id)


def _door_is_duplicate(device_id: str, door_state: str, action: str) -> bool:
    """
    Return True if the last known door state for this device is the same.
    Checks in-memory cache first; falls back to a single Supabase query on
    Flask restart (when the cache is empty) so we never spam the DB after a
    process restart either.
    """
    cached = _door_last_state.get(device_id)
    if cached is not None:
        return cached["door_state"] == door_state and cached["action"] == action

    # Cache miss (first packet after restart) — query the latest stored event
    try:
        res = (
            supabase_admin.table("access_door_events")
            .select("action, metadata")
            .eq("device_id", device_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if res.data:
            prev = res.data[0]
            prev_state  = (prev.get("metadata") or {}).get("door_state", "")
            prev_action = prev.get("action", "")
            _door_last_state[device_id] = {"door_state": prev_state, "action": prev_action}
            return prev_state == door_state and prev_action == action
    except Exception as e:
        logger.error("DOOR fallback state query failed: %s", e)

    return False  # on error allow the insert


def handle_door(device: dict, data: dict) -> None:
    """
    automatic_access_door telemetry → access_door_events.

    Inserts a row ONLY on meaningful transitions:
      * door_state changes (closed→open or open→closed)
      * action is explicitly "open" or "close" AND state differs from last insert
      * success is False (failures always recorded)

    Heartbeat/repeated-same-state packets update the in-memory tracker and
    trigger alert evaluation but do NOT write a new DB row.
    """
    owner_id  = device["owner_id"]
    device_id = device["id"]

    raw_action  = data.get("action", "")
    source      = data.get("source", "app")
    success     = bool(data.get("success", True))
    door_state  = data.get("door_state", "")
    error_msg   = data.get("error_message") or ""

    # Normalise action for DB storage — "heartbeat" is not a valid action column value
    action = raw_action if raw_action in ("open", "close") else "close"

    if source not in ("serial", "app", "heartbeat", "manual", "scheduled", "sensor"):
        source = "app"

    logger.debug("DOOR telemetry received — device=%s raw_action=%s source=%s door_state=%s success=%s",
                 device_id, raw_action, source, door_state, success)

    # ── Decide whether to insert ──────────────────────────────────
    # Always insert on failure; skip repeated identical success packets.
    is_heartbeat    = raw_action in ("heartbeat",) or source == "heartbeat"
    is_duplicate    = _door_is_duplicate(device_id, door_state, action)

    should_insert = not success or (not is_heartbeat and not is_duplicate)

    if should_insert:
        try:
            supabase_admin.table("access_door_events").insert({
                "device_id": device_id,
                "owner_id":  owner_id,
                "action":    action,
                "source":    source,
                "success":   success,
                "metadata": {
                    "door_state":    door_state,
                    "error_message": error_msg or None,
                    "raw": data,
                },
            }).execute()
            _door_last_state[device_id] = {"door_state": door_state, "action": action}
            logger.info("DOOR access_door_events insert OK — device=%s action=%s door_state=%s",
                        device_id, action, door_state)
        except Exception as e:
            logger.error("access_door_events insert failed: %s", e)
    else:
        logger.debug("DOOR duplicate/heartbeat skipped — device=%s door_state=%s action=%s",
                     device_id, door_state, action)

    # ── Alert logic — runs on every packet regardless of insert ──
    if success and door_state == "open":
        if not _has_open_alert(device_id, "door_open"):
            _insert_alert(
                device_id, owner_id,
                alert_type = "door_open",
                severity   = "warning",
                title      = "Door Opened",
                message    = f"{device['serial_number']} is open.",
            )
        else:
            logger.debug("DOOR door_open alert already open — skipping (device=%s)", device_id)

    elif not success:
        alert_type = f"door_failed_to_{action}"
        if not _has_open_alert(device_id, alert_type):
            detail = f" Error: {error_msg}" if error_msg else ""
            _insert_alert(
                device_id, owner_id,
                alert_type = alert_type,
                severity   = "critical",
                title      = f"Door Failed to {action.capitalize()}",
                message    = (
                    f"Door on device '{device['device_name']}' failed to {action}.{detail}"
                ),
            )
        else:
            logger.debug("DOOR %s alert already open — skipping (device=%s)", alert_type, device_id)


def handle_reward(device: dict, data: dict) -> None:
    """interactive_reward_system telemetry → reward_events.

    Inserts a row ONLY for meaningful game events:
      reward_dispensed = True               — always record
      pressed_button > 0 (pet interacted)   — record the interaction
      inventory low / error                 — record
    Idle heartbeats (no button pressed, no dispense) are skipped.
    """
    owner_id  = device["owner_id"]
    device_id = device["id"]

    pressed_button   = data.get("pressed_button", 0)
    winning_button   = data.get("winning_button", 0)
    reward_dispensed = bool(data.get("reward_dispensed", False))
    daily_count      = data.get("daily_reward_count", 0)
    error_msg        = data.get("error_message")
    low_inventory    = bool(data.get("low_inventory", False))

    # Idle heartbeat: nothing happened
    is_idle = (
        not reward_dispensed
        and int(pressed_button or 0) == 0
        and not error_msg
        and not low_inventory
    )
    if is_idle:
        logger.debug("REWARD idle heartbeat — skipping DB write (device=%s)", device_id)
    else:
        try:
            supabase_admin.table("reward_events").insert({
                "device_id":          device_id,
                "owner_id":           owner_id,
                "pressed_button":     int(pressed_button or 0),
                "winning_button":     int(winning_button or 0),
                "reward_dispensed":   reward_dispensed,
                "daily_reward_count": int(daily_count or 0),
                "metadata": {
                    "cooldown_active": data.get("cooldown_active"),
                    "button_count":    data.get("button_count"),
                    "low_inventory":   low_inventory,
                    "error_message":   error_msg,
                    "raw": data,
                },
            }).execute()
            logger.info("REWARD event recorded: dispensed=%s button=%s (device=%s)",
                        reward_dispensed, pressed_button, device_id)
        except Exception as e:
            logger.error("reward_events insert failed: %s", e)

    # ── Alert: daily limit ────────────────────────────────────────────
    try:
        cfg = supabase_admin.table("reward_system_configurations") \
            .select("max_rewards_per_day") \
            .eq("device_id", device_id).execute()
        max_rewards = cfg.data[0]["max_rewards_per_day"] if cfg.data else 10
    except Exception:
        max_rewards = 10

    if int(daily_count or 0) >= max_rewards:
        if not _has_open_alert(device_id, "reward_limit_reached"):
            _insert_alert(device_id, owner_id, "reward_limit_reached", "info",
                          "ℹ️ Daily Reward Limit Reached",
                          f"Your pet has reached the daily reward limit ({max_rewards}) "
                          f"on device '{device['device_name']}'.")
        else:
            logger.debug("REWARD limit alert already open — skipping (device=%s)", device_id)

    if low_inventory and not _has_open_alert(device_id, "reward_inventory_low"):
        _insert_alert(device_id, owner_id, "reward_inventory_low", "warning",
                      "⚠️ Reward Inventory Low",
                      f"Reward inventory is running low on '{device['device_name']}'. "
                      "Please refill the dispenser.")


def handle_ball_launcher(device: dict, data: dict) -> None:
    """automatic_ball_launcher telemetry → ball_launcher_events.

    Inserts a row ONLY on meaningful events:
      ball_launched = True / launch just happened  — always record
      empty_container changed state                — record
      success = False                              — record
      idle status heartbeat (no launch)            — skip
    """
    owner_id  = device["owner_id"]
    device_id = device["id"]

    launch_source  = data.get("launch_source", "app")
    success        = bool(data.get("success", True))
    ball_count     = data.get("ball_count_after_launch", data.get("ball_count"))
    empty_container = bool(data.get("empty_container", False))
    error_msg      = data.get("error_message")
    ball_launched  = bool(data.get("ball_launched", False))

    if launch_source not in ("app", "button", "scheduled"):
        launch_source = "app"

    # Check if empty state changed vs last known
    prev_launcher = _launcher_last_state.get(device_id, {})
    prev_empty    = prev_launcher.get("empty", False)
    empty_changed = empty_container != prev_empty

    # Idle heartbeat: device is online but no launch occurred, no new empty state
    is_idle = (
        not ball_launched
        and success
        and not empty_changed
        and not error_msg
        and not data.get("trajectory_number")  # no trajectory = no launch attempt
    )

    if is_idle:
        logger.debug("LAUNCHER idle heartbeat — skipping DB write (device=%s)", device_id)
    else:
        try:
            supabase_admin.table("ball_launcher_events").insert({
                "device_id":               device_id,
                "owner_id":                owner_id,
                "launch_source":           launch_source,
                "trajectory_number":       data.get("trajectory_number"),
                "ball_count_after_launch": ball_count,
                "success":                 success,
                "metadata": {
                    "empty_container": empty_container,
                    "error_message":   error_msg,
                    "ball_launched":   ball_launched,
                    "raw": data,
                },
            }).execute()
            logger.info("LAUNCHER event recorded: launched=%s success=%s (device=%s)",
                        ball_launched, success, device_id)
        except Exception as e:
            logger.error("ball_launcher_events insert failed: %s", e)

    # Update state cache
    _launcher_last_state[device_id] = {"empty": empty_container}

    # ── Alerts ───────────────────────────────────────────────────────
    if empty_container and empty_changed:
        if not _has_open_alert(device_id, "ball_container_empty"):
            _insert_alert(device_id, owner_id, "ball_container_empty", "warning",
                          "⚠️ Ball Container Empty",
                          f"The ball launcher '{device['device_name']}' has run out of balls. "
                          "Please refill the container.")
    elif not empty_container and prev_empty:
        logger.info("LAUNCHER ball container refilled (device=%s)", device_id)

    if not success and error_msg:
        if not _has_open_alert(device_id, "launch_failed"):
            _insert_alert(device_id, owner_id, "launch_failed", "warning",
                          "⚠️ Ball Launch Failed",
                          f"Ball launcher '{device['device_name']}' failed to launch. "
                          f"Error: {error_msg or 'unknown'}")
        else:
            logger.debug("LAUNCHER launch_failed alert already open — skipping (device=%s)", device_id)


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