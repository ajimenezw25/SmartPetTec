"""
app.py
------
Flask application entry point.
Run with: python app.py
Or as packaged .exe built with PyInstaller.

The sys.frozen block handles path resolution when running inside
a PyInstaller bundle — templates and static files are extracted
to sys._MEIPASS at runtime.
"""

import sys
import os

# ── PyInstaller frozen path fix ──────────────────────────────
# When packaged with PyInstaller, __file__ points inside a temp
# dir (sys._MEIPASS). We tell Flask to look there for templates
# and static files by passing the correct root_path.
if getattr(sys, 'frozen', False):
    # Running as compiled .exe
    _base_dir = sys._MEIPASS
else:
    # Running as normal Python script
    _base_dir = os.path.dirname(os.path.abspath(__file__))

from flask import Flask
from config import FLASK_SECRET_KEY

from auth       import auth_bp
from dashboard  import dashboard_bp
from pets       import pets_bp
from devices    import devices_bp
from feeder     import feeder_bp
from alerts     import alerts_bp
from history    import history_bp
from profile    import profile_bp
from locations  import locations_bp

app = Flask(
    __name__,
    template_folder = os.path.join(_base_dir, "templates"),
    static_folder   = os.path.join(_base_dir, "static"),
)
app.secret_key = FLASK_SECRET_KEY

app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(pets_bp)
app.register_blueprint(devices_bp)
app.register_blueprint(feeder_bp)
app.register_blueprint(alerts_bp)
app.register_blueprint(history_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(locations_bp)


@app.template_filter("datefmt")
def datefmt(value, fmt="%Y-%m-%d %H:%M"):
    """Format an ISO datetime string for display in templates."""
    if not value:
        return "—"
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.strftime(fmt)
    except Exception:
        return str(value)


if __name__ == "__main__":
    # debug=False in production / packaged builds
    is_frozen = getattr(sys, 'frozen', False)
    app.run(debug=not is_frozen, port=5000, use_reloader=not is_frozen)
