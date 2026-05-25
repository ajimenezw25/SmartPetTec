"""
history.py
----------
Blueprint for the event history page.
Displays feeding_events, motion_events, environmental_events, and alerts.
Supports optional filtering by device_id via query string.
"""

from flask import Blueprint, render_template, request
from utils import login_required, get_supabase_with_session, current_user_id

history_bp = Blueprint("history", __name__, url_prefix="/history")


@history_bp.route("/")
@login_required
def index():
    sb         = get_supabase_with_session()
    uid        = current_user_id()
    device_id  = request.args.get("device_id", "").strip() or None
    limit      = 30  # rows per event type

    # ── Available devices for the filter dropdown ───────────
    devices_res = (
        sb.table("devices")
        .select("id, device_name, serial_number")
        .eq("owner_id", uid)
        .order("device_name")
        .execute()
    )

    def apply_device_filter(query):
        if device_id:
            return query.eq("device_id", device_id)
        return query

    # ── Feeding events ───────────────────────────────────────
    q = (
        sb.table("feeding_events")
        .select("created_at, dispensed_grams, consumed_grams, status_color, device_id, devices(device_name)")
        .eq("owner_id", uid)
        .order("created_at", desc=True)
        .limit(limit)
    )
    feeding_res = apply_device_filter(q).execute()

    # ── Motion events ────────────────────────────────────────
    q = (
        sb.table("motion_events")
        .select("detected_at, created_at, device_id, devices(device_name)")
        .eq("owner_id", uid)
        .order("detected_at", desc=True)
        .limit(limit)
    )
    motion_res = apply_device_filter(q).execute()

    # ── Environmental events ─────────────────────────────────
    q = (
        sb.table("environmental_events")
        .select("created_at, temperature, status, actuator_triggered, device_id, devices(device_name)")
        .eq("owner_id", uid)
        .order("created_at", desc=True)
        .limit(limit)
    )
    env_res = apply_device_filter(q).execute()

    # ── Alert history ────────────────────────────────────────
    q = (
        sb.table("alerts")
        .select("created_at, title, severity, alert_type, is_read, resolved_at, device_id, devices(device_name)")
        .eq("owner_id", uid)
        .order("created_at", desc=True)
        .limit(limit)
    )
    alerts_res = apply_device_filter(q).execute()

    return render_template(
        "history.html",
        devices             = devices_res.data or [],
        selected_device_id  = device_id,
        feeding_events      = feeding_res.data or [],
        motion_events       = motion_res.data or [],
        env_events          = env_res.data or [],
        alerts              = alerts_res.data or [],
    )
