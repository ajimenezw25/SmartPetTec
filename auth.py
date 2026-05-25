"""
auth.py
-------
Blueprint handling user registration, login, and logout.

KEY CHANGE from original:
  We no longer manually INSERT into public.profiles here.
  A Postgres trigger (handle_new_user) on auth.users does it
  automatically and reliably, bypassing RLS via SECURITY DEFINER.

  We DO pass display_name + telegram_chat_id into Supabase Auth
  user metadata during sign_up so the trigger can read them.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from config import supabase

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email        = request.form.get("email", "").strip()
        password     = request.form.get("password", "")
        display_name = request.form.get("display_name", "").strip()
        telegram_id  = request.form.get("telegram_chat_id", "").strip() or None

        if not email or not password or not display_name:
            flash("Email, password, and display name are required.", "error")
            return render_template("register.html")

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("register.html")

        try:
            # Pass display_name into user metadata.
            # The DB trigger reads raw_user_meta_data->>'display_name'
            # and uses it when creating the profiles row automatically.
            res = supabase.auth.sign_up({
                "email":    email,
                "password": password,
                "options": {
                    "data": {
                        "display_name":     display_name,
                        "telegram_chat_id": telegram_id,
                    }
                }
            })

            if res.user is None:
                flash("Registration failed. The email may already be in use.", "error")
                return render_template("register.html")

            # Because email confirmation is DISABLED in Supabase Auth,
            # sign_up() returns a live session immediately.
            # We log the user straight in so they don't have to re-enter credentials.
            if res.session:
                session["user_id"]       = res.user.id
                session["user_email"]    = res.user.email
                session["access_token"]  = res.session.access_token
                session["refresh_token"] = res.session.refresh_token
                session["display_name"]  = display_name

                flash(f"Welcome, {display_name}! Your account has been created.", "success")
                return redirect(url_for("dashboard.index"))

            # Fallback: if for any reason there's no session (e.g. confirmation
            # was accidentally re-enabled), send them to login.
            flash("Account created! Please log in.", "success")
            return redirect(url_for("auth.login"))

        except Exception as e:
            error_msg = str(e)
            # Supabase returns "User already registered" for duplicate emails
            if "already registered" in error_msg.lower() or "already been registered" in error_msg.lower():
                flash("An account with that email already exists.", "error")
            else:
                flash(f"Registration error: {error_msg}", "error")

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Both fields are required.", "error")
            return render_template("login.html")

        try:
            res = supabase.auth.sign_in_with_password(
                {"email": email, "password": password}
            )

            if res.session is None:
                flash("Invalid email or password.", "error")
                return render_template("login.html")

            # Store tokens in Flask's encrypted session cookie.
            # These are restored on every request by get_supabase_with_session()
            # so that RLS policies receive the correct auth.uid().
            session["user_id"]       = res.user.id
            session["user_email"]    = res.user.email
            session["access_token"]  = res.session.access_token
            session["refresh_token"] = res.session.refresh_token

            # Restore the Supabase session so we can query with RLS active
            supabase.auth.set_session(res.session.access_token, res.session.refresh_token)

            # Fetch the display_name from profiles (created by the DB trigger)
            try:
                profile = (
                    supabase.table("profiles")
                    .select("display_name")
                    .eq("id", res.user.id)
                    .single()
                    .execute()
                )
                display_name = profile.data.get("display_name", email)
            except Exception:
                # Profile fetch failing should never block login
                display_name = email

            session["display_name"] = display_name

            flash(f"Welcome back, {display_name}!", "success")
            return redirect(url_for("dashboard.index"))

        except Exception as e:
            error_msg = str(e)
            if "invalid login credentials" in error_msg.lower():
                flash("Invalid email or password.", "error")
            else:
                flash(f"Login error: {error_msg}", "error")

    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    try:
        supabase.auth.sign_out()
    except Exception:
        pass  # Sign-out errors should never prevent session clearing
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
