"""
api.py
------
Flask Blueprint exposing all JSON REST API endpoints under /api.

All responses follow:
  { "ok": true,  "data": ... }
  { "ok": false, "error": "message" }

Authentication: Flask session (same as page routes).
RLS: All queries filter by owner_id = current_user_id().
"""

import uuid
import logging
from functools import wraps
from flask import Blueprint, jsonify, request, session

import commands as cmd_module
import mqtt_client
from config import supabase
from utils import get_supabase_with_session, current_user_id

api_bp  = Blueprint("api", __name__, url_prefix="/api")
logger  = logging.getLogger(__name__)

# ── Auth helpers ──────────────────────────────────────────────

def api_auth(f):
    """Decorator: return 401 JSON if not logged in."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"ok": False, "error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return decorated


def ok(data):
    return jsonify({"ok": True, "data": data})


def err(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


# ── Session / Me ──────────────────────────────────────────────

@api_bp.route("/me")
@api_auth
def me():
    return ok({
        "user_id":      session.get("user_id"),
        "email":        session.get("user_email"),
        "display_name": session.get("display_name"),
    })


@api_bp.route("/mqtt/status")
@api_auth
def mqtt_status():
    return ok({
        "connected": mqtt_client.is_connected(),
        "host":      __import__("config").MQTT_HOST or "not configured",
    })


# ── Device Types ──────────────────────────────────────────────

@api_bp.route("/device-types")
@api_auth
def device_types():
    sb = get_supabase_with_session()
    res = sb.table("device_types").select("*").order("name").execute()
    return ok(res.data or [])


# ── Devices ───────────────────────────────────────────────────

@api_bp.route("/devices", methods=["GET"])
@api_auth
def get_devices():
    sb  = get_supabase_with_session()
    uid = current_user_id()
    try:
        res = (
            sb.table("devices")
            .select("*, device_types(slug, name), pets(name), locations(name)")
            .eq("owner_id", uid)
            .order("device_name")
            .execute()
        )
        return ok(res.data or [])
    except Exception as e:
        return err(str(e))


@api_bp.route("/devices/<device_id>", methods=["GET"])
@api_auth
def get_device(device_id):
    sb  = get_supabase_with_session()
    uid = current_user_id()
    try:
        res = (
            sb.table("devices")
            .select("*, device_types(slug, name), pets(name), locations(name)")
            .eq("id", device_id).eq("owner_id", uid)
            .single().execute()
        )
        if not res.data:
            return err("Device not found", 404)
        # Attach command definitions for this device type
        slug   = (res.data.get("device_types") or {}).get("slug", "")
        result = dict(res.data)
        result["commands"] = cmd_module.get_commands_for_slug(slug)
        return ok(result)
    except Exception as e:
        return err(str(e))


@api_bp.route("/devices", methods=["POST"])
@api_auth
def create_device():
    sb  = get_supabase_with_session()
    uid = current_user_id()
    body = request.get_json(silent=True) or {}

    serial_number  = (body.get("serial_number") or "").strip()
    device_type_id = body.get("device_type_id")
    device_name    = (body.get("device_name") or "").strip()
    pet_id         = body.get("pet_id") or None
    location_id    = body.get("location_id") or None

    if not serial_number or not device_type_id or not device_name:
        return err("serial_number, device_type_id, and device_name are required")

    try:
        res = sb.table("devices").insert({
            "serial_number":  serial_number,
            "device_type_id": int(device_type_id),
            "owner_id":       uid,
            "pet_id":         pet_id,
            "location_id":    location_id,
            "device_name":    device_name,
            "status":         "offline",
            "is_active":      True,
        }).execute()
        return ok(res.data[0] if res.data else {})
    except Exception as e:
        return err(str(e))


@api_bp.route("/devices/<device_id>", methods=["PATCH"])
@api_auth
def update_device(device_id):
    sb   = get_supabase_with_session()
    uid  = current_user_id()
    body = request.get_json(silent=True) or {}
    allowed = {"device_name","pet_id","location_id","status","is_active"}
    update  = {k: v for k, v in body.items() if k in allowed}
    if not update:
        return err("No valid fields to update")
    try:
        sb.table("devices").update(update).eq("id", device_id).eq("owner_id", uid).execute()
        return ok({"updated": True})
    except Exception as e:
        return err(str(e))


@api_bp.route("/devices/<device_id>", methods=["DELETE"])
@api_auth
def delete_device(device_id):
    sb  = get_supabase_with_session()
    uid = current_user_id()
    try:
        sb.table("devices").delete().eq("id", device_id).eq("owner_id", uid).execute()
        return ok({"deleted": True})
    except Exception as e:
        return err(str(e))


# ── Events / Telemetry ────────────────────────────────────────

# Map device type slug → event table name + relevant columns
EVENT_TABLES = {
    "automatic_feeder":          ("feeding_events",      "created_at, dispensed_grams, consumed_grams, leftover_grams, status_color, metadata"),
    "water_dispenser":           ("water_events",        "created_at, water_level_before, water_level_after, refill_triggered, supply_failure, metadata"),
    "motion_monitoring_network": ("motion_events",       "detected_at, created_at, motion_sensor_id, metadata"),
    "audio_communication":       ("audio_events",        "created_at, audio_url, status, sent_at, played_at, metadata"),
    "environmental_monitor":     ("environmental_events","created_at, temperature, status, actuator_triggered, metadata"),
    "automatic_access_door":     ("access_door_events",  "created_at, action, source, success, metadata"),
    "interactive_reward_system": ("reward_events",       "created_at, pressed_button, winning_button, reward_dispensed, daily_reward_count, metadata"),
    "automatic_ball_launcher":   ("ball_launcher_events","created_at, launch_source, trajectory_number, ball_count_after_launch, success, metadata"),
}


@api_bp.route("/devices/<device_id>/events")
@api_auth
def get_device_events(device_id):
    sb    = get_supabase_with_session()
    uid   = current_user_id()
    limit = min(int(request.args.get("limit", 20)), 100)

    # First verify ownership and get device type
    try:
        d = (
            sb.table("devices")
            .select("id, device_types(slug)")
            .eq("id", device_id).eq("owner_id", uid)
            .single().execute()
        )
    except Exception:
        return err("Device not found", 404)

    if not d.data:
        return err("Device not found", 404)

    slug = (d.data.get("device_types") or {}).get("slug", "")
    if slug not in EVENT_TABLES:
        return ok([])

    table, columns = EVENT_TABLES[slug]
    try:
        # For automatic_feeder, only return meaningful event-type rows
        # (low_food_detected, food_level_ok, manual_dispense).
        # Normal periodic telemetry rows have no event_type — fetch extra and filter.
        fetch_limit = limit * 10 if slug == "automatic_feeder" else limit
        res = (
            sb.table(table)
            .select(columns)
            .eq("device_id", device_id)
            .order("created_at", desc=True)
            .limit(fetch_limit)
            .execute()
        )
        rows = res.data or []
        if slug == "automatic_feeder":
            rows = [r for r in rows if (r.get("metadata") or {}).get("event_type")][:limit]
        return ok(rows)
    except Exception as e:
        return err(str(e))


# ── Telemetry (all devices) ───────────────────────────────────

@api_bp.route("/telemetry")
@api_auth
def get_telemetry():
    """
    Return raw telemetry rows across all the user's devices.
    Currently covers automatic_feeder (feeding_events).
    Extensible: add more device slugs / tables below.

    Query params:
      device_id    – filter to one device UUID
      device_type  – filter by slug (e.g. automatic_feeder)
      status_color – filter by status_color value
      limit        – max rows (default 50, max 200)
    """
    sb    = get_supabase_with_session()
    uid   = current_user_id()
    limit = min(int(request.args.get("limit", 50)), 200)
    filter_device_id    = request.args.get("device_id", "").strip()
    filter_device_type  = request.args.get("device_type", "").strip()
    filter_status_color = request.args.get("status_color", "").strip()

    rows = []

    # ── automatic_feeder → feeding_events ─────────────────────
    if not filter_device_type or filter_device_type == "automatic_feeder":
        try:
            q = (sb.table("feeding_events")
                 .select("created_at, dispensed_grams, consumed_grams, leftover_grams, "
                         "status_color, metadata, "
                         "devices(id, device_name, serial_number, device_types(slug, name))")
                 .eq("owner_id", uid)
                 .order("created_at", desc=True)
                 .limit(limit))
            if filter_device_id:
                q = q.eq("device_id", filter_device_id)
            if filter_status_color:
                q = q.eq("status_color", filter_status_color)
            res = q.execute()
            for r in (res.data or []):
                dev = r.pop("devices", {}) or {}
                dt  = dev.pop("device_types", {}) or {}
                rows.append({
                    "created_at":       r.get("created_at"),
                    "device_name":      dev.get("device_name", "—"),
                    "serial_number":    dev.get("serial_number", "—"),
                    "device_id":        dev.get("id", ""),
                    "device_type_slug": dt.get("slug", "automatic_feeder"),
                    "device_type_name": dt.get("name", "Automatic Feeder"),
                    "status_color":     r.get("status_color"),
                    "event_type":       (r.get("metadata") or {}).get("event_type"),
                    "dispensed_grams":  r.get("dispensed_grams"),
                    "consumed_grams":   r.get("consumed_grams"),
                    "leftover_grams":   r.get("leftover_grams"),
                    "food_remaining":   (r.get("metadata") or {}).get("food_remaining_grams"),
                })
        except Exception as e:
            logger.error("Telemetry fetch failed (feeding_events): %s", e)

    # -- water_dispenser -> water_events --
    if not filter_device_type or filter_device_type == "water_dispenser":
        try:
            q = (sb.table("water_events")
                 .select("created_at, water_level_before, water_level_after, "
                         "refill_triggered, supply_failure, metadata, "
                         "devices(id, device_name, serial_number, device_types(slug, name))")
                 .eq("owner_id", uid)
                 .order("created_at", desc=True)
                 .limit(limit))
            if filter_device_id:
                q = q.eq("device_id", filter_device_id)
            res = q.execute()
            for r in (res.data or []):
                dev = r.pop("devices", {}) or {}
                dt  = dev.pop("device_types", {}) or {}
                meta = r.get("metadata") or {}
                rows.append({
                    "created_at":         r.get("created_at"),
                    "device_name":        dev.get("device_name", "-"),
                    "serial_number":      dev.get("serial_number", "-"),
                    "device_id":          dev.get("id", ""),
                    "device_type_slug":   dt.get("slug", "water_dispenser"),
                    "device_type_name":   dt.get("name", "Water Dispenser"),
                    "status_color":       "red" if r.get("supply_failure") else
                                          "yellow" if (meta.get("event") == "level_low") else "green",
                    "event_type":         meta.get("event"),
                    "water_level":        meta.get("water_level"),
                    "water_level_before": r.get("water_level_before"),
                    "water_level_after":  r.get("water_level_after"),
                    "refill_triggered":   r.get("refill_triggered"),
                    "supply_failure":     r.get("supply_failure"),
                    "valve_state":        meta.get("valve_state"),
                })
        except Exception as e:
            logger.error("Telemetry fetch failed (water_events): %s", e)

    # Sort combined rows newest-first and trim to limit
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return ok(rows[:limit])


# ── Commands ──────────────────────────────────────────────────

@api_bp.route("/devices/<device_id>/command", methods=["POST"])
@api_auth
def send_command(device_id):
    sb   = get_supabase_with_session()
    uid  = current_user_id()
    body = request.get_json(silent=True) or {}

    command = (body.get("command") or "").strip()
    params  = body.get("params") or {}

    if not command:
        return err("'command' is required")

    # Verify device ownership
    try:
        d = (
            sb.table("devices")
            .select("serial_number, device_types(slug)")
            .eq("id", device_id).eq("owner_id", uid)
            .single().execute()
        )
    except Exception:
        return err("Device not found", 404)

    if not d.data:
        return err("Device not found", 404)

    serial_number = d.data["serial_number"]
    slug          = (d.data.get("device_types") or {}).get("slug", "")

    # Validate command is valid for this device type
    valid_commands = [c["command"] for c in cmd_module.get_commands_for_slug(slug)]
    if command not in valid_commands:
        return err(f"Command '{command}' is not valid for device type '{slug}'")

    # Special handling: sync_schedules — auto-fetch feeder schedules
    if command == "sync_schedules" and slug == "automatic_feeder":
        try:
            cfg = sb.table("feeder_configurations").select("id").eq("device_id", device_id).execute()
            if cfg.data:
                scheds = sb.table("feeding_schedules") \
                    .select("feeding_time, target_grams, enabled") \
                    .eq("feeder_config_id", cfg.data[0]["id"]) \
                    .execute()
                params["schedules"] = scheds.data or []
        except Exception as e:
            logger.warning("Could not fetch schedules for sync: %s", e)

    # Publish via MQTT
    command_id = cmd_module.publish_command(
        mqtt_client.get_client(), serial_number, command, params
    )

    # Store command info so dispatch_ack() can correlate the ACK with its command
    # (used to record manual_dispense feeding events when dispense_food ACK arrives)
    mqtt_client.pending_commands[command_id] = {
        "command":       command,
        "serial_number": serial_number,
        "params":        params,
    }

    if not mqtt_client.is_connected():
        return ok({
            "command_id": command_id,
            "queued":     False,
            "warning":    "MQTT not connected — command could not be delivered",
        })

    return ok({
        "command_id": command_id,
        "queued":     True,
        "topic":      f"smartpethome/devices/{serial_number}/command",
    })


@api_bp.route("/devices/<device_id>/ack/<command_id>")
@api_auth
def get_ack(device_id, command_id):
    """Poll for a command acknowledgement from in-memory ack_store."""
    ack = mqtt_client.ack_store.get(command_id)
    if ack:
        return ok(ack)
    return ok({"command_id": command_id, "status": "pending"})


# ── Dashboard Summary ─────────────────────────────────────────

@api_bp.route("/dashboard/summary")
@api_auth
def dashboard_summary():
    sb  = get_supabase_with_session()
    uid = current_user_id()

    # Each query is wrapped independently so one failure never blocks the others.

    try:
        _r = sb.table("pets").select("id", count="exact").eq("owner_id", uid).execute()
        total_pets = _r.count or 0
    except Exception:
        total_pets = 0

    try:
        _r = sb.table("devices").select("id", count="exact").eq("owner_id", uid).execute()
        total_devices = _r.count or 0
    except Exception:
        total_devices = 0

    try:
        _r = (sb.table("alerts").select("id", count="exact")
              .eq("owner_id", uid).is_("resolved_at", "null").execute())
        total_alerts = _r.count or 0
    except Exception:
        total_alerts = 0

    try:
        _r = (sb.table("alerts").select("title,severity,created_at,alert_type")
              .eq("owner_id", uid).is_("resolved_at", "null")
              .order("created_at", desc=True).limit(5).execute())
        recent_alerts = _r.data or []
    except Exception:
        recent_alerts = []

    try:
        # Fetch extra rows, then filter to only meaningful event-type rows.
        # Normal periodic telemetry rows have no event_type in metadata.
        _r = (sb.table("feeding_events")
              .select("created_at,dispensed_grams,status_color,metadata,device_id")
              .eq("owner_id", uid)
              .order("created_at", desc=True).limit(50).execute())
        recent_feedings = [
            f for f in (_r.data or [])
            if (f.get("metadata") or {}).get("event_type")
        ][:5]
    except Exception:
        recent_feedings = []

    try:
        _r = (sb.table("devices")
              .select("id,device_name,status,last_seen_at,device_types(slug,name)")
              .eq("owner_id", uid).order("device_name").execute())
        device_statuses = _r.data or []
    except Exception:
        device_statuses = []

    return ok({
        "total_pets":      total_pets,
        "total_devices":   total_devices,
        "total_alerts":    total_alerts,
        "recent_alerts":   recent_alerts,
        "recent_feedings": recent_feedings,   # already a plain list — no .data
        "device_statuses": device_statuses,
        "mqtt_connected":  mqtt_client.is_connected(),
    })


# ── Alerts ────────────────────────────────────────────────────

@api_bp.route("/alerts")
@api_auth
def get_alerts():
    sb  = get_supabase_with_session()
    uid = current_user_id()
    resolved = request.args.get("resolved", "false").lower() == "true"
    try:
        q = (
            sb.table("alerts")
            .select("*, devices(device_name, serial_number)")
            .eq("owner_id", uid)
            .order("created_at", desc=True)
            .limit(50)
        )
        if resolved:
            q = q.not_.is_("resolved_at", "null")
        else:
            q = q.is_("resolved_at", "null")
        return ok(q.execute().data or [])
    except Exception as e:
        return err(str(e))


@api_bp.route("/alerts/<alert_id>/read", methods=["POST"])
@api_auth
def alert_read(alert_id):
    sb  = get_supabase_with_session()
    uid = current_user_id()
    try:
        sb.table("alerts").update({"is_read": True}).eq("id", alert_id).eq("owner_id", uid).execute()
        return ok({"updated": True})
    except Exception as e:
        return err(str(e))


@api_bp.route("/alerts/<alert_id>/resolve", methods=["POST"])
@api_auth
def alert_resolve(alert_id):
    from datetime import datetime, timezone
    sb  = get_supabase_with_session()
    uid = current_user_id()
    try:
        sb.table("alerts").update({
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "is_read":     True,
        }).eq("id", alert_id).eq("owner_id", uid).execute()
        return ok({"updated": True})
    except Exception as e:
        return err(str(e))


@api_bp.route("/alerts/resolve-all", methods=["POST"])
@api_auth
def alert_resolve_all():
    from datetime import datetime, timezone
    sb  = get_supabase_with_session()
    uid = current_user_id()
    try:
        res = (sb.table("alerts")
               .update({"resolved_at": datetime.now(timezone.utc).isoformat(), "is_read": True})
               .eq("owner_id", uid)
               .is_("resolved_at", "null")
               .execute())
        count = len(res.data) if res.data else 0
        logger.info("Resolve-all: %d alerts resolved for user %s", count, uid)
        return ok({"resolved": count})
    except Exception as e:
        return err(str(e))


# ── Feeder ────────────────────────────────────────────────────

@api_bp.route("/feeders/<device_id>/settings", methods=["GET"])
@api_auth
def get_feeder_settings(device_id):
    sb  = get_supabase_with_session()
    uid = current_user_id()
    # Verify ownership
    try:
        d = sb.table("devices").select("id").eq("id", device_id).eq("owner_id", uid).single().execute()
        if not d.data:
            return err("Device not found", 404)
    except Exception:
        return err("Device not found", 404)

    cfg = sb.table("feeder_configurations").select("*").eq("device_id", device_id).execute()
    config = cfg.data[0] if cfg.data else None
    schedules = []
    if config:
        s = sb.table("feeding_schedules").select("*").eq("feeder_config_id", config["id"]).order("feeding_time").execute()
        schedules = s.data or []
    return ok({"config": config, "schedules": schedules})


@api_bp.route("/feeders/<device_id>/settings", methods=["POST"])
@api_auth
def save_feeder_settings(device_id):
    sb   = get_supabase_with_session()
    uid  = current_user_id()
    body = request.get_json(silent=True) or {}
    try:
        d = sb.table("devices").select("id").eq("id", device_id).eq("owner_id", uid).single().execute()
        if not d.data:
            return err("Device not found", 404)
    except Exception:
        return err("Device not found", 404)

    payload = {
        "device_id":                 device_id,
        "feeding_mode":              body.get("feeding_mode", "redistribute_daily_diet"),
        "daily_tolerance_grams":     float(body.get("daily_tolerance_grams", 10)),
        "low_food_threshold_grams":  float(body.get("low_food_threshold_grams", 100)),
    }
    existing = sb.table("feeder_configurations").select("id").eq("device_id", device_id).execute()
    if existing.data:
        sb.table("feeder_configurations").update(payload).eq("id", existing.data[0]["id"]).execute()
    else:
        sb.table("feeder_configurations").insert(payload).execute()
    return ok({"saved": True})


@api_bp.route("/feeders/<device_id>/schedules", methods=["POST"])
@api_auth
def add_feeder_schedule(device_id):
    sb   = get_supabase_with_session()
    uid  = current_user_id()
    body = request.get_json(silent=True) or {}
    try:
        d = sb.table("devices").select("id").eq("id", device_id).eq("owner_id", uid).single().execute()
        if not d.data:
            return err("Device not found", 404)
    except Exception:
        return err("Device not found", 404)

    cfg = sb.table("feeder_configurations").select("id").eq("device_id", device_id).execute()
    if not cfg.data:
        return err("Save feeder configuration first")

    res = sb.table("feeding_schedules").insert({
        "feeder_config_id": cfg.data[0]["id"],
        "feeding_time":     body.get("feeding_time"),
        "target_grams":     float(body.get("target_grams", 0)),
        "enabled":          bool(body.get("enabled", True)),
    }).execute()
    return ok(res.data[0] if res.data else {})


@api_bp.route("/feeders/<device_id>/schedules/<sched_id>", methods=["PATCH"])
@api_auth
def update_feeder_schedule(device_id, sched_id):
    sb   = get_supabase_with_session()
    uid  = current_user_id()
    body = request.get_json(silent=True) or {}
    update = {}
    if "feeding_time"  in body: update["feeding_time"]  = body["feeding_time"]
    if "target_grams"  in body: update["target_grams"]  = float(body["target_grams"])
    if "enabled"       in body: update["enabled"]        = bool(body["enabled"])
    if not update:
        return err("No valid fields")
    sb.table("feeding_schedules").update(update).eq("id", sched_id).execute()
    return ok({"updated": True})


@api_bp.route("/feeders/<device_id>/schedules/<sched_id>", methods=["DELETE"])
@api_auth
def delete_feeder_schedule(device_id, sched_id):
    sb = get_supabase_with_session()
    sb.table("feeding_schedules").delete().eq("id", sched_id).execute()
    return ok({"deleted": True})


# ── Locations ─────────────────────────────────────────────────

@api_bp.route("/locations", methods=["GET"])
@api_auth
def get_locations():
    sb  = get_supabase_with_session()
    uid = current_user_id()
    res = sb.table("locations").select("*").eq("owner_id", uid).order("name").execute()
    return ok(res.data or [])


@api_bp.route("/locations", methods=["POST"])
@api_auth
def create_location():
    sb   = get_supabase_with_session()
    uid  = current_user_id()
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return err("'name' is required")
    res = sb.table("locations").insert({
        "owner_id": uid,
        "name":     name,
        "notes":    body.get("notes") or None,
    }).execute()
    return ok(res.data[0] if res.data else {})


# ── Water Dispenser ───────────────────────────────────────────

@api_bp.route("/water/<device_id>/config", methods=["GET"])
@api_auth
def get_water_config(device_id):
    """
    Called by the ESP32 on boot (via sync_config command response or HTTP poll).
    Returns sensor calibration + refills_remaining.
    """
    sb  = get_supabase_with_session()
    uid = current_user_id()
    try:
        d = sb.table("devices").select("id").eq("id", device_id).eq("owner_id", uid).single().execute()
        if not d.data:
            return err("Device not found", 404)
    except Exception:
        return err("Device not found", 404)

    res = sb.table("water_configurations").select("*").eq("device_id", device_id).execute()
    cfg = res.data[0] if res.data else {}
    return ok({
        "dist_full_cm":       cfg.get("dist_full_cm",       3.0),
        "dist_empty_cm":      cfg.get("dist_empty_cm",      20.0),
        "low_threshold_pct":  cfg.get("low_threshold_pct",  25),
        "high_threshold_pct": cfg.get("high_threshold_pct", 80),
        "max_refills":        cfg.get("max_refills",         3),
        "refills_remaining":  cfg.get("refills_remaining",   3),
    })


@api_bp.route("/water/<device_id>/refills", methods=["PATCH"])
@api_auth
def update_refills(device_id):
    """
    Called by telemetry_handlers when a refill cycle completes —
    decrements refills_remaining in water_configurations.
    Returns the updated count.
    """
    sb  = get_supabase_with_session()
    uid = current_user_id()
    try:
        d = sb.table("devices").select("id").eq("id", device_id).eq("owner_id", uid).single().execute()
        if not d.data:
            return err("Device not found", 404)
    except Exception:
        return err("Device not found", 404)

    res = sb.table("water_configurations").select("*").eq("device_id", device_id).execute()
    if not res.data:
        return err("No water configuration found. Configure the device first.")

    cfg = res.data[0]
    current = cfg.get("refills_remaining", 0)
    new_val = max(0, current - 1)
    sb.table("water_configurations").update({"refills_remaining": new_val}).eq("id", cfg["id"]).execute()
    return ok({"refills_remaining": new_val, "max_refills": cfg.get("max_refills", 3)})