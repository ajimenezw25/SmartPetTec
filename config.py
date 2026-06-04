"""
config.py
---------
Central configuration. Loads environment variables and creates
Supabase client instances.

TWO SUPABASE CLIENTS:
  supabase       - anon/public key. Used for all user-facing operations
                   (auth, RLS-protected queries from Flask routes).
  supabase_admin - service role key (optional). Used ONLY for server-side
                   backend operations like MQTT telemetry processing, where
                   there is no user session to authenticate with.
                   NEVER sent to the browser or exposed in API responses.
                   If SUPABASE_SERVICE_KEY is not set, falls back to the
                   anon key (telemetry inserts may fail due to RLS).
"""

import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL:         str = os.environ["SUPABASE_URL"]
SUPABASE_KEY:         str = os.environ["SUPABASE_KEY"]
SUPABASE_SERVICE_KEY: str = os.environ.get("SUPABASE_SERVICE_KEY", "")
FLASK_SECRET_KEY:     str = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

# MQTT — EMQX Public Broker
MQTT_HOST:      str  = os.environ.get("MQTT_HOST", "broker.emqx.io")
MQTT_PORT:      int  = int(os.environ.get("MQTT_PORT", 1883))
MQTT_USERNAME:  str  = os.environ.get("MQTT_USERNAME", "")
MQTT_PASSWORD:  str  = os.environ.get("MQTT_PASSWORD", "")
MQTT_TLS:       bool = os.environ.get("MQTT_TLS", "false").lower() == "true"
MQTT_CLIENT_ID: str  = os.environ.get("MQTT_CLIENT_ID", "smartpethome-backend")

# Telegram
TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# ── Supabase clients ─────────────────────────────────────────
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Admin client — service role bypasses RLS for trusted server-side ops
_admin_key = SUPABASE_SERVICE_KEY or SUPABASE_KEY
supabase_admin: Client = create_client(SUPABASE_URL, _admin_key)
