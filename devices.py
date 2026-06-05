"""
devices.py
----------
Device management routes:
- list devices
- register device
- assign device to pet/location
- delete device
- command center detail page
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from utils import login_required, get_supabase_with_session, current_user_id
from config import supabase_admin

devices_bp = Blueprint("devices", __name__, url_prefix="/devices")


@devices_bp.route("/")
@login_required
def index():
    """List all devices owned by the logged-in user."""
    sb = get_supabase_with_session()
    uid = current_user_id()

    try:
        res = (
            sb.table("devices")
            .select("*, device_types(slug, name), pets(name), locations(name)")
            .eq("owner_id", uid)
            .order("device_name")
            .execute()
        )
        devices = res.data or []
    except Exception as e:
        flash(f"Error loading devices: {e}", "error")
        devices = []

    return render_template("devices.html", devices=devices)


@devices_bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    """Register a new device."""
    sb = get_supabase_with_session()
    uid = current_user_id()

    try:
        device_types_res = (
            sb.table("device_types")
            .select("*")
            .order("name")
            .execute()
        )
        device_types = device_types_res.data or []

        pets_res = (
            sb.table("pets")
            .select("id, name")
            .eq("owner_id", uid)
            .order("name")
            .execute()
        )
        pets = pets_res.data or []

        locations_res = (
            sb.table("locations")
            .select("id, name")
            .eq("owner_id", uid)
            .order("name")
            .execute()
        )
        locations = locations_res.data or []

    except Exception as e:
        flash(f"Error loading form data: {e}", "error")
        device_types = []
        pets = []
        locations = []

    if request.method == "POST":
        device_name = request.form.get("device_name", "").strip()
        serial_number = request.form.get("serial_number", "").strip()
        device_type_id = request.form.get("device_type_id")
        pet_id = request.form.get("pet_id") or None
        location_id = request.form.get("location_id") or None

        if not device_name or not serial_number or not device_type_id:
            flash("Device name, serial number, and device type are required.", "error")
            return render_template(
                "device_form.html",
                device=None,
                device_types=device_types,
                pets=pets,
                locations=locations,
            )

        selected_type = None
        for dt in device_types:
            if str(dt.get("id")) == str(device_type_id):
                selected_type = dt
                break

        selected_slug = selected_type.get("slug") if selected_type else ""

        if selected_slug == "automatic_feeder" and not pet_id:
            flash("Automatic feeders must be assigned to a pet.", "error")
            return render_template(
                "device_form.html",
                device=None,
                device_types=device_types,
                pets=pets,
                locations=locations,
            )

        # Check for duplicate serial number across all users (bypasses RLS)
        try:
            dup = (supabase_admin.table("devices")
                   .select("id")
                   .eq("serial_number", serial_number)
                   .limit(1)
                   .execute())
            if dup.data:
                flash(
                    "This serial number is already registered. "
                    "Please check the device serial or contact support.",
                    "error",
                )
                return render_template(
                    "device_form.html",
                    device=None,
                    device_types=device_types,
                    pets=pets,
                    locations=locations,
                )
        except Exception:
            pass  # If the check itself fails, proceed and let the insert catch the constraint

        try:
            sb.table("devices").insert({
                "owner_id": uid,
                "device_type_id": int(device_type_id),
                "device_name": device_name,
                "serial_number": serial_number,
                "pet_id": pet_id,
                "location_id": location_id,
                "status": "offline",
                "is_active": True,
            }).execute()

            flash("Device registered successfully.", "success")
            return redirect(url_for("devices.index"))

        except Exception as e:
            err_str = str(e).lower()
            if "unique" in err_str or "duplicate" in err_str or "serial_number" in err_str:
                flash(
                    "This serial number is already registered. "
                    "Please check the device serial or contact support.",
                    "error",
                )
            else:
                flash("Error registering device. Please try again.", "error")

    return render_template(
        "device_form.html",
        device=None,
        device_types=device_types,
        pets=pets,
        locations=locations,
    )


@devices_bp.route("/<device_id>/assign", methods=["GET", "POST"])
@login_required
def assign(device_id):
    """Assign an existing device to a pet or location."""
    sb = get_supabase_with_session()
    uid = current_user_id()

    try:
        device_res = (
            sb.table("devices")
            .select("*, device_types(slug, name), pets(name), locations(name)")
            .eq("id", device_id)
            .eq("owner_id", uid)
            .single()
            .execute()
        )
        device = device_res.data

        if not device:
            flash("Device not found.", "error")
            return redirect(url_for("devices.index"))

        pets_res = (
            sb.table("pets")
            .select("id, name")
            .eq("owner_id", uid)
            .order("name")
            .execute()
        )
        pets = pets_res.data or []

        locations_res = (
            sb.table("locations")
            .select("id, name")
            .eq("owner_id", uid)
            .order("name")
            .execute()
        )
        locations = locations_res.data or []

    except Exception as e:
        flash(f"Error loading device assignment: {e}", "error")
        return redirect(url_for("devices.index"))

    if request.method == "POST":
        pet_id = request.form.get("pet_id") or None
        location_id = request.form.get("location_id") or None

        slug = (device.get("device_types") or {}).get("slug", "")

        if slug == "automatic_feeder" and not pet_id:
            flash("Automatic feeders must be assigned to a pet.", "error")
            return render_template(
                "device_assignment.html",
                device=device,
                pets=pets,
                locations=locations,
            )

        try:
            sb.table("devices").update({
                "pet_id": pet_id,
                "location_id": location_id,
            }).eq("id", device_id).eq("owner_id", uid).execute()

            flash("Device assignment updated.", "success")
            return redirect(url_for("devices.index"))

        except Exception as e:
            flash(f"Error assigning device: {e}", "error")

    return render_template(
        "device_assignment.html",
        device=device,
        pets=pets,
        locations=locations,
    )


@devices_bp.route("/<device_id>/delete", methods=["POST"])
@login_required
def delete(device_id):
    """Delete a device owned by the logged-in user."""
    sb = get_supabase_with_session()
    uid = current_user_id()

    try:
        sb.table("devices").delete().eq("id", device_id).eq("owner_id", uid).execute()
        flash("Device deleted.", "success")
    except Exception as e:
        flash(f"Error deleting device: {e}", "error")

    return redirect(url_for("devices.index"))


@devices_bp.route("/<device_id>/detail")
@login_required
def detail(device_id):
    """Device command center page."""
    sb = get_supabase_with_session()
    uid = current_user_id()

    try:
        res = (
            sb.table("devices")
            .select("*, device_types(slug, name), pets(name), locations(name)")
            .eq("id", device_id)
            .eq("owner_id", uid)
            .single()
            .execute()
        )
        device = res.data
    except Exception:
        device = None

    if not device:
        flash("Device not found.", "error")
        return redirect(url_for("devices.index"))

    return render_template("device_detail.html", device=device)
    