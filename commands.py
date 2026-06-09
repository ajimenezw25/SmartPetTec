"""
commands.py
-----------
Defines valid commands for each device type and publishes them via MQTT.

DEVICE_COMMANDS is consumed by the /api/devices/<id>/command endpoint
and by static/app.js to render device-specific command UI.

Each command entry:
  {
    "command": "command_name",
    "label":   "Human Readable Label",
    "params":  [
        {"name": "grams", "type": "number", "label": "Grams", "required": True},
        {"name": "mode",  "type": "select", "options": ["a","b"], "label": "Mode"},
    ]
  }
"""

import json
import uuid
import logging

logger = logging.getLogger(__name__)

# ── Command definitions per device type slug ─────────────────
DEVICE_COMMANDS: dict[str, list[dict]] = {
    "automatic_feeder": [
        {
            "command": "dispense_food",
            "label":   "Dispense Food Now",
            "params":  [{"name": "grams", "type": "number", "label": "Grams", "required": True}],
        },
        {
            "command": "set_feeding_mode",
            "label":   "Set Feeding Mode",
            "params":  [{"name": "mode", "type": "select",
                         "options": ["complete_bowl", "redistribute_daily_diet"],
                         "label": "Mode", "required": True}],
        },
        {"command": "sync_schedules",  "label": "Sync Schedules to Device", "params": []},
        {"command": "calibrate_scale", "label": "Calibrate Scale",          "params": []},
        {"command": "tare_scale",      "label": "Tare Scale (Zero)",         "params": []},
        {"command": "get_status",      "label": "Refresh Status",            "params": []},
    ],
    "water_dispenser": [
        {"command": "refill_now",      "label": "Refill Now",           "params": []},
        {"command": "open_valve",      "label": "Open Valve",           "params": []},
        {"command": "close_valve",     "label": "Close Valve",          "params": []},
        {
            "command": "set_auto_refill",
            "label":   "Set Auto-Refill",
            "params":  [{"name": "enabled", "type": "select",
                         "options": ["true", "false"], "label": "Enabled", "required": True}],
        },
        {"command": "sync_config",     "label": "Sync Config",          "params": []},
        {"command": "reset_refills",   "label": "Reset Refill Counter", "params": []},
        {"command": "get_status",      "label": "Refresh Status",       "params": []},
    ],
    "motion_monitoring_network": [
        {
            "command": "set_inactivity_limit",
            "label":   "Set Inactivity Limit",
            "params":  [{"name": "minutes", "type": "number", "label": "Minutes", "required": True}],
        },
        {"command": "enable_monitoring",  "label": "Enable Monitoring",  "params": []},
        {"command": "disable_monitoring", "label": "Disable Monitoring", "params": []},
        {"command": "get_status",         "label": "Refresh Status",     "params": []},
    ],
    "audio_communication": [
        {
            "command": "play_audio",
            "label":   "Play Audio File",
            "params":  [{"name": "audio_file", "type": "text", "label": "Audio File / Message ID", "required": True}],
        },
        {
            "command": "set_volume",
            "label":   "Set Volume",
            "params":  [{"name": "level", "type": "number", "label": "Volume (0-100)", "required": True}],
        },
        {"command": "stop_audio", "label": "Stop Audio",      "params": []},
        {"command": "get_status", "label": "Refresh Status",  "params": []},
    ],
    "environmental_monitor": [
        {
            "command": "set_temperature_range",
            "label":   "Set Temperature Range",
            "params":  [
                {"name": "min_temperature", "type": "number", "label": "Min Temp (°C)", "required": True},
                {"name": "max_temperature", "type": "number", "label": "Max Temp (°C)", "required": True},
            ],
        },
        {"command": "turn_actuator_on",  "label": "Turn Actuator ON",      "params": []},
        {"command": "turn_actuator_off", "label": "Turn Actuator OFF",     "params": []},
        {
            "command": "set_auto_control",
            "label":   "Set Auto Control",
            "params":  [{"name": "enabled", "type": "select",
                         "options": ["true", "false"], "label": "Enabled", "required": True}],
        },
        {"command": "get_status", "label": "Refresh Status", "params": []},
    ],
    "automatic_access_door": [
        {"command": "open_door",              "label": "Open Door",              "params": []},
        {"command": "close_door",             "label": "Close Door",             "params": []},
        {"command": "enable_manual_control",  "label": "Enable Manual Control",  "params": []},
        {"command": "disable_manual_control", "label": "Disable Manual Control", "params": []},
        {"command": "get_status",             "label": "Refresh Status",         "params": []},
    ],
    "interactive_reward_system": [
        {
            "command": "set_winning_button",
            "label":   "Set Winning Button",
            "params":  [{"name": "button", "type": "number", "label": "Button Number (1-5)", "required": True}],
        },
        {"command": "dispense_reward",      "label": "Dispense Reward Now",   "params": []},
        {
            "command": "set_cooldown",
            "label":   "Set Cooldown",
            "params":  [{"name": "minutes", "type": "number", "label": "Cooldown (minutes)", "required": True}],
        },
        {
            "command": "set_max_rewards_per_day",
            "label":   "Set Daily Reward Limit",
            "params":  [{"name": "max", "type": "number", "label": "Max Rewards/Day", "required": True}],
        },
        {"command": "enable_game",  "label": "Enable Game",   "params": []},
        {"command": "disable_game", "label": "Disable Game",  "params": []},
        {"command": "get_status",   "label": "Refresh Status","params": []},
    ],
    "automatic_ball_launcher": [
        {
            "command": "launch_ball",
            "label":   "Launch Ball",
            "params":  [{"name": "trajectory_number", "type": "number", "label": "Trajectory (1-3)", "required": False}],
        },
        {
            "command": "set_launch_mode",
            "label":   "Set Launch Mode",
            "params":  [{"name": "mode", "type": "select",
                         "options": ["manual", "scheduled", "both"],
                         "label": "Mode", "required": True}],
        },
        {
            "command": "set_trajectory",
            "label":   "Set Trajectory",
            "params":  [{"name": "number", "type": "number", "label": "Trajectory Number", "required": True}],
        },
        {"command": "sync_launch_schedule", "label": "Sync Launch Schedule", "params": []},
        {"command": "get_status",           "label": "Refresh Status",       "params": []},
    ],
}


def publish_command(mqtt_client, serial_number: str, command: str, params: dict | None = None) -> str:
    """
    Publish a command JSON to:
      smartpethome/devices/{serial_number}/command

    Returns the generated command_id so callers can track the ack.
    """
    command_id = str(uuid.uuid4())
    payload = {
        "command":    command,
        "command_id": command_id,
        "params":     params or {},
    }
    topic = f"smartpethome/devices/{serial_number}/command"
    try:
        mqtt_client.publish(topic, json.dumps(payload), qos=1)
        logger.info("Published command '%s' to %s (id=%s)", command, topic, command_id)
    except Exception as e:
        logger.error("Failed to publish command: %s", e)
    return command_id


def get_commands_for_slug(slug: str) -> list[dict]:
    """Return the command definitions for a device type slug."""
    return DEVICE_COMMANDS.get(slug, [])