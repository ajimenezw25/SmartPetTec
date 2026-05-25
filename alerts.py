"""
alerts.py
---------
Blueprint for the alerts page.
Telegram settings have been moved to profile.py.
"""

from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash
from utils import login_required, get_supabase_with_session, current_user_id

alerts_bp = Blueprint("alerts", __name__, url_prefix="/alerts")


@alerts_bp.route("/")
@login_required
def index():
    sb  = get_supabase_with_session()
    uid = current_user_id()

    unresolved_res = (
        sb.table("alerts")
        .select("*, devices(device_name, serial_number)")
        .eq("owner_id", uid)
        .is_("resolved_at", "null")
        .order("created_at", desc=True)
        .execute()
    )

    resolved_res = (
        sb.table("alerts")
        .select("*, devices(device_name, serial_number)")
        .eq("owner_id", uid)
        .not_.is_("resolved_at", "null")
        .order("resolved_at", desc=True)
        .limit(20)
        .execute()
    )

    profile_res = (
        sb.table("profiles")
        .select("display_name, telegram_chat_id")
        .eq("id", uid)
        .single()
        .execute()
    )

    return render_template(
        "alerts.html",
        unresolved = unresolved_res.data or [],
        resolved   = resolved_res.data or [],
        profile    = profile_res.data or {},
    )


@alerts_bp.route("/<alert_id>/resolve", methods=["POST"])
@login_required
def resolve(alert_id):
    sb  = get_supabase_with_session()
    uid = current_user_id()
    try:
        sb.table("alerts").update({
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "is_read":     True,
        }).eq("id", alert_id).eq("owner_id", uid).execute()
        flash("Alert marked as resolved.", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("alerts.index"))


@alerts_bp.route("/<alert_id>/read", methods=["POST"])
@login_required
def mark_read(alert_id):
    sb  = get_supabase_with_session()
    uid = current_user_id()
    try:
        sb.table("alerts").update({"is_read": True}).eq("id", alert_id).eq("owner_id", uid).execute()
        flash("Alert marked as read.", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("alerts.index"))
