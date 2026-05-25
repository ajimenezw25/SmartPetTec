"""
profile.py
----------
Blueprint for user profile/settings management.

Handles:
  - Viewing and updating the user's display name
  - Storing a PHONE NUMBER for Telegram alert delivery

TELEGRAM PHONE NUMBER APPROACH (university prototype):
──────────────────────────────────────────────────────
Telegram's API requires a "chat_id" (a numeric ID) to send messages,
not a phone number. However, asking users to find their own chat_id
is confusing for non-technical users.

For this prototype we store the phone number the user provides in
the existing `telegram_chat_id` column (TEXT, so it accepts any string).
The field is relabelled in the UI as "Phone number for alerts".

In a future production version, a small bot flow would:
  1. User texts the bot from their phone number.
  2. The bot looks up the phone number in profiles and links the chat_id.
  3. The app sends alerts using the resolved chat_id.

For Sprint 1 the phone number is stored and displayed. The alert
delivery logic can be added later without any schema change.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from utils import login_required, get_supabase_with_session, current_user_id

profile_bp = Blueprint("profile", __name__, url_prefix="/profile")


@profile_bp.route("/", methods=["GET", "POST"])
@login_required
def settings():
    sb  = get_supabase_with_session()
    uid = current_user_id()

    # Load current profile
    try:
        res     = sb.table("profiles").select("*").eq("id", uid).single().execute()
        profile = res.data or {}
    except Exception as e:
        flash(f"Could not load profile: {e}", "error")
        profile = {}

    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()
        phone_number = request.form.get("phone_number", "").strip() or None

        if not display_name:
            flash("Display name is required.", "error")
            return render_template("profile.html", profile=profile)

        # Basic phone validation: allow +, digits, spaces, dashes
        if phone_number:
            import re
            cleaned = re.sub(r"[\s\-()]", "", phone_number)
            if not re.match(r"^\+?\d{7,15}$", cleaned):
                flash("Please enter a valid phone number (e.g. +506 8888 1234).", "error")
                return render_template("profile.html", profile=profile)

        try:
            sb.table("profiles").update({
                "display_name":     display_name,
                # We store the phone number in telegram_chat_id.
                # The column is TEXT so it accepts any format.
                # A future bot integration will resolve it to a real chat_id.
                "telegram_chat_id": phone_number,
            }).eq("id", uid).execute()

            # Keep display_name in session fresh
            session["display_name"] = display_name
            flash("Profile updated successfully.", "success")
            return redirect(url_for("profile.settings"))

        except Exception as e:
            flash(f"Error updating profile: {e}", "error")

    return render_template("profile.html", profile=profile)
