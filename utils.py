"""
utils.py
--------
Shared helper utilities used across blueprints.
"""

import logging
from functools import wraps
from flask import session, redirect, url_for, flash
from config import supabase

logger = logging.getLogger(__name__)


def login_required(f):
    """
    Decorator that redirects unauthenticated users to the login page.
    Checks for 'user_id' in the Flask session, which is set on login.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            logger.info("SESSION redirect to login — user_id missing from session")
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def get_supabase_with_session():
    """
    Returns the shared Supabase client after restoring the user's
    auth session from Flask session storage.

    Token handling:
      1. Try set_session() with the stored access + refresh tokens.
      2. If that fails (token expired), attempt a silent token refresh.
      3. If the refresh succeeds, update the session cookie with the new tokens.
      4. If the refresh also fails, keep the Flask session intact and log a
         warning — the user stays "logged in" in the app but Supabase queries
         that require RLS may fail gracefully on the affected request.
      5. NEVER call session.clear() here. The only place that should clear the
         session is the explicit /logout route.
    """
    access_token  = session.get("access_token")
    refresh_token = session.get("refresh_token")

    if not access_token or not refresh_token:
        logger.debug("SESSION no tokens in session — returning unauthenticated client")
        return supabase

    try:
        supabase.auth.set_session(access_token, refresh_token)
        return supabase
    except Exception as set_err:
        logger.debug("SESSION set_session failed (%s) — attempting token refresh", set_err)

    # set_session failed — try to silently refresh the token
    try:
        refreshed = supabase.auth.refresh_session(refresh_token)
        if refreshed and refreshed.session:
            new_access  = refreshed.session.access_token
            new_refresh = refreshed.session.refresh_token
            session["access_token"]  = new_access
            session["refresh_token"] = new_refresh
            supabase.auth.set_session(new_access, new_refresh)
            logger.info("SESSION token refreshed silently for user=%s", session.get("user_id"))
        else:
            logger.warning("SESSION token refresh returned no session — keeping Flask session as-is")
    except Exception as refresh_err:
        # Refresh failed (network issue, truly expired refresh token, etc.)
        # Do NOT clear the session — that would log the user out unexpectedly.
        # The route will handle any DB errors that result from stale tokens.
        logger.warning("SESSION token refresh failed: %s — keeping Flask session intact", refresh_err)

    return supabase


def current_user_id() -> str:
    """
    Return the logged-in user's UUID from the Flask session.
    This is the same UUID as auth.users.id and profiles.id.
    Always use this as owner_id — never derive the user from the request.
    """
    return session.get("user_id", "")
