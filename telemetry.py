"""
telemetry.py
------------
Blueprint for the Telemetry page — shows raw event rows from all devices.
"""

from flask import Blueprint, render_template, session, redirect, url_for
from utils import login_required

telemetry_bp = Blueprint("telemetry", __name__)


@telemetry_bp.route("/telemetry")
@login_required
def index():
    return render_template("telemetry.html")
