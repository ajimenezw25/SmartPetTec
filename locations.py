"""
locations.py
------------
Blueprint for location management (Living Room, Kennel, Backyard, etc.)
Locations are used when assigning non-pet devices to a physical space.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from utils import login_required, get_supabase_with_session, current_user_id

locations_bp = Blueprint("locations", __name__, url_prefix="/locations")


@locations_bp.route("/")
@login_required
def index():
    sb  = get_supabase_with_session()
    uid = current_user_id()
    try:
        res = sb.table("locations").select("*").eq("owner_id", uid).order("name").execute()
        locations = res.data or []
    except Exception as e:
        flash(f"Could not load locations: {e}", "error")
        locations = []
    return render_template("locations.html", locations=locations)


@locations_bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    if request.method == "POST":
        sb    = get_supabase_with_session()
        uid   = current_user_id()
        name  = request.form.get("name", "").strip()
        notes = request.form.get("notes", "").strip() or None

        if not name:
            flash("Location name is required.", "error")
            return render_template("location_form.html", location=None)
        try:
            sb.table("locations").insert({"owner_id": uid, "name": name, "notes": notes}).execute()
            flash(f"Location '{name}' created.", "success")
            return redirect(url_for("locations.index"))
        except Exception as e:
            flash(f"Error creating location: {e}", "error")
    return render_template("location_form.html", location=None)


@locations_bp.route("/<loc_id>/edit", methods=["GET", "POST"])
@login_required
def edit(loc_id):
    sb  = get_supabase_with_session()
    uid = current_user_id()
    try:
        res      = sb.table("locations").select("*").eq("id", loc_id).eq("owner_id", uid).single().execute()
        location = res.data
    except Exception:
        location = None
    if not location:
        flash("Location not found.", "error")
        return redirect(url_for("locations.index"))

    if request.method == "POST":
        name  = request.form.get("name", "").strip()
        notes = request.form.get("notes", "").strip() or None
        if not name:
            flash("Name is required.", "error")
            return render_template("location_form.html", location=location)
        try:
            sb.table("locations").update({"name": name, "notes": notes}).eq("id", loc_id).eq("owner_id", uid).execute()
            flash("Location updated.", "success")
            return redirect(url_for("locations.index"))
        except Exception as e:
            flash(f"Error: {e}", "error")
    return render_template("location_form.html", location=location)


@locations_bp.route("/<loc_id>/delete", methods=["POST"])
@login_required
def delete(loc_id):
    sb  = get_supabase_with_session()
    uid = current_user_id()
    try:
        sb.table("locations").delete().eq("id", loc_id).eq("owner_id", uid).execute()
        flash("Location removed.", "success")
    except Exception as e:
        flash(f"Could not delete: {e}", "error")
    return redirect(url_for("locations.index"))
