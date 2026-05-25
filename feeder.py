"""
feeder.py
---------
Blueprint for automatic feeder configuration and schedule management.

DIET MODE EXPLANATION:
──────────────────────
Two modes are supported in feeder_configurations.feeding_mode:

  1. complete_bowl
     The feeder dispenses food up to the bowl's maximum capacity each
     time a schedule fires, regardless of what is already in the bowl.
     Use case: pets that self-regulate and prefer a full bowl available
     at all times. The hardware will check the current weight sensor
     reading and top up the difference.

  2. redistribute_daily_diet
     A daily ration (target_grams × number of schedules) is calculated
     and spread across all enabled feeding times. If the pet did not eat
     at a previous meal (leftover detected), the next meal is reduced
     proportionally. The tolerance band (daily_tolerance_grams) defines
     how much variance is acceptable before triggering a yellow/red alert.
     Use case: weight-management diets, portion-controlled feeding.

Both modes write events to feeding_events. The status_color field
(green/yellow/red) is set by the hardware based on how closely actual
consumption matched the target, relative to the tolerance setting.

SCHEDULE FLOW:
  - The physical feeder polls feeding_schedules from Supabase via the API.
  - It fires a dispense action at each enabled feeding_time.
  - After dispensing it writes a feeding_event row with the result.
  - If food remaining drops below low_food_threshold_grams, the device
    creates a 'low_food' alert row in the alerts table.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from utils import login_required, get_supabase_with_session, current_user_id

feeder_bp = Blueprint("feeder", __name__, url_prefix="/feeder")


def _get_owned_feeder(sb, device_id, uid):
    """
    Fetch a device, verify it belongs to uid and is an automatic_feeder.
    Returns (device, error_message).
    """
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


def _load_config_and_schedules(sb, device_id):
    """Return (config_or_None, schedules_list)."""
    cfg_res = (
        sb.table("feeder_configurations")
        .select("*")
        .eq("device_id", device_id)
        .execute()
    )
    config = cfg_res.data[0] if cfg_res.data else None

    schedules = []
    if config:
        sched_res = (
            sb.table("feeding_schedules")
            .select("*")
            .eq("feeder_config_id", config["id"])
            .order("feeding_time")
            .execute()
        )
        schedules = sched_res.data or []

    return config, schedules


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

    config, schedules = _load_config_and_schedules(sb, device_id)

    if request.method == "POST":
        action = request.form.get("action", "")

        # ── Save diet mode + thresholds ──────────────────────
        if action == "save_config":
            feeding_mode  = request.form.get("feeding_mode", "redistribute_daily_diet")
            if feeding_mode not in ("complete_bowl", "redistribute_daily_diet"):
                flash("Invalid feeding mode.", "error")
                return redirect(url_for("feeder.settings", device_id=device_id))

            try:
                tolerance  = float(request.form.get("daily_tolerance_grams", 10))
                threshold  = float(request.form.get("low_food_threshold_grams", 100))
            except ValueError:
                flash("Tolerance and threshold must be numbers.", "error")
                return redirect(url_for("feeder.settings", device_id=device_id))

            if tolerance < 0 or threshold < 0:
                flash("Values cannot be negative.", "error")
                return redirect(url_for("feeder.settings", device_id=device_id))

            payload = {
                "device_id":                 device_id,
                "feeding_mode":              feeding_mode,
                "daily_tolerance_grams":     tolerance,
                "low_food_threshold_grams":  threshold,
            }
            try:
                if config:
                    sb.table("feeder_configurations").update(payload).eq("id", config["id"]).execute()
                else:
                    sb.table("feeder_configurations").insert(payload).execute()
                flash("Feeder configuration saved.", "success")
            except Exception as e:
                flash(f"Error saving configuration: {e}", "error")
            return redirect(url_for("feeder.settings", device_id=device_id))

        # ── Add new schedule ─────────────────────────────────
        if action == "add_schedule":
            if not config:
                flash("Save diet configuration first before adding schedules.", "warning")
                return redirect(url_for("feeder.settings", device_id=device_id))

            feeding_time = request.form.get("feeding_time", "").strip()
            enabled      = request.form.get("enabled") == "on"

            try:
                target_grams = float(request.form.get("target_grams", 0))
            except ValueError:
                flash("Target grams must be a number.", "error")
                return redirect(url_for("feeder.settings", device_id=device_id))

            if not feeding_time:
                flash("Feeding time is required.", "error")
                return redirect(url_for("feeder.settings", device_id=device_id))
            if target_grams <= 0:
                flash("Target grams must be greater than zero.", "error")
                return redirect(url_for("feeder.settings", device_id=device_id))

            try:
                sb.table("feeding_schedules").insert({
                    "feeder_config_id": config["id"],
                    "feeding_time":     feeding_time,
                    "target_grams":     target_grams,
                    "enabled":          enabled,
                }).execute()
                flash("Feeding schedule added.", "success")
            except Exception as e:
                flash(f"Error adding schedule: {e}", "error")
            return redirect(url_for("feeder.settings", device_id=device_id))

    return render_template(
        "feeder_settings.html",
        device    = device,
        config    = config,
        schedules = schedules,
    )


@feeder_bp.route("/<device_id>/schedule/<sched_id>/edit", methods=["GET", "POST"])
@login_required
def edit_schedule(device_id, sched_id):
    """Edit an existing feeding schedule entry."""
    sb  = get_supabase_with_session()
    uid = current_user_id()

    device, err = _get_owned_feeder(sb, device_id, uid)
    if err:
        flash(err, "error")
        return redirect(url_for("devices.index"))

    # Fetch the schedule row
    try:
        sres = sb.table("feeding_schedules").select("*").eq("id", sched_id).single().execute()
        schedule = sres.data
    except Exception:
        schedule = None

    if not schedule:
        flash("Schedule not found.", "error")
        return redirect(url_for("feeder.settings", device_id=device_id))

    if request.method == "POST":
        feeding_time = request.form.get("feeding_time", "").strip()
        enabled      = request.form.get("enabled") == "on"
        try:
            target_grams = float(request.form.get("target_grams", 0))
        except ValueError:
            flash("Target grams must be a number.", "error")
            return render_template("schedule_edit.html", device=device, schedule=schedule)

        if not feeding_time or target_grams <= 0:
            flash("Please provide a valid time and grams > 0.", "error")
            return render_template("schedule_edit.html", device=device, schedule=schedule)

        try:
            sb.table("feeding_schedules").update({
                "feeding_time": feeding_time,
                "target_grams": target_grams,
                "enabled":      enabled,
            }).eq("id", sched_id).execute()
            flash("Schedule updated.", "success")
            return redirect(url_for("feeder.settings", device_id=device_id))
        except Exception as e:
            flash(f"Error updating schedule: {e}", "error")

    return render_template("schedule_edit.html", device=device, schedule=schedule)


@feeder_bp.route("/<device_id>/schedule/<sched_id>/delete", methods=["POST"])
@login_required
def delete_schedule(device_id, sched_id):
    sb  = get_supabase_with_session()
    uid = current_user_id()
    device, err = _get_owned_feeder(sb, device_id, uid)
    if err:
        flash(err, "error")
        return redirect(url_for("devices.index"))
    try:
        sb.table("feeding_schedules").delete().eq("id", sched_id).execute()
        flash("Schedule removed.", "success")
    except Exception as e:
        flash(f"Error removing schedule: {e}", "error")
    return redirect(url_for("feeder.settings", device_id=device_id))


@feeder_bp.route("/<device_id>/schedule/<sched_id>/toggle", methods=["POST"])
@login_required
def toggle_schedule(device_id, sched_id):
    sb  = get_supabase_with_session()
    uid = current_user_id()
    device, err = _get_owned_feeder(sb, device_id, uid)
    if err:
        flash(err, "error")
        return redirect(url_for("devices.index"))
    try:
        res = sb.table("feeding_schedules").select("enabled").eq("id", sched_id).single().execute()
        if res.data:
            sb.table("feeding_schedules").update({"enabled": not res.data["enabled"]}).eq("id", sched_id).execute()
            flash("Schedule toggled.", "success")
    except Exception as e:
        flash(f"Error toggling schedule: {e}", "error")
    return redirect(url_for("feeder.settings", device_id=device_id))
