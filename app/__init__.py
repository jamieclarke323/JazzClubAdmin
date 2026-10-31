import os
import secrets
from functools import wraps

from flask import Flask, abort, g, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from flask_login import current_user, login_required

from config import Config

from .extensions import db, login_manager, migrate
from .utils import PRIORITIES, RECURRENCE_SHORT, RECURRENCES, due_label, today_local


def household_required(view):
    """Require a logged-in user who belongs to a household."""

    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.household_id:
            if _wants_json():
                return jsonify(ok=False, error="No household", redirect=url_for("household.setup")), 403
            return redirect(url_for("household.setup"))
        return view(*args, **kwargs)

    return wrapper


def _wants_json() -> bool:
    return request.is_json or request.headers.get("X-Requested-With") == "fetch"


def create_app(config_object=Config) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)
    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = None

    from . import models

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(models.User, int(user_id))

    @login_manager.unauthorized_handler
    def unauthorized():
        if _wants_json():
            return jsonify(ok=False, error="Not signed in", redirect=url_for("auth.login")), 401
        return redirect(url_for("auth.login", next=request.full_path if request.method == "GET" else None))

    # --- CSRF ---------------------------------------------------------------
    def csrf_token() -> str:
        token = session.get("_csrf")
        if not token:
            token = secrets.token_urlsafe(32)
            session["_csrf"] = token
        return token

    @app.before_request
    def csrf_protect():
        if not app.config.get("CSRF_ENABLED", True):
            return None
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            expected = session.get("_csrf")
            sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
            if not expected or not sent or not secrets.compare_digest(expected, sent):
                abort(400, description="Your session expired. Please reload the page and try again.")
        return None

    # --- Static asset versioning (cache busting for the PWA) -----------------
    static_dir = os.path.join(app.root_path, "static")
    latest_mtime = 0
    for root, _dirs, files in os.walk(static_dir):
        for name in files:
            latest_mtime = max(latest_mtime, int(os.path.getmtime(os.path.join(root, name))))
    app.config["ASSET_VERSION"] = str(latest_mtime)

    def static_url(filename: str) -> str:
        return url_for("static", filename=filename, v=app.config["ASSET_VERSION"])

    # --- Template helpers -----------------------------------------------------
    @app.context_processor
    def inject_globals():
        ctx = {
            "csrf_token": csrf_token,
            "static_url": static_url,
            "app_name": app.config["APP_NAME"],
            "today": today_local(),
            "RECURRENCES": RECURRENCES,
            "RECURRENCE_SHORT": RECURRENCE_SHORT,
            "PRIORITIES": PRIORITIES,
            "SHOPPING_CATEGORIES": models.SHOPPING_CATEGORIES,
            "nav_counts": {},
        }
        if current_user.is_authenticated and current_user.household_id:
            hid = current_user.household_id
            ctx["nav_counts"] = {
                "shopping": models.ShoppingItem.query.filter_by(household_id=hid, checked_at=None).count(),
                "tasks": models.Task.query.filter(
                    models.Task.household_id == hid,
                    models.Task.completed_at.is_(None),
                    models.Task.due_date <= ctx["today"],
                ).count(),
            }
        return ctx

    app.jinja_env.filters["due_label"] = lambda d: due_label(d, today_local())

    # --- Blueprints -------------------------------------------------------------
    from .auth import bp as auth_bp
    from .household import bp as household_bp
    from .shopping import bp as shopping_bp
    from .tasks import bp as tasks_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(household_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(shopping_bp)

    @app.route("/")
    def index():
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if not current_user.household_id:
            return redirect(url_for("household.setup"))
        return redirect(url_for("tasks.index"))

    # --- PWA ---------------------------------------------------------------------
    @app.route("/sw.js")
    def service_worker():
        response = send_from_directory(static_dir, "sw.js", mimetype="application/javascript")
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Service-Worker-Allowed"] = "/"
        return response

    @app.route("/manifest.webmanifest")
    def manifest():
        return render_template("manifest.json"), 200, {"Content-Type": "application/manifest+json"}

    @app.route("/offline")
    def offline():
        return render_template("offline.html", title="Offline")

    # --- Errors --------------------------------------------------------------------
    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def handle_client_error(err):
        if _wants_json():
            return jsonify(ok=False, error=getattr(err, "description", str(err))), err.code
        return render_template("error.html", title="Oops", error=err), err.code

    @app.errorhandler(500)
    def handle_server_error(err):
        db.session.rollback()
        if _wants_json():
            return jsonify(ok=False, error="Something went wrong"), 500
        return render_template("error.html", title="Oops", error=err), 500

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    # --- CLI -------------------------------------------------------------------------
    @app.cli.command("init-db")
    def init_db_command():
        """Create or upgrade the database to the latest schema (safe to re-run)."""
        from flask_migrate import upgrade

        upgrade()
        print("Database is up to date.")

    return app
