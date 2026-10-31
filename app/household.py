from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from . import household_required
from .extensions import db
from .models import Household, Task
from .utils import clean_text

bp = Blueprint("household", __name__, url_prefix="/household")


@bp.route("/setup")
@login_required
def setup():
    if current_user.household_id:
        return redirect(url_for("household.home"))
    if session.get("pending_invite"):
        return redirect(url_for("household.join_code", code=session["pending_invite"]))
    return render_template("household/setup.html", title="Set up your household")


@bp.route("/new", methods=["POST"])
@login_required
def create():
    if current_user.household_id:
        flash("You're already in a household.", "error")
        return redirect(url_for("household.home"))
    name = clean_text(request.form.get("name"), 80) or f"{current_user.display_name}'s home"
    household = Household(name=name)
    db.session.add(household)
    db.session.flush()
    current_user.household_id = household.id
    db.session.commit()
    flash(f"Welcome to {household.name}! Invite someone from the Household tab.", "success")
    return redirect(url_for("tasks.index"))


@bp.route("/join", methods=["POST"])
@login_required
def join_form():
    code = clean_text(request.form.get("code"), 64)
    if "/" in code:
        code = code.rstrip("/").rsplit("/", 1)[-1]
    return redirect(url_for("household.join_code", code=code))


@bp.route("/join/<code>")
def join_code(code):
    household = Household.query.filter_by(invite_code=code).first()
    if household is None:
        session.pop("pending_invite", None)
        flash("That invite link isn't valid any more. Ask for a new one.", "error")
        return redirect(url_for("index"))

    if not current_user.is_authenticated:
        session["pending_invite"] = code
        flash(f"You've been invited to join {household.name}. Create an account or log in to continue.", "info")
        return redirect(url_for("auth.register"))

    session.pop("pending_invite", None)
    if current_user.household_id == household.id:
        return redirect(url_for("tasks.index"))
    if current_user.household_id:
        flash("Leave your current household before joining another one.", "error")
        return redirect(url_for("household.home"))

    current_user.household_id = household.id
    db.session.commit()
    flash(f"You've joined {household.name}.", "success")
    return redirect(url_for("tasks.index"))


@bp.route("")
@household_required
def home():
    household = current_user.household
    invite_url = url_for("household.join_code", code=household.invite_code, _external=True)
    return render_template(
        "household/home.html",
        title="Household",
        nav="household",
        household=household,
        invite_url=invite_url,
    )


@bp.route("/rename", methods=["POST"])
@household_required
def rename():
    name = clean_text(request.form.get("name"), 80)
    if name:
        current_user.household.name = name
        db.session.commit()
        flash("Household renamed.", "success")
    return redirect(url_for("household.home"))


@bp.route("/regenerate-invite", methods=["POST"])
@household_required
def regenerate_invite():
    current_user.household.regenerate_invite()
    db.session.commit()
    flash("New invite link created. The old one no longer works.", "success")
    return redirect(url_for("household.home"))


@bp.route("/leave", methods=["POST"])
@household_required
def leave():
    if request.form.get("confirm") != "yes":
        flash("Please confirm that you want to leave.", "error")
        return redirect(url_for("household.home"))

    household = current_user.household
    others = [m for m in household.members if m.id != current_user.id]

    if others:
        Task.query.filter_by(household_id=household.id, assignee_id=current_user.id).update({"assignee_id": None})
        household.touch_tasks()
        current_user.household_id = None
        db.session.commit()
        flash(f"You've left {household.name}.", "info")
    else:
        from .info import remove_file

        for item in household.info_items:
            for att in item.attachments:
                remove_file(att)
        current_user.household_id = None
        db.session.flush()
        db.session.delete(household)
        db.session.commit()
        flash("Household deleted.", "info")
    return redirect(url_for("household.setup"))


@bp.route("/account", methods=["POST"])
@login_required
def account():
    action = request.form.get("action")
    if action == "name":
        name = clean_text(request.form.get("display_name"), 40)
        if not name:
            flash("Display name can't be empty.", "error")
        else:
            current_user.display_name = name
            db.session.commit()
            flash("Name updated.", "success")
    elif action == "password":
        current = request.form.get("current_password") or ""
        new = request.form.get("new_password") or ""
        if not current_user.check_password(current):
            flash("Current password is incorrect.", "error")
        elif len(new) < 8:
            flash("New password must be at least 8 characters.", "error")
        else:
            current_user.set_password(new)
            db.session.commit()
            flash("Password changed.", "success")
    return redirect(url_for("household.home") if current_user.household_id else url_for("household.setup"))
