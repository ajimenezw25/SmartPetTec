"""
feeder.py
---------
Blueprint for the automatic feeder diet schedule page.

UI: one simple form — grams, feeding_time_1, feeding_time_2, enabled.
Storage: two rows in feeding_schedules (one per time slot), both with the
same target_grams value and the same enabled flag.
feeder_configurations is auto-created with defaults if missing so the user
never has to interact with diet-mode or threshold settings.

The backend scheduler (scheduler.py) reads feeding_schedules and fires
dispense_food MQTT commands at the configured times.
"""

import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from utils import login_required, get_supabase_with_session, current_user_id

logger = logging.getLogger(__name__)

feeder_bp = Blueprint("feeder", __name__, url_prefix="/feeder")


# ── Helpers ───────────────────────────────────────────────────

def _get_owned_feeder(sb, device_id: str, uid: str):
    """Return (device, error_str). Verifies ownership and device type."""
    try:
        res = (
            sb.table("devices")
            .select("*, device_types(slug, name), pets(name)")
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
    if (device.get("device_types") or {}).get("slug") != "automatic_feeder":
        return None, "This device is not an automatic feeder."
    return device, None


def _get_or_create_config(sb, device_id: str) -> dict | None:
    """
    Return the feeder_configurations row, creating one with defaults if absent.
    Returns None on error.
    """
    try:
        res = sb.table("feeder_configurations").select("*") \
            .eq("device_id", device_id).execute()
        if res.data:
            return res.data[0]
        # Auto-create with silent defaults — user never sees these values
        ins = sb.table("feeder_configurations").insert({
            "device_id":                device_id,
            "feeding_mode":             "redistribute_daily_diet",
            "daily_tolerance_grams":    10.0,
            "low_food_threshold_grams": 100.0,
        }).execute()
        return ins.data[0] if ins.data else None
    except Exception as e:
        logger.error("FEEDER config get/create failed — device=%s: %s", device_id, e)
        return None


def _load_schedule_pair(sb, config_id: str) -> tuple:
    """
    Return (sched1, sched2, grams, enabled) from the two schedule rows.
    sched1/sched2 may be None if not yet saved.
    grams/enabled come from the first row found, or defaults.
    """
    try:
        res = sb.table("feeding_schedules").select("*") \
            .eq("feeder_config_id", config_id) \
            .order("feeding_time") \
            .limit(2) \
            .execute()
        rows = res.data or []
    except Exception as e:
        logger.error("FEEDER schedule load failed — config=%s: %s", config_id, e)
        rows = []

    def _norm(row):
        if not row:
            return row
        from scheduler import _to_hhmm
        row = dict(row)
        row["feeding_time"] = _to_hhmm(row.get("feeding_time"))
        return row

    sched1  = _norm(rows[0] if len(rows) > 0 else None)
    sched2  = _norm(rows[1] if len(rows) > 1 else None)
    grams   = float((sched1 or {}).get("target_grams") or 0)
    enabled = bool((sched1 or {}).get("enabled", True))
    return sched1, sched2, grams, enabled


# ── Routes ────────────────────────────────────────────────────

@feeder_bp.route("/<device_id>", methods=["GET", "POST"])
@login_required
def settings(device_id):
    sb  = get_supabase_with_session()
    uid = current_user_id()

    device, err = _get_owned_feeder(sb, device_id, uid)
    if err:
        flash(err, "error")
        return redirect(url_for("devices.index"))

    config = _get_or_create_config(sb, device_id)
    if not config:
        flash("Could not load feeder configuration.", "error")
        return redirect(url_for("devices.index"))

    sched1, sched2, grams, enabled = _load_schedule_pair(sb, config["id"])

    if request.method == "POST":
        # Parse form
        raw_time1 = request.form.get("feeding_time_1", "").strip()
        raw_time2 = request.form.get("feeding_time_2", "").strip()
        new_enabled = request.form.get("enabled") == "on"
        try:
            new_grams = float(request.form.get("grams", 0))
        except ValueError:
            flash("Grams must be a number.", "error")
            return redirect(url_for("feeder.settings", device_id=device_id))

        if not raw_time1 and not raw_time2:
            flash("Set at least one feeding time.", "error")
            return redirect(url_for("feeder.settings", device_id=device_id))
        if new_grams <= 0:
            flash("Grams must be greater than zero.", "error")
            return redirect(url_for("feeder.settings", device_id=device_id))

        # Delete all existing schedule rows for this config, then re-insert
        try:
            sb.table("feeding_schedules").delete() \
                .eq("feeder_config_id", config["id"]).execute()
        except Exception as e:
            logger.error("FEEDER schedule delete failed — config=%s: %s", config["id"], e)
            flash("Could not update schedule.", "error")
            return redirect(url_for("feeder.settings", device_id=device_id))

        rows_to_insert = []
        if raw_time1:
            rows_to_insert.append({
                "feeder_config_id": config["id"],
                "feeding_time":     raw_time1,
                "target_grams":     new_grams,
                "enabled":          new_enabled,
            })
        if raw_time2:
            rows_to_insert.append({
                "feeder_config_id": config["id"],
                "feeding_time":     raw_time2,
                "target_grams":     new_grams,
                "enabled":          new_enabled,
            })

        try:
            if rows_to_insert:
                sb.table("feeding_schedules").insert(rows_to_insert).execute()
            logger.info("FEEDER schedule saved — device=%s times=[%s,%s] grams=%.1f enabled=%s",
                        device_id, raw_time1, raw_time2, new_grams, new_enabled)
            flash("Feeding schedule saved.", "success")
        except Exception as e:
            logger.error("FEEDER schedule insert failed — device=%s: %s", device_id, e)
            flash("Could not save feeding schedule.", "error")

        return redirect(url_for("feeder.settings", device_id=device_id))

    import scheduler as sched_mod
    sched_status = sched_mod.get_status()

    return render_template(
        "feeder_settings.html",
        device       = device,
        sched1       = sched1,
        sched2       = sched2,
        grams        = grams,
        enabled      = enabled,
        sched_status = sched_status,
    )


@feeder_bp.route("/<device_id>/test-feeding", methods=["POST"])
@login_required
def test_feeding(device_id):
    """Test button: fire a scheduled dispense_food immediately."""
    import scheduler as sched_mod

    sb  = get_supabase_with_session()
    uid = current_user_id()

    device, err = _get_owned_feeder(sb, device_id, uid)
    if err:
        return jsonify({"ok": False, "error": err}), 403

    config = _get_or_create_config(sb, device_id)
    if not config:
        flash("Could not load feeder configuration.", "error")
        return redirect(url_for("feeder.settings", device_id=device_id))

    _, _, grams, _ = _load_schedule_pair(sb, config["id"])
    if grams <= 0:
        flash("Set a grams value and save the schedule first.", "error")
        return redirect(url_for("feeder.settings", device_id=device_id))

    serial   = device.get("serial_number", "")
    owner_id = device.get("owner_id", "")

    success = sched_mod.execute_feeder(device_id, serial, owner_id, grams)
    if success:
        flash(f"Test feeding command sent to {serial} ({grams:.0f} g). Check your device and alerts.", "success")
    else:
        flash("Test feeding failed — MQTT not connected. Is the backend running?", "error")

    return redirect(url_for("feeder.settings", device_id=device_id))


# ── Legacy route stubs (redirect to settings) ─────────────────
# Kept so any cached bookmarks don't produce 404s.

@feeder_bp.route("/<device_id>/schedule/<sched_id>/edit", methods=["GET", "POST"])
@login_required
def edit_schedule(device_id, sched_id):
    return redirect(url_for("feeder.settings", device_id=device_id))


@feeder_bp.route("/<device_id>/schedule/<sched_id>/delete", methods=["POST"])
@login_required
def delete_schedule(device_id, sched_id):
    return redirect(url_for("feeder.settings", device_id=device_id))


@feeder_bp.route("/<device_id>/schedule/<sched_id>/toggle", methods=["POST"])
@login_required
def toggle_schedule(device_id, sched_id):
    return redirect(url_for("feeder.settings", device_id=device_id))
