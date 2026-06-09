"""
mqtt_client.py
--------------
MQTT client for EMQX Public Broker (broker.emqx.io:1883, no TLS, no auth).

Runs in a background daemon thread so it doesn't block Flask.

Topic structure:
  Telemetry (ESP → backend): smartpethome/devices/{serial}/telemetry
  Status/heartbeat (ESP → backend): smartpethome/devices/{serial}/status
  Commands (backend → ESP): smartpethome/devices/{serial}/command
  Ack (ESP → backend): smartpethome/devices/{serial}/ack

The ack_store dict is shared between mqtt_client and the API so
command acknowledgements can be polled via /api/devices/<id>/ack/<cmd_id>.
"""

import json
import logging
import ssl
import threading

import paho.mqtt.client as mqtt

from config import (
    MQTT_HOST, MQTT_PORT, MQTT_USERNAME, MQTT_PASSWORD,
    MQTT_TLS, MQTT_CLIENT_ID,
)
from telemetry_handlers import dispatch_telemetry, dispatch_status, dispatch_ack

logger = logging.getLogger(__name__)

# In-memory store for command acks: {command_id: ack_payload}
# Shared with api.py to allow the frontend to poll for ack results.
ack_store: dict = {}

# In-memory store for pending commands: {command_id: {command, serial_number, params}}
# Populated by api.py when a command is published so dispatch_ack() can
# identify what command an incoming ACK belongs to (e.g. to record manual_dispense).
pending_commands: dict = {}

# Global MQTT client instance (set by start_mqtt())
_mqtt_client: mqtt.Client | None = None
_connected: bool = False


def get_client() -> mqtt.Client | None:
    return _mqtt_client


def is_connected() -> bool:
    return _connected


# ── MQTT callbacks ────────────────────────────────────────────

def _on_connect(client, userdata, flags, reason_code, properties=None):
    global _connected
    if reason_code == 0 or reason_code == mqtt.MQTT_ERR_SUCCESS:
        _connected = True
        logger.info("MQTT connected to %s:%s", MQTT_HOST, MQTT_PORT)
        # Subscribe to wildcard topics for all devices
        client.subscribe("smartpethome/devices/+/telemetry", qos=1)
        client.subscribe("smartpethome/devices/+/status",    qos=1)
        client.subscribe("smartpethome/devices/+/ack",       qos=1)
        logger.info("Subscribed to smartpethome/devices/+/{telemetry,status,ack}")
    else:
        _connected = False
        logger.error("MQTT connection failed with code %s", reason_code)


def _on_disconnect(client, userdata, disconnect_flags, reason_code, properties=None):
    global _connected
    _connected = False
    logger.warning("MQTT disconnected (code=%s). Will auto-reconnect.", reason_code)


def _on_message(client, userdata, msg):
    """
    Route incoming MQTT messages to the correct handler.
    Topic format: smartpethome/devices/{serial_number}/{type}
    """
    topic = msg.topic
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning("Could not parse MQTT payload on %s: %s", topic, e)
        return

    # Extract serial_number and message type from topic
    parts = topic.split("/")
    if len(parts) != 4:
        return

    _, _, serial_number, msg_type = parts

    logger.debug("MQTT MESSAGE topic=%s payload=%s", topic, payload)
    logger.debug("MQTT ROUTE serial=%s type=%s", serial_number, msg_type)

    if msg_type == "telemetry":
        dispatch_telemetry(serial_number, payload)
    elif msg_type == "status":
        dispatch_status(serial_number, payload)
    elif msg_type == "ack":
        dispatch_ack(serial_number, payload, ack_store, pending_commands)
    else:
        logger.warning("Unknown MQTT message type '%s' on topic '%s' — ignored.", msg_type, topic)


# ── Connection setup ──────────────────────────────────────────

def _build_client() -> mqtt.Client:
    client = mqtt.Client(
        client_id        = MQTT_CLIENT_ID,
        protocol         = mqtt.MQTTv5,
        callback_api_version = mqtt.CallbackAPIVersion.VERSION2,
    )
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    if MQTT_TLS:
        tls_ctx = ssl.create_default_context()
        client.tls_set_context(tls_ctx)

    client.on_connect    = _on_connect
    client.on_disconnect = _on_disconnect
    client.on_message    = _on_message

    return client


def _mqtt_thread_func():
    """Target function for the background MQTT thread."""
    global _mqtt_client
    try:
        _mqtt_client = _build_client()
        _mqtt_client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        logger.info("Starting MQTT loop (blocking) in background thread…")
        _mqtt_client.loop_forever()     # Handles reconnects automatically
    except Exception as e:
        logger.error("MQTT thread error: %s", e)


def start_mqtt() -> None:
    """
    Start the MQTT client in a background daemon thread.
    Safe to call multiple times (checks if already running).
    Should be called once when Flask starts (in app.py).

    Skips startup if MQTT_HOST is not configured (development without MQTT).
    """
    if not MQTT_HOST:
        logger.warning(
            "MQTT_HOST not set — MQTT disabled. "
            "Set MQTT_HOST in .env to enable IoT communication."
        )
        return

    thread = threading.Thread(target=_mqtt_thread_func, daemon=True, name="mqtt-client")
    thread.start()
    logger.info("MQTT background thread started.")


def publish(topic: str, payload: str | dict, qos: int = 1) -> bool:
    """
    Publish a message to a topic. Returns True on success.
    Used by the /api/devices/<id>/command endpoint.
    """
    global _mqtt_client
    if not _mqtt_client or not _connected:
        logger.warning("MQTT publish attempted but client not connected.")
        return False
    try:
        msg = payload if isinstance(payload, str) else json.dumps(payload)
        _mqtt_client.publish(topic, msg, qos=qos)
        return True
    except Exception as e:
        logger.error("MQTT publish error: %s", e)
        return False
