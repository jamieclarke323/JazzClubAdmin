from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from urllib.parse import urlparse

from .extensions import db
from .models import User
from .utils import clean_text

bp = Blueprint("auth", __name__, url_prefix="/auth")


def _safe_next(target: str | None) -> str | None:
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/"):
        return None
    return target


def _after_login_redirect():
    if session.get("pending_invite"):
        return redirect(url_for("household.join_code", code=session["pending_invite"]))
    return redirect(_safe_next(request.args.get("next")) or url_for("index"))


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return _after_login_redirect()

    registration_open = current_app.config["ALLOW_REGISTRATION"] or bool(session.get("pending_invite"))
    if not registration_open:
        flash("Registration is by invitation only. Ask a household member for an invite link.", "error")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        email = clean_text(request.form.get("email"), 255).lower()
        name = clean_text(request.form.get("display_name"), 40)
        password = request.form.get("password") or ""

        error = None
        if "@" not in email or len(email) < 5:
            error = "Please enter a valid email address."
        elif not name:
            error = "Please tell us what to call you."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif User.query.filter_by(email=email).first():
            error = "An account with that email already exists. Try logging in."

        if error:
            flash(error, "error")
            return render_template("auth/register.html", title="Create account", email=email, display_name=name), 400

        user = User(email=email, display_name=name)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user, remember=True)
        return _after_login_redirect()

    return render_template("auth/register.html", title="Create account")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return _after_login_redirect()

    if request.method == "POST":
        email = clean_text(request.form.get("email"), 255).lower()
        password = request.form.get("password") or ""
        user = User.query.filter_by(email=email).first()
        if user is None or not user.check_password(password):
            flash("Email or password is incorrect.", "error")
            return render_template("auth/login.html", title="Log in", email=email), 401
        login_user(user, remember=True)
        return _after_login_redirect()

    return render_template("auth/login.html", title="Log in")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for("auth.login"))
