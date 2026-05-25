"""
devices.py
----------
Blueprint for device management:
  - List all devices with assignment status
  - Register a new device
  - Assign/reassign device to pet or location
  - Delete device

ASSIGNMENT RULES (enforced here + DB trigger):
  - automatic_feeder  → must have pet_id (cannot use location_id)
  - environmental_monitor → recommended for location, not enforced here
  - audio_communication → can use either
  - all others → either pet or location (optional)
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from utils import login_required, get_supabase_with_session, current_user_id

devices_bp = Blueprint("devices", __name__, url_prefix="/devices")

FEEDER_SLUG = "automatic_feeder"


def _load_device_types(sb):
    return sb.table("device_types").select("*").order("name").execute().data or []


def _load_user_pets(sb, uid):
    return sb.table("pets").select("id, name, species").eq("owner_id", uid).order("name").execute().data or []


def _load_user_locations(sb, uid):
    return sb.table("locations").select("id, name").eq("owner_id", uid).order("name").execute().data or []


def _is_feeder(device_types, device_type_id):
    """Return True if the given device_type_id maps to automatic_feeder."""
    for dt in device_types:
        if str(dt["id"]) == str(device_type_id) and dt["slug"] == FEEDER_SLUG:
            return True
    return False


@devices_bp.route("/")
@login_required
def index():
    sb  = get_supabase_with_session()
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
        flash(f"Could not load devices: {e}", "error")
        devices = []
    return render_template("devices.html", devices=devices)


@devices_bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    sb           = get_supabase_with_session()
    uid          = current_user_id()
    device_types = _load_device_types(sb)
    pets         = _load_user_pets(sb, uid)
    locations    = _load_user_locations(sb, uid)

    if request.method == "POST":
        serial_number  = request.form.get("serial_number", "").strip()
        device_type_id = request.form.get("device_type_id", "").strip()
        device_name    = request.form.get("device_name", "").strip()
        pet_id         = request.form.get("pet_id", "").strip() or None
        location_id    = request.form.get("location_id", "").strip() or None

        if not serial_number or not device_type_id or not device_name:
            flash("Serial number, device type, and name are required.", "error")
            return render_template("device_form.html",
                device=None, device_types=device_types, pets=pets, locations=locations)

        if _is_feeder(device_types, device_type_id) and not pet_id:
            flash("Automatic feeders must be assigned to a pet.", "error")
            return render_template("device_form.html",
                device=None, device_types=device_types, pets=pets, locations=locations)

        try:
            sb.table("devices").insert({
                "serial_number":  serial_number,
                "device_type_id": int(device_type_id),
                "owner_id":       uid,
                "pet_id":         pet_id,
                "location_id":    location_id,
                "device_name":    device_name,
                "status":         "offline",
                "is_active":      True,
            }).execute()
            flash(f"Device '{device_name}' registered!", "success")
            return redirect(url_for("devices.index"))
        except Exception as e:
            err = str(e)
            if "devices_serial_number_key" in err or "unique" in err.lower():
                flash("That serial number is already registered.", "error")
            else:
                flash(f"Error registering device: {err}", "error")

    return render_template("device_form.html",
        device=None, device_types=device_types, pets=pets, locations=locations)


@devices_bp.route("/<device_id>/assign", methods=["GET", "POST"])
@login_required
def assign(device_id):
    """Edit pet_id / location_id assignment for an existing device."""
    sb  = get_supabase_with_session()
    uid = current_user_id()

    try:
        res = (
            sb.table("devices")
            .select("*, device_types(slug, name), pets(name), locations(name)")
            .eq("id", device_id).eq("owner_id", uid)
            .single().execute()
        )
        device = res.data
    except Exception:
        device = None

    if not device:
        flash("Device not found.", "error")
        return redirect(url_for("devices.index"))

    pets      = _load_user_pets(sb, uid)
    locations = _load_user_locations(sb, uid)
    is_feeder = (device.get("device_types") or {}).get("slug") == FEEDER_SLUG

    if request.method == "POST":
        pet_id      = request.form.get("pet_id", "").strip() or None
        location_id = request.form.get("location_id", "").strip() or None

        # Feeders must have a pet
        if is_feeder and not pet_id:
            flash("Automatic feeders must be assigned to a pet.", "error")
            return render_template("device_assignment.html",
                device=device, pets=pets, locations=locations, is_feeder=is_feeder)

        # Feeders cannot use location
        if is_feeder:
            location_id = None

        try:
            sb.table("devices").update({
                "pet_id":      pet_id,
                "location_id": location_id,
            }).eq("id", device_id).eq("owner_id", uid).execute()
            flash("Assignment updated successfully.", "success")
            return redirect(url_for("devices.index"))
        except Exception as e:
            flash(f"Error updating assignment: {e}", "error")

    return render_template("device_assignment.html",
        device=device, pets=pets, locations=locations, is_feeder=is_feeder)


@devices_bp.route("/<device_id>/delete", methods=["POST"])
@login_required
def delete(device_id):
    sb  = get_supabase_with_session()
    uid = current_user_id()
    try:
        sb.table("devices").delete().eq("id", device_id).eq("owner_id", uid).execute()
        flash("Device removed.", "success")
    except Exception as e:
        flash(f"Could not delete device: {e}", "error")
    return redirect(url_for("devices.index"))
