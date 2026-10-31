import os
import secrets

from flask import Blueprint, abort, current_app, jsonify, render_template, request, send_from_directory
from flask_login import current_user
from werkzeug.utils import secure_filename

from . import household_required
from .extensions import db
from .models import InfoAttachment, InfoItem
from .utils import clean_text, utcnow

bp = Blueprint("info", __name__, url_prefix="/info")

ALLOWED_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}
EXTENSION_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}
MAX_FILES_PER_REQUEST = 10


def _payload() -> dict:
    data = request.get_json(silent=True)
    if data is None:
        data = request.form.to_dict()
    return data if isinstance(data, dict) else {}


def _get_item(item_id: int) -> InfoItem:
    item = db.session.get(InfoItem, item_id)
    if item is None or item.household_id != current_user.household_id:
        abort(404)
    return item


def _get_attachment(attachment_id: int) -> InfoAttachment:
    att = db.session.get(InfoAttachment, attachment_id)
    if att is None or att.item.household_id != current_user.household_id:
        abort(404)
    return att


def household_upload_dir(household_id: int) -> str:
    path = os.path.join(current_app.config["UPLOAD_DIR"], str(household_id))
    os.makedirs(path, exist_ok=True)
    return path


def attachment_path(att: InfoAttachment) -> str:
    return os.path.join(household_upload_dir(att.item.household_id), att.stored_name)


def remove_file(att: InfoAttachment):
    try:
        os.remove(attachment_path(att))
    except FileNotFoundError:
        pass


def _detect_type(storage) -> tuple[str, str] | None:
    """Return (content_type, extension) if the upload is an allowed image/PDF, else None."""
    ext = os.path.splitext(storage.filename or "")[1].lower()
    mimetype = (storage.mimetype or "").split(";")[0].strip().lower()
    if mimetype in ALLOWED_TYPES:
        return mimetype, ALLOWED_TYPES[mimetype]
    if ext in EXTENSION_TYPES:
        return EXTENSION_TYPES[ext], ALLOWED_TYPES[EXTENSION_TYPES[ext]]
    return None


def _validate_uploads(files) -> list:
    """Return [(storage, content_type, ext)] or abort before anything is written."""
    files = [f for f in files if f and f.filename][:MAX_FILES_PER_REQUEST]
    validated = []
    for storage in files:
        detected = _detect_type(storage)
        if detected is None:
            abort(400, description=f"'{storage.filename}' isn't a supported file. Use photos (JPG, PNG, GIF, WebP) or PDFs.")
        validated.append((storage, *detected))
    return validated


def _save_uploads(item: InfoItem, validated) -> list[InfoAttachment]:
    saved = []
    directory = household_upload_dir(item.household_id)
    for storage, content_type, ext in validated:
        stored_name = secrets.token_urlsafe(18) + ext
        full_path = os.path.join(directory, stored_name)
        storage.save(full_path)
        att = InfoAttachment(
            original_name=secure_filename(storage.filename)[:255] or f"attachment{ext}",
            stored_name=stored_name,
            content_type=content_type,
            size=os.path.getsize(full_path),
        )
        item.attachments.append(att)
        saved.append(att)
    return saved


def _board_context():
    items = (
        InfoItem.query.filter_by(household_id=current_user.household_id)
        .order_by(InfoItem.updated_at.desc())
        .all()
    )
    return {"items": items, "household": current_user.household}


@bp.route("")
@household_required
def index():
    return render_template("info/index.html", title="Info", nav="info", **_board_context())


@bp.route("/list")
@household_required
def list_partial():
    return render_template("info/_board.html", **_board_context())


@bp.route("/version")
@household_required
def version():
    return jsonify(version=current_user.household.info_version)


@bp.route("", methods=["POST"])
@household_required
def create():
    data = _payload()
    title = clean_text(data.get("title"), 120)
    if not title:
        abort(400, description="Give it a title, e.g. 'Spain flights'.")
    validated = _validate_uploads(request.files.getlist("files"))
    item = InfoItem(
        household_id=current_user.household_id,
        title=title,
        notes=str(data.get("notes") or "").strip()[:5000] or None,
        created_by_id=current_user.id,
    )
    db.session.add(item)
    db.session.flush()
    _save_uploads(item, validated)
    current_user.household.touch_info()
    db.session.commit()
    return jsonify(ok=True, item=item.to_dict())


@bp.route("/<int:item_id>", methods=["POST"])
@household_required
def update(item_id):
    item = _get_item(item_id)
    data = _payload()
    validated = _validate_uploads(request.files.getlist("files"))
    if "title" in data:
        title = clean_text(data.get("title"), 120)
        if not title:
            abort(400, description="A title is required.")
        item.title = title
    if "notes" in data:
        item.notes = str(data.get("notes") or "").strip()[:5000] or None
    _save_uploads(item, validated)
    item.updated_at = utcnow()
    current_user.household.touch_info()
    db.session.commit()
    return jsonify(ok=True, item=item.to_dict())


@bp.route("/<int:item_id>/delete", methods=["POST"])
@household_required
def delete(item_id):
    item = _get_item(item_id)
    for att in list(item.attachments):
        remove_file(att)
    db.session.delete(item)
    current_user.household.touch_info()
    db.session.commit()
    return jsonify(ok=True)


@bp.route("/files/<int:attachment_id>/delete", methods=["POST"])
@household_required
def delete_attachment(attachment_id):
    att = _get_attachment(attachment_id)
    remove_file(att)
    item = att.item
    db.session.delete(att)
    item.updated_at = utcnow()
    current_user.household.touch_info()
    db.session.commit()
    return jsonify(ok=True, item=item.to_dict())


@bp.route("/files/<int:attachment_id>/<path:name>")
@household_required
def serve_attachment(attachment_id, name):
    att = _get_attachment(attachment_id)
    response = send_from_directory(
        household_upload_dir(att.item.household_id),
        att.stored_name,
        mimetype=att.content_type,
        download_name=att.original_name,
        as_attachment=request.args.get("download") == "1",
        conditional=True,
        max_age=60 * 60 * 24 * 30,
    )
    response.headers["Cache-Control"] = "private, max-age=2592000"
    return response
