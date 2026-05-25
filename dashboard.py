"""
dashboard.py
------------
Main dashboard shown after login.
Displays summary counts and the most recent events.
"""

from flask import Blueprint, render_template, session
from utils import login_required, get_supabase_with_session, current_user_id

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@login_required
def index():
    sb      = get_supabase_with_session()
    uid     = current_user_id()

    # ── Counts ──────────────────────────────────────────────
    pets_res    = sb.table("pets").select("id", count="exact").eq("owner_id", uid).execute()
    devices_res = sb.table("devices").select("id", count="exact").eq("owner_id", uid).execute()
    alerts_res  = (
        sb.table("alerts")
        .select("id", count="exact")
        .eq("owner_id", uid)
        .is_("resolved_at", "null")
        .execute()
    )

    total_pets    = pets_res.count    or 0
    total_devices = devices_res.count or 0
    total_alerts  = alerts_res.count  or 0

    # ── Recent feeding events (last 5) ─────────────────────
    feeding_res = (
        sb.table("feeding_events")
        .select("created_at, dispensed_grams, status_color, device_id")
        .eq("owner_id", uid)
        .order("created_at", desc=True)
        .limit(5)
        .execute()
    )

    # ── Recent alerts (last 5, unresolved) ─────────────────
    recent_alerts_res = (
        sb.table("alerts")
        .select("title, severity, created_at")
        .eq("owner_id", uid)
        .is_("resolved_at", "null")
        .order("created_at", desc=True)
        .limit(5)
        .execute()
    )

    return render_template(
        "dashboard.html",
        total_pets     = total_pets,
        total_devices  = total_devices,
        total_alerts   = total_alerts,
        feeding_events = feeding_res.data or [],
        recent_alerts  = recent_alerts_res.data or [],
    )
