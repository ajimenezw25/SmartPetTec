# SmartPetHome / SmartPetTec — Project Context

## Critical Rules

- Do NOT change the Supabase database schema.
- Do NOT create new tables.
- Do NOT rename columns.
- Do NOT delete tables.
- Do NOT migrate Flask to FastAPI.
- Do NOT use React, Node.js, npm, Tailwind, Docker, or frontend build tools.
- Keep the current Flask + Supabase + HTML/CSS/Jinja + vanilla JavaScript architecture.
- Keep the current authentication/session flow.
- Keep PyInstaller compatibility.
- If requirements.txt changes, use pyinstaller==6.20.0. Do NOT use pyinstaller==6.6.0.

## Current Stack

- Python
- Flask
- Supabase PostgreSQL
- Supabase Auth
- HTML/CSS/Jinja templates
- Vanilla JavaScript in static/app.js
- MQTT using paho-mqtt
- EMQX Public Broker
- Telegram Bot API using requests
- PyInstaller for Windows executable

## MQTT Broker

We are using EMQX Public Broker, not HiveMQ Cloud.

Use this MQTT config:

MQTT_HOST=broker.emqx.io
MQTT_PORT=1883
MQTT_USERNAME=
MQTT_PASSWORD=
MQTT_TLS=false
MQTT_CLIENT_ID=smartpethome-backend

This is for a university prototype. It is public, so do not send sensitive data.

## MQTT Topics

Telemetry:
smartpethome/devices/{serial_number}/telemetry

Status:
smartpethome/devices/{serial_number}/status

Commands:
smartpethome/devices/{serial_number}/command

Acknowledgements:
smartpethome/devices/{serial_number}/ack

## Device Types

The project supports:

1. automatic_feeder
2. water_dispenser
3. motion_monitoring_network
4. audio_communication
5. environmental_monitor
6. automatic_access_door
7. interactive_reward_system
8. automatic_ball_launcher

## Hardware Sprint Goal

We need physical wireless ESP32 devices, not emulators.

Serial Monitor is allowed only for debugging. It is not the communication protocol.

The real communication protocol is:

ESP32 → WiFi → EMQX Public Broker → Flask backend → Supabase → JavaScript frontend

Commands flow:

Frontend → Flask API → EMQX Public Broker → ESP32 → ACK → App

## First Physical Proof of Concept

Start with automatic_feeder:

- ESP32
- potentiometer as prototype weight/food-level sensor
- servo as feeder gate
- red LED for alert/low food
- green LED for normal/dispensing

The ESP32 serial number must match the app device serial:
FEEDER-001

## Known Issues

- app.py must remain the Flask entry point.
- profile.py exists and should not accidentally be pasted into app.py.
- devices.py must remain complete. Do not replace it with only the /detail route.
- requirements.txt must use pyinstaller==6.20.0.
- Do not break the existing device registration, dashboard, alerts, history, or feeder settings.