"""
profile.py
----------
User profile/settings routes.
Handles display name and Telegram phone number settings.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from utils import login_required, get_supabase_with_session, current_user_id

profile_bp = Blueprint("profile", __name__, url_prefix="/profile")


@profile_bp.route("/", methods=["GET", "POST"])
@profile_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    sb = get_supabase_with_session()
    uid = current_user_id()

    try:
        profile_res = (
            sb.table("profiles")
            .select("*")
            .eq("id", uid)
            .single()
            .execute()
        )
        profile = profile_res.data or {}
    except Exception:
        profile = {}

    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()

        telegram_phone = (
            request.form.get("telegram_chat_id", "").strip()
            or request.form.get("phone_number", "").strip()
        )

        if not display_name:
            flash("Display name is required.", "error")
            return render_template("profile.html", profile=profile)

        try:
            sb.table("profiles").update({
                "display_name": display_name,
                "telegram_chat_id": telegram_phone or None,
            }).eq("id", uid).execute()

            session["display_name"] = display_name

            flash("Profile updated successfully.", "success")
            return redirect(url_for("profile.settings"))

        except Exception as e:
            flash(f"Error updating profile: {e}", "error")

    return render_template("profile.html", profile=profile)


@profile_bp.route("/telegram", methods=["GET", "POST"])
@login_required
def telegram():
    sb  = get_supabase_with_session()
    uid = current_user_id()

    try:
        profile_res = sb.table("profiles").select("telegram_chat_id").eq("id", uid).single().execute()
        profile = profile_res.data or {}
    except Exception:
        profile = {}

    if request.method == "POST":
        chat_id = request.form.get("telegram_chat_id", "").strip()
        try:
            sb.table("profiles").update({"telegram_chat_id": chat_id or None}).eq("id", uid).execute()
            flash("Telegram Chat ID saved. You will now receive alert notifications.", "success")
        except Exception as e:
            flash(f"Error saving: {e}", "error")
        return redirect(url_for("profile.telegram"))

    return render_template("telegram_config.html", profile=profile)