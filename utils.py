"""
utils.py
--------
Shared helper utilities used across blueprints.

KEY CHANGE from original:
  get_supabase_with_session() now also handles an expired or invalid
  token gracefully — it clears the Flask session and lets the
  login_required decorator redirect to login, instead of crashing.
"""

from functools import wraps
from flask import session, redirect, url_for, flash
from config import supabase


def login_required(f):
    """
    Decorator that redirects unauthenticated users to the login page.
    Checks for 'user_id' in the Flask session, which is set on login.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def get_supabase_with_session():
    """
    Returns the shared Supabase client after restoring the user's
    auth session from Flask session storage.

    HOW FLASK SESSION + SUPABASE AUTH WORK TOGETHER:
    ──────────────────────────────────────────────────
    - On login, Supabase returns an access_token (JWT) and refresh_token.
    - We store both in Flask's signed+encrypted session cookie.
      The cookie is HttpOnly and never readable by JavaScript.
    - On every subsequent request, this function calls set_session()
      so the Supabase client attaches the user's JWT to every DB query
      as: Authorization: Bearer <access_token>
    - Supabase/Postgres receives the JWT, validates it, sets auth.uid()
      internally, and RLS policies evaluate correctly.

    If the token is missing or invalid, we clear the session so the
    login_required decorator can redirect cleanly on the next check.
    """
    access_token  = session.get("access_token")
    refresh_token = session.get("refresh_token")

    if not access_token or not refresh_token:
        return supabase  # Unauthenticated — login_required will handle it

    try:
        supabase.auth.set_session(access_token, refresh_token)
    except Exception:
        # Token is expired or invalid. Clear the session so the user
        # gets redirected to login on the next login_required check.
        session.clear()

    return supabase


def current_user_id() -> str:
    """
    Return the logged-in user's UUID from the Flask session.
    This is the same UUID as auth.users.id and profiles.id.
    Always use this as owner_id — never derive the user from the request.
    """
    return session.get("user_id", "")
