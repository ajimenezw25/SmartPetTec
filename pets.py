"""
pets.py
-------
Blueprint for pet management: list, create, edit, delete.

KEY CHANGES from original:
  - owner_id is always sourced from current_user_id() (Flask session).
    It is never taken from the form or the URL — users cannot spoof it.
  - Errors are caught individually so the user gets a useful message
    instead of a raw Postgres exception.
  - The FK error (23503) is caught and surfaced as a plain English message
    so it's obvious when the profiles row is still missing.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from utils import login_required, get_supabase_with_session, current_user_id

pets_bp = Blueprint("pets", __name__, url_prefix="/pets")


@pets_bp.route("/")
@login_required
def index():
    sb  = get_supabase_with_session()
    uid = current_user_id()
    try:
        res = sb.table("pets").select("*").eq("owner_id", uid).order("name").execute()
        pets = res.data or []
    except Exception as e:
        flash(f"Could not load pets: {e}", "error")
        pets = []
    return render_template("pets.html", pets=pets)


@pets_bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    if request.method == "POST":
        sb  = get_supabase_with_session()
        uid = current_user_id()

        # Guard: should never be empty at this point because login_required
        # ran, but we check explicitly to give a clear error.
        if not uid:
            flash("Session expired. Please log in again.", "error")
            return redirect(url_for("auth.login"))

        name       = request.form.get("name", "").strip()
        species    = request.form.get("species", "").strip()
        breed      = request.form.get("breed", "").strip() or None
        birth_date = request.form.get("birth_date", "").strip() or None
        notes      = request.form.get("notes", "").strip() or None

        if not name or not species:
            flash("Name and species are required.", "error")
            return render_template("pet_form.html", pet=None)

        try:
            sb.table("pets").insert({
                "owner_id":   uid,   # Always the session user — never from the form
                "name":       name,
                "species":    species,
                "breed":      breed,
                "birth_date": birth_date,
                "notes":      notes,
            }).execute()
            flash(f"Pet '{name}' registered successfully!", "success")
            return redirect(url_for("pets.index"))

        except Exception as e:
            error_str = str(e)
            # FK violation means the profiles row doesn't exist yet
            if "23503" in error_str or "pets_owner_id_fkey" in error_str:
                flash(
                    "Your user profile is not set up yet. "
                    "Please log out, log back in, and try again. "
                    "If the problem persists, contact support.",
                    "error"
                )
            # RLS violation
            elif "42501" in error_str:
                flash(
                    "Permission denied. Make sure you are logged in "
                    "and your session is valid.",
                    "error"
                )
            else:
                flash(f"Error saving pet: {error_str}", "error")

    return render_template("pet_form.html", pet=None)


@pets_bp.route("/<pet_id>/edit", methods=["GET", "POST"])
@login_required
def edit(pet_id):
    sb  = get_supabase_with_session()
    uid = current_user_id()

    # Fetch pet — the .eq("owner_id", uid) means users can't edit others' pets
    try:
        res = (
            sb.table("pets").select("*")
            .eq("id", pet_id)
            .eq("owner_id", uid)
            .single()
            .execute()
        )
        pet = res.data
    except Exception:
        pet = None

    if not pet:
        flash("Pet not found or you don't have permission to edit it.", "error")
        return redirect(url_for("pets.index"))

    if request.method == "POST":
        name       = request.form.get("name", "").strip()
        species    = request.form.get("species", "").strip()
        breed      = request.form.get("breed", "").strip() or None
        birth_date = request.form.get("birth_date", "").strip() or None
        notes      = request.form.get("notes", "").strip() or None

        if not name or not species:
            flash("Name and species are required.", "error")
            return render_template("pet_form.html", pet=pet)

        try:
            sb.table("pets").update({
                "name":       name,
                "species":    species,
                "breed":      breed,
                "birth_date": birth_date,
                "notes":      notes,
                # owner_id is NOT updated — it can never change
            }).eq("id", pet_id).eq("owner_id", uid).execute()
            flash(f"Pet '{name}' updated.", "success")
            return redirect(url_for("pets.index"))
        except Exception as e:
            flash(f"Error updating pet: {e}", "error")

    return render_template("pet_form.html", pet=pet)


@pets_bp.route("/<pet_id>/delete", methods=["POST"])
@login_required
def delete(pet_id):
    sb  = get_supabase_with_session()
    uid = current_user_id()
    try:
        sb.table("pets").delete().eq("id", pet_id).eq("owner_id", uid).execute()
        flash("Pet removed.", "success")
    except Exception as e:
        flash(f"Could not delete pet: {e}", "error")
    return redirect(url_for("pets.index"))
