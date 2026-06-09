"""
door.py
-------
Blueprint for automatic_access_door schedule management.

Route: /door/<device_id>

Stores one schedule row per door device in the door_schedules table.
The backend scheduler (scheduler.py) reads last_open_run_date and
last_close_run_date to avoid re-firing on the same day.
"""

import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from utils import login_required, get_supabase_with_session, current_user_id

logger = logging.getLogger(__name__)

door_bp = Blueprint("door", __name__, url_prefix="/door")


def _get_owned_door(sb, device_id: str, uid: str):
    """Fetch device, verify ownership and type. Returns (device, error_str)."""
    try:
        res = (
            sb.table("devices")
            .select("*, device_types(slug, name)")
            .eq("id", device_id)
            .eq("owner_id", uid)
            .single()
            .execute()
        )
        device = res.data
    except Exception:
        return None, "Device not found."

    if not device:
        return None, "Device not found."
    if (device.get("device_types") or {}).get("slug") != "automatic_access_door":
        return None, "This device is not an automatic access door."
    return device, None


@door_bp.route("/<device_id>", methods=["GET", "POST"])
@login_required
def schedule(device_id):
    sb  = get_supabase_with_session()
    uid = current_user_id()

    device, err = _get_owned_door(sb, device_id, uid)
    if err:
        flash(err, "error")
        return redirect(url_for("devices.index"))

    # Load the existing schedule for this device+owner (one row per device)
    door_sched    = None
    table_missing = False
    try:
        res = (
            sb.table("door_schedules")
            .select("*")
            .eq("device_id", device_id)
            .eq("owner_id", uid)
            .limit(1)
            .execute()
        )
        door_sched = res.data[0] if res.data else None
        if door_sched:
            from scheduler import _to_hhmm
            door_sched = dict(door_sched)
            door_sched["open_time"]  = _to_hhmm(door_sched.get("open_time"))
            door_sched["close_time"] = _to_hhmm(door_sched.get("close_time"))
        logger.debug("DOOR schedule loaded — device=%s exists=%s", device_id, door_sched is not None)
    except Exception as e:
        err_str = str(e).lower()
        if "does not exist" in err_str or "relation" in err_str or "42p01" in err_str:
            table_missing = True
        else:
            flash("Could not load door schedule.", "error")
            logger.error("DOOR schedule load error — device=%s: %s", device_id, e)

    if request.method == "POST":
        if table_missing:
            flash("Run the door_schedules SQL migration in Supabase first.", "error")
            return redirect(url_for("door.schedule", device_id=device_id))

        open_time  = request.form.get("open_time",  "").strip() or None
        close_time = request.form.get("close_time", "").strip() or None
        enabled    = request.form.get("enabled") == "on"

        if not open_time and not close_time:
            flash("Set at least one of Open Time or Close Time.", "error")
            return redirect(url_for("door.schedule", device_id=device_id))

        payload = {
            "device_id":  device_id,
            "owner_id":   uid,
            "open_time":  open_time,
            "close_time": close_time,
            "enabled":    enabled,
        }
        try:
            if door_sched:
                sb.table("door_schedules") \
                    .update(payload) \
                    .eq("id", door_sched["id"]) \
                    .execute()
            else:
                sb.table("door_schedules").insert(payload).execute()
            logger.info("DOOR schedule saved — device=%s open=%s close=%s enabled=%s",
                        device_id, open_time, close_time, enabled)
            flash("Door schedule saved.", "success")
        except Exception as e:
            logger.error("DOOR schedule save error — device=%s: %s", device_id, e)
            flash("Could not save door schedule.", "error")

        return redirect(url_for("door.schedule", device_id=device_id))

    import scheduler as sched_mod
    sched_status = sched_mod.get_status()

    return render_template(
        "door_schedule.html",
        device        = device,
        door_sched    = door_sched,
        table_missing = table_missing,
        sched_status  = sched_status,
    )


@door_bp.route("/<device_id>/test-action", methods=["POST"])
@login_required
def test_action(device_id):
    """Test button: fire a door action immediately via scheduler execute functions."""
    import scheduler as sched_mod

    sb  = get_supabase_with_session()
    uid = current_user_id()

    device, err = _get_owned_door(sb, device_id, uid)
    if err:
        return jsonify({"ok": False, "error": err}), 403

    action = request.form.get("action_type", "open_door")
    if action not in ("open_door", "close_door"):
        return jsonify({"ok": False, "error": "Invalid action"}), 400

    serial   = device.get("serial_number", "")
    owner_id = device.get("owner_id", "")

    success = sched_mod.execute_door_action(device_id, serial, owner_id, action)
    human   = "open" if action == "open_door" else "close"
    if success:
        flash(f"Test {human} command sent to {serial}. Check your device and alerts.", "success")
    else:
        flash(f"Test {human} failed — MQTT not connected. Is the backend running?", "error")

    return redirect(url_for("door.schedule", device_id=device_id))
