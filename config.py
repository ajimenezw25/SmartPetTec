"""
config.py
---------
Loads environment variables and exposes a single Supabase client
that every blueprint can import.

We use ONLY the anon/public key here — the service role key is
never shipped to the browser and is not needed for client-side auth.
"""

import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL: str = os.environ["SUPABASE_URL"]
SUPABASE_KEY: str = os.environ["SUPABASE_KEY"]       # anon public key
FLASK_SECRET_KEY: str = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

# One shared Supabase client for the whole app.
# For authenticated requests we call supabase.auth.set_session() before queries.
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
