"""
water_dispenser.py
------------------
Blueprint para la configuración del dispensador de agua.

Rutas:
  GET/POST /water/<device_id>/settings  — ver y guardar configuración
  POST     /water/<device_id>/reset     — reiniciar contador de recargas

Tabla Supabase usada: water_configurations
  device_id         uuid  FK → devices
  owner_id          uuid  FK → auth.users
  max_refills       int   (default 3)
  refills_remaining int   (current count)
  dist_full_cm      float (sensor reading when full)
  dist_empty_cm     float (sensor reading when empty)
  low_threshold_pct int   (% at which refill starts)
  high_threshold_pct int  (% at which refill stops)
  updated_at        timestamptz
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from utils import login_required, get_supabase_with_session, current_user_id

water_bp = Blueprint("water", __name__, url_prefix="/water")

# ── Defaults ──────────────────────────────────────────────────
MAX_REFILLS        = 3
DIST_FULL_DEFAULT  = 3.0
DIST_EMPTY_DEFAULT = 20.0
LOW_THR_DEFAULT    = 25
HIGH_THR_DEFAULT   = 80


def _get_owned_water(sb, device_id, uid):
    """Verify device exists, belongs to uid, and is a water_dispenser."""
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
        return None, "Dispositivo no encontrado."

    if not device:
        return None, "Dispositivo no encontrado."
    if (device.get("device_types") or {}).get("slug") != "water_dispenser":
        return None, "Este dispositivo no es un dispensador de agua."
    return device, None


def _load_config(sb, device_id):
    """Return water_configurations row or None."""
    res = sb.table("water_configurations").select("*").eq("device_id", device_id).execute()
    return res.data[0] if res.data else None


def _save_config(sb, device_id, owner_id, payload: dict):
    """Upsert water_configurations."""
    existing = sb.table("water_configurations").select("id").eq("device_id", device_id).execute()
    payload["device_id"] = device_id
    payload["owner_id"]  = owner_id
    if existing.data:
        sb.table("water_configurations").update(payload).eq("id", existing.data[0]["id"]).execute()
    else:
        sb.table("water_configurations").insert(payload).execute()


# ── Settings page ─────────────────────────────────────────────

@water_bp.route("/<device_id>/settings", methods=["GET", "POST"])
@login_required
def settings(device_id):
    sb  = get_supabase_with_session()
    uid = current_user_id()

    device, err = _get_owned_water(sb, device_id, uid)
    if err:
        flash(err, "error")
        return redirect(url_for("devices.index"))

    config = _load_config(sb, device_id)

    if request.method == "POST":
        action = request.form.get("action")

        if action == "save_config":
            try:
                payload = {
                    "dist_full_cm":       float(request.form.get("dist_full_cm",  DIST_FULL_DEFAULT)),
                    "dist_empty_cm":      float(request.form.get("dist_empty_cm", DIST_EMPTY_DEFAULT)),
                    "low_threshold_pct":  int(request.form.get("low_threshold_pct",  LOW_THR_DEFAULT)),
                    "high_threshold_pct": int(request.form.get("high_threshold_pct", HIGH_THR_DEFAULT)),
                }
                # Preserve refills_remaining if config already exists
                if config:
                    payload["refills_remaining"] = config.get("refills_remaining", MAX_REFILLS)
                    payload["max_refills"]        = config.get("max_refills", MAX_REFILLS)
                else:
                    payload["refills_remaining"] = MAX_REFILLS
                    payload["max_refills"]        = MAX_REFILLS

                _save_config(sb, device_id, uid, payload)
                flash("✅ Configuración guardada. Envía el comando 'Sync Config' al dispositivo para aplicarla.", "success")
            except (ValueError, TypeError) as e:
                flash(f"Error en los valores: {e}", "error")

        return redirect(url_for("water.settings", device_id=device_id))

    return render_template(
        "water_settings.html",
        device=device,
        config=config,
        max_refills=MAX_REFILLS,
        dist_full_default=DIST_FULL_DEFAULT,
        dist_empty_default=DIST_EMPTY_DEFAULT,
        low_thr_default=LOW_THR_DEFAULT,
        high_thr_default=HIGH_THR_DEFAULT,
    )


# ── Reset refill counter ───────────────────────────────────────

@water_bp.route("/<device_id>/reset", methods=["POST"])
@login_required
def reset_refills(device_id):
    sb  = get_supabase_with_session()
    uid = current_user_id()

    device, err = _get_owned_water(sb, device_id, uid)
    if err:
        flash(err, "error")
        return redirect(url_for("devices.index"))

    config = _load_config(sb, device_id)
    max_r  = (config or {}).get("max_refills", MAX_REFILLS)

    payload = {"refills_remaining": max_r}
    if config:
        sb.table("water_configurations").update(payload).eq("device_id", device_id).execute()
    else:
        payload.update({
            "device_id":          device_id,
            "owner_id":           uid,
            "max_refills":        MAX_REFILLS,
            "dist_full_cm":       DIST_FULL_DEFAULT,
            "dist_empty_cm":      DIST_EMPTY_DEFAULT,
            "low_threshold_pct":  LOW_THR_DEFAULT,
            "high_threshold_pct": HIGH_THR_DEFAULT,
        })
        sb.table("water_configurations").insert(payload).execute()

    flash(f"✅ Contador de recargas reiniciado a {max_r}.", "success")
    return redirect(url_for("water.settings", device_id=device_id))