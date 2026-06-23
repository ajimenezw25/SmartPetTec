"""
audio_communication.py
-----------------------
Blueprint para el sistema de comunicación de audio con la mascota.

Rutas:
  POST /audio/<device_id>/upload  — sube un mensaje de voz grabado en el
                                     navegador, lo guarda en Supabase Storage
                                     y publica el comando play_audio por MQTT

No crea tablas nuevas. audio_events ya existe y ya es poblada por
telemetry_handlers.handle_audio() cuando el ESP32 reporta el resultado
de la reproducción.

Storage:
  Bucket: audio-messages (público, debe crearse una sola vez en el
  dashboard de Supabase → Storage → New bucket → Public bucket = ON)
"""

import uuid
import logging

from flask import Blueprint, request, jsonify
from utils import login_required, get_supabase_with_session, current_user_id
from config import SUPABASE_URL, supabase_admin
import commands as cmd_module
import mqtt_client

audio_communication_bp = Blueprint("audio_communication", __name__, url_prefix="/audio")
logger = logging.getLogger(__name__)

BUCKET = "audio-messages"

# Content-Type → extensión, para nombrar el archivo en Storage
_EXT_MAP = {
    "audio/webm":  "webm",
    "audio/mp4":   "mp4",
    "audio/mpeg":  "mp3",
    "audio/ogg":   "ogg",
    "audio/wav":   "wav",
    "audio/x-wav": "wav",
}


def _get_owned_audio_device(sb, device_id, uid):
    """Verify device exists, belongs to uid, and is audio_communication."""
    try:
        res = (
            sb.table("devices")
            .select("serial_number, device_name, device_types(slug)")
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
    if (device.get("device_types") or {}).get("slug") != "audio_communication":
        return None, "Este dispositivo no es de tipo Audio Communication."
    return device, None


@audio_communication_bp.route("/<device_id>/upload", methods=["POST"])
@login_required
def upload(device_id):
    """
    Recibe un archivo de audio grabado en el navegador (MediaRecorder),
    lo sube a Supabase Storage y publica el comando play_audio por MQTT.

    Form data:
        audio — archivo de audio (webm/mp4/mp3/wav/ogg)

    Responde JSON (esta ruta es llamada por fetch() desde el navegador,
    no es una página renderizada — por eso usa jsonify directo en vez
    de redirect/flash como el resto de blueprints de página).
    """
    sb  = get_supabase_with_session()
    uid = current_user_id()

    device, error = _get_owned_audio_device(sb, device_id, uid)
    if error:
        return jsonify({"ok": False, "error": error}), 404

    file = request.files.get("audio")
    if not file:
        return jsonify({"ok": False, "error": "No se recibió ningún archivo de audio."}), 400

    content_type = file.content_type or "audio/webm"
    ext = _EXT_MAP.get(content_type, "webm")
    filename = f"{device_id}/{uuid.uuid4()}.{ext}"

    # Subir a Supabase Storage usando el cliente admin (service role),
    # igual que el resto de operaciones server-side de este proyecto.
    try:
        supabase_admin.storage.from_(BUCKET).upload(
            filename,
            file.read(),
            {"content-type": content_type},
        )
        audio_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{filename}"
        logger.info("AUDIO uploaded to storage: %s", audio_url)
    except Exception as e:
        logger.error("AUDIO storage upload failed: %s", e)
        return jsonify({"ok": False, "error": f"Error al subir el audio: {e}"}), 500

    # Publicar comando play_audio por MQTT.
    # commands.py define el parámetro como "audio_file" — se usa ese
    # nombre exacto para que coincida con DEVICE_COMMANDS y con lo que
    # telemetry_handlers.handle_audio() espera leer de vuelta (data.get("audio_file")).
    serial_number = device["serial_number"]
    command_id = cmd_module.publish_command(
        mqtt_client.get_client(), serial_number, "play_audio",
        {"audio_file": audio_url},
    )

    # Igual que en api.py/send_command — registrar el comando pendiente
    # para que dispatch_ack() pueda correlacionarlo si se necesita.
    mqtt_client.pending_commands[command_id] = {
        "command":       "play_audio",
        "serial_number": serial_number,
        "params":        {"audio_file": audio_url},
    }

    if not mqtt_client.is_connected():
        return jsonify({
            "ok": True,
            "data": {
                "command_id": command_id,
                "audio_url":  audio_url,
                "warning":    "MQTT no está conectado — el comando no pudo entregarse.",
            },
        })

    return jsonify({
        "ok": True,
        "data": {
            "command_id": command_id,
            "audio_url":  audio_url,
        },
    })


# ── Biblioteca de audios pregrabados ─────────────────────────────────────────
#
# Los audios de biblioteca se guardan en el mismo bucket "audio-messages"
# bajo la subcarpeta  {device_id}/library/{uuid}.{ext}
# Un archivo de metadatos JSON en  {device_id}/library/_index.json
# guarda el mapeo  path → name  para mostrar nombres amigables en la UI.

import json as _json

LIBRARY_PREFIX = "library"
INDEX_FILE     = "_index.json"


def _read_index(device_id: str) -> dict:
    """Lee el índice de nombres de la biblioteca. Devuelve {} si no existe."""
    path = f"{device_id}/{LIBRARY_PREFIX}/{INDEX_FILE}"
    try:
        raw = supabase_admin.storage.from_(BUCKET).download(path)
        return _json.loads(raw)
    except Exception:
        return {}


def _write_index(device_id: str, index: dict) -> None:
    path = f"{device_id}/{LIBRARY_PREFIX}/{INDEX_FILE}"
    raw  = _json.dumps(index).encode()
    # upsert: eliminar primero si existe, luego subir
    try:
        supabase_admin.storage.from_(BUCKET).remove([path])
    except Exception:
        pass
    supabase_admin.storage.from_(BUCKET).upload(path, raw, {"content-type": "application/json"})


@audio_communication_bp.route("/<device_id>/library", methods=["GET"])
@login_required
def library_list(device_id):
    """Devuelve la lista de audios pregrabados del dispositivo."""
    sb  = get_supabase_with_session()
    uid = current_user_id()

    _, error = _get_owned_audio_device(sb, device_id, uid)
    if error:
        return jsonify({"ok": False, "error": error}), 404

    index = _read_index(device_id)  # {path: name}

    items = []
    for path, name in index.items():
        url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{path}"
        items.append({"path": path, "name": name, "url": url})

    # Orden alfabético por nombre
    items.sort(key=lambda x: x["name"].lower())
    return jsonify({"ok": True, "items": items})


@audio_communication_bp.route("/<device_id>/library/upload", methods=["POST"])
@login_required
def library_upload(device_id):
    """Sube un audio pregrabado a la biblioteca del dispositivo."""
    sb  = get_supabase_with_session()
    uid = current_user_id()

    _, error = _get_owned_audio_device(sb, device_id, uid)
    if error:
        return jsonify({"ok": False, "error": error}), 404

    file = request.files.get("audio")
    name = (request.form.get("name") or "").strip()

    if not file:
        return jsonify({"ok": False, "error": "No se recibió ningún archivo."}), 400
    if not name:
        return jsonify({"ok": False, "error": "El nombre es requerido."}), 400

    content_type = file.content_type or "audio/mpeg"
    ext          = _EXT_MAP.get(content_type, "mp3")
    filename     = f"{device_id}/{LIBRARY_PREFIX}/{uuid.uuid4()}.{ext}"

    try:
        supabase_admin.storage.from_(BUCKET).upload(
            filename, file.read(), {"content-type": content_type}
        )
        logger.info("LIBRARY uploaded: %s", filename)
    except Exception as e:
        logger.error("LIBRARY upload failed: %s", e)
        return jsonify({"ok": False, "error": f"Error al subir: {e}"}), 500

    # Actualizar índice
    try:
        index = _read_index(device_id)
        index[filename] = name
        _write_index(device_id, index)
    except Exception as e:
        logger.error("LIBRARY index update failed: %s", e)
        # El archivo ya está subido — devolver ok igual, solo avisar
        return jsonify({"ok": True, "warning": "Audio subido pero el índice no pudo actualizarse."})

    url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{filename}"
    return jsonify({"ok": True, "path": filename, "name": name, "url": url})


@audio_communication_bp.route("/<device_id>/library/delete", methods=["POST"])
@login_required
def library_delete(device_id):
    """Elimina un audio pregrabado de la biblioteca."""
    sb  = get_supabase_with_session()
    uid = current_user_id()

    _, error = _get_owned_audio_device(sb, device_id, uid)
    if error:
        return jsonify({"ok": False, "error": error}), 404

    body = request.get_json(silent=True) or {}
    path = (body.get("path") or "").strip()

    if not path:
        return jsonify({"ok": False, "error": "Path requerido."}), 400

    # Seguridad: el path debe pertenecer al device_id
    if not path.startswith(f"{device_id}/{LIBRARY_PREFIX}/"):
        return jsonify({"ok": False, "error": "Path no válido."}), 403

    try:
        supabase_admin.storage.from_(BUCKET).remove([path])
        logger.info("LIBRARY deleted: %s", path)
    except Exception as e:
        logger.error("LIBRARY delete failed: %s", e)
        return jsonify({"ok": False, "error": f"Error al eliminar: {e}"}), 500

    # Actualizar índice
    try:
        index = _read_index(device_id)
        index.pop(path, None)
        _write_index(device_id, index)
    except Exception as e:
        logger.warning("LIBRARY index cleanup failed after delete: %s", e)

    return jsonify({"ok": True})


# ── Audios base (seed) ────────────────────────────────────────────────────────
#
# Genera 7 audios base con gTTS usando el nombre de la mascota asignada
# y los sube a la biblioteca del dispositivo.
# Se llama automáticamente desde el frontend la primera vez que se abre
# la página si la biblioteca está vacía.
# Requiere: pip install gtts

_BASE_MESSAGES = [
    ("¡Hola!",               "¡Hola, {name}! ¿Cómo estás?"),
    ("Hora de comer",        "¡{name}, es hora de comer!"),
    ("Te extraño",           "¡{name}, te extraño mucho!"),
    ("Buen comportamiento",  "¡Muy bien, {name}! Sos un buen chico."),
    ("Hora de dormir",       "¡Buenas noches, {name}! Es hora de descansar."),
    ("¿Dónde estás?",        "¡{name}! ¿Dónde estás?"),
    ("Te quiero",            "¡{name}, te quiero mucho!"),
]


@audio_communication_bp.route("/<device_id>/library/seed", methods=["POST"])
@login_required
def library_seed(device_id):
    """
    Genera y sube los audios base con gTTS usando el nombre de la mascota.
    El frontend lo llama la primera vez que la biblioteca está vacía.
    Requiere que el dispositivo tenga una mascota asignada.
    """
    try:
        from gtts import gTTS
        import io as _io
    except ImportError:
        return jsonify({"ok": False, "error": "gTTS no instalado. Ejecutá: pip install gtts"}), 500

    sb  = get_supabase_with_session()
    uid = current_user_id()

    # Verificar dispositivo y obtener nombre de mascota
    try:
        res = (
            sb.table("devices")
            .select("serial_number, device_name, device_types(slug), pets(name)")
            .eq("id", device_id)
            .eq("owner_id", uid)
            .single()
            .execute()
        )
        device = res.data
    except Exception:
        return jsonify({"ok": False, "error": "Dispositivo no encontrado."}), 404

    if not device:
        return jsonify({"ok": False, "error": "Dispositivo no encontrado."}), 404
    if (device.get("device_types") or {}).get("slug") != "audio_communication":
        return jsonify({"ok": False, "error": "No es un dispositivo de audio."}), 400

    pet_name = (device.get("pets") or {}).get("name") or "mascota"

    index   = _read_index(device_id)
    created = []
    errors  = []

    for label, template in _BASE_MESSAGES:
        text = template.format(name=pet_name)
        try:
            buf = _io.BytesIO()
            tts = gTTS(text=text, lang="es", tld="com.mx")  # Español Latino
            tts.write_to_fp(buf)
            audio_bytes = buf.getvalue()

            filename = f"{device_id}/{LIBRARY_PREFIX}/base_{uuid.uuid4()}.mp3"
            supabase_admin.storage.from_(BUCKET).upload(
                filename, audio_bytes, {"content-type": "audio/mpeg"}
            )
            index[filename] = label
            created.append(label)
            logger.info("SEED uploaded: %s → %s", label, filename)

        except Exception as e:
            logger.error("SEED failed for '%s': %s", label, e)
            errors.append({"label": label, "error": str(e)})

    # Guardar índice actualizado
    if created:
        try:
            _write_index(device_id, index)
        except Exception as e:
            logger.error("SEED index write failed: %s", e)
            return jsonify({"ok": False, "error": f"Audios generados pero índice no guardado: {e}"}), 500

    return jsonify({
        "ok":      True,
        "created": created,
        "errors":  errors,
        "pet_name": pet_name,
    })
