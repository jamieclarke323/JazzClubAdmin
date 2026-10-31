from flask import Blueprint, abort, jsonify, make_response, render_template, request
from flask_login import current_user

from . import household_required
from .extensions import db
from .models import SHOPPING_CATEGORIES, SHOPPING_CATEGORY_KEYS, ShoppingHistory, ShoppingItem
from .utils import clean_text, normalise_name, parse_shopping_input, utcnow

bp = Blueprint("shopping", __name__, url_prefix="/shopping")

GROUP_COOKIE = "shop_group"


def _payload() -> dict:
    data = request.get_json(silent=True)
    if data is None:
        data = request.form.to_dict()
    return data if isinstance(data, dict) else {}


def _get_item(item_id: int) -> ShoppingItem:
    item = db.session.get(ShoppingItem, item_id)
    if item is None or item.household_id != current_user.household_id:
        abort(404)
    return item


def _clean_category(value, default="groceries") -> str:
    value = str(value or "").strip().lower()
    return value if value in SHOPPING_CATEGORY_KEYS else default


def _clean_quantity(value) -> str | None:
    return clean_text(value, 30) or None


def _remember(name: str, key: str, category: str, quantity: str | None):
    hist = ShoppingHistory.query.filter_by(household_id=current_user.household_id, name_key=key).first()
    if hist is None:
        hist = ShoppingHistory(household_id=current_user.household_id, name=name, name_key=key, count=0)
        db.session.add(hist)
    hist.name = name
    hist.category = category
    if quantity:
        hist.quantity = quantity
    hist.count += 1
    hist.last_used_at = utcnow()


def _board_context():
    hid = current_user.household_id
    items = ShoppingItem.query.filter_by(household_id=hid).order_by(ShoppingItem.created_at.desc()).all()
    active = [i for i in items if not i.is_checked]
    checked = sorted([i for i in items if i.is_checked], key=lambda i: i.checked_at, reverse=True)
    grouped = request.cookies.get(GROUP_COOKIE) == "1"

    if grouped:
        groups = []
        for key, label in SHOPPING_CATEGORIES:
            bucket = [i for i in active if i.category == key]
            if bucket:
                groups.append((label, bucket))
    else:
        groups = [(None, active)] if active else []

    on_list = {i.name_key for i in active}
    recent = (
        ShoppingHistory.query.filter_by(household_id=hid)
        .order_by(ShoppingHistory.last_used_at.desc())
        .limit(30)
        .all()
    )
    recent = [h for h in recent if h.name_key not in on_list][:10]

    return {
        "active_items": active,
        "checked_items": checked,
        "groups": groups,
        "grouped": grouped,
        "recent": recent,
        "remaining": len(active),
        "household": current_user.household,
    }


@bp.route("")
@household_required
def index():
    return render_template("shopping/index.html", title="Shopping", nav="shopping", **_board_context())


@bp.route("/list")
@household_required
def list_partial():
    return render_template("shopping/_board.html", **_board_context())


@bp.route("/version")
@household_required
def version():
    return jsonify(version=current_user.household.shopping_version)


@bp.route("/group", methods=["POST"])
@household_required
def toggle_group():
    enabled = request.cookies.get(GROUP_COOKIE) != "1"
    resp = make_response(jsonify(ok=True, grouped=enabled))
    resp.set_cookie(GROUP_COOKIE, "1" if enabled else "0", max_age=60 * 60 * 24 * 365, samesite="Lax")
    return resp


@bp.route("/items", methods=["POST"])
@household_required
def add_item():
    data = _payload()
    name, parsed_qty = parse_shopping_input(data.get("name") or "")
    if not name:
        abort(400, description="Type something to add.")
    quantity = _clean_quantity(data.get("quantity")) or parsed_qty
    key = normalise_name(name)
    hid = current_user.household_id
    household = current_user.household

    existing = ShoppingItem.query.filter_by(household_id=hid, name_key=key).order_by(ShoppingItem.checked_at.asc()).all()
    active = next((i for i in existing if not i.is_checked), None)
    if active is not None:
        if quantity and quantity != active.quantity:
            active.quantity = quantity
            household.touch_shopping()
            db.session.commit()
        return jsonify(ok=True, status="exists", item=active.to_dict())

    history = ShoppingHistory.query.filter_by(household_id=hid, name_key=key).first()
    category = _clean_category(data.get("category"), default=history.category if history else "groceries")

    checked = next((i for i in existing if i.is_checked), None)
    if checked is not None:
        checked.checked_at = None
        checked.name = name
        checked.quantity = quantity
        checked.category = category
        checked.added_by_id = current_user.id
        checked.created_at = utcnow()
        item, status = checked, "restored"
    else:
        item = ShoppingItem(
            household_id=hid,
            name=name,
            name_key=key,
            quantity=quantity,
            category=category,
            added_by_id=current_user.id,
        )
        db.session.add(item)
        status = "added"

    _remember(name, key, category, quantity)
    household.touch_shopping()
    db.session.commit()
    return jsonify(ok=True, status=status, item=item.to_dict())


@bp.route("/items/<int:item_id>", methods=["POST"])
@household_required
def update_item(item_id):
    item = _get_item(item_id)
    data = _payload()
    if "name" in data:
        name = clean_text(data.get("name"), 120)
        if not name:
            abort(400, description="Name can't be empty.")
        item.name = name
        item.name_key = normalise_name(name)
    if "quantity" in data:
        item.quantity = _clean_quantity(data.get("quantity"))
    if "category" in data:
        item.category = _clean_category(data.get("category"), default=item.category)
    hist = ShoppingHistory.query.filter_by(household_id=item.household_id, name_key=item.name_key).first()
    if hist is not None:
        hist.category = item.category
        hist.name = item.name
    current_user.household.touch_shopping()
    db.session.commit()
    return jsonify(ok=True, item=item.to_dict())


@bp.route("/items/<int:item_id>/toggle", methods=["POST"])
@household_required
def toggle_item(item_id):
    item = _get_item(item_id)
    item.checked_at = None if item.is_checked else utcnow()
    current_user.household.touch_shopping()
    db.session.commit()
    return jsonify(ok=True, item=item.to_dict())


@bp.route("/items/<int:item_id>/delete", methods=["POST"])
@household_required
def delete_item(item_id):
    item = _get_item(item_id)
    db.session.delete(item)
    current_user.household.touch_shopping()
    db.session.commit()
    return jsonify(ok=True)


@bp.route("/clear-checked", methods=["POST"])
@household_required
def clear_checked():
    deleted = ShoppingItem.query.filter(
        ShoppingItem.household_id == current_user.household_id, ShoppingItem.checked_at.isnot(None)
    ).delete(synchronize_session=False)
    current_user.household.touch_shopping()
    db.session.commit()
    return jsonify(ok=True, deleted=deleted)


@bp.route("/suggest")
@household_required
def suggest():
    q = normalise_name(request.args.get("q", ""))
    if len(q) < 1:
        return jsonify(suggestions=[])
    hid = current_user.household_id
    rows = (
        ShoppingHistory.query.filter(ShoppingHistory.household_id == hid, ShoppingHistory.name_key.contains(q))
        .order_by(ShoppingHistory.count.desc(), ShoppingHistory.last_used_at.desc())
        .limit(6)
        .all()
    )
    on_list = {
        i.name_key
        for i in ShoppingItem.query.filter_by(household_id=hid, checked_at=None).with_entities(ShoppingItem.name_key)
    }
    return jsonify(
        suggestions=[
            {"name": h.name, "category": h.category, "quantity": h.quantity or "", "on_list": h.name_key in on_list}
            for h in rows
        ]
    )
