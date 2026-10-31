from flask import Blueprint, abort, jsonify, render_template, request
from flask_login import current_user

from . import household_required
from .extensions import db
from .models import Task, User
from .utils import RECURRENCES, clean_text, next_occurrence, parse_date, today_local, utcnow

bp = Blueprint("tasks", __name__, url_prefix="/tasks")

VIEWS = {
    "mine": "Mine",
    "all": "All",
    "today": "Today",
    "upcoming": "Upcoming",
    "overdue": "Overdue",
    "done": "Done",
}


def _payload() -> dict:
    data = request.get_json(silent=True)
    if data is None:
        data = request.form.to_dict()
    return data if isinstance(data, dict) else {}


def _get_task(task_id: int) -> Task:
    task = db.session.get(Task, task_id)
    if task is None or task.household_id != current_user.household_id:
        abort(404)
    return task


def _active_query():
    return Task.query.filter(Task.household_id == current_user.household_id, Task.completed_at.is_(None))


def _filtered_tasks(view: str, who: str, today):
    if view == "done":
        q = Task.query.filter(Task.household_id == current_user.household_id, Task.completed_at.isnot(None))
    else:
        q = _active_query()
        if view == "mine":
            q = q.filter(Task.assignee_id == current_user.id)
        elif view == "today":
            q = q.filter(Task.due_date <= today)
        elif view == "upcoming":
            q = q.filter(Task.due_date > today)
        elif view == "overdue":
            q = q.filter(Task.due_date < today)

    if who == "unassigned":
        q = q.filter(Task.assignee_id.is_(None))
    elif who.isdigit():
        q = q.filter(Task.assignee_id == int(who))

    if view == "done":
        return q.order_by(Task.completed_at.desc()).limit(100).all()
    return q.order_by(
        Task.due_date.is_(None), Task.due_date.asc(), Task.priority.desc(), Task.created_at.asc()
    ).all()


def _counts(today) -> dict:
    active = _active_query().all()
    return {
        "mine": sum(1 for t in active if t.assignee_id == current_user.id),
        "all": len(active),
        "today": sum(1 for t in active if t.due_date and t.due_date <= today),
        "upcoming": sum(1 for t in active if t.due_date and t.due_date > today),
        "overdue": sum(1 for t in active if t.due_date and t.due_date < today),
    }


def _group(tasks, view, today):
    """Split a flat list into labelled sections for the list views."""
    if view in ("done", "overdue", "today", "upcoming"):
        return [(None, tasks)]
    buckets = {"Overdue": [], "Today": [], "Upcoming": [], "No date": []}
    for t in tasks:
        if t.due_date is None:
            buckets["No date"].append(t)
        elif t.due_date < today:
            buckets["Overdue"].append(t)
        elif t.due_date == today:
            buckets["Today"].append(t)
        else:
            buckets["Upcoming"].append(t)
    return [(label, items) for label, items in buckets.items() if items]


def _board_context():
    view = request.args.get("view", "mine")
    if view not in VIEWS:
        view = "mine"
    who = request.args.get("who", "") or ""
    today = today_local()
    tasks = _filtered_tasks(view, who, today)
    household = current_user.household
    return {
        "view": view,
        "who": who,
        "VIEWS": VIEWS,
        "tasks": tasks,
        "groups": _group(tasks, view, today),
        "counts": _counts(today),
        "household": household,
        "members": household.members,
        "categories": _categories(),
    }


def _categories():
    rows = (
        db.session.query(Task.category)
        .filter(Task.household_id == current_user.household_id, Task.category.isnot(None))
        .distinct()
        .all()
    )
    return sorted({r[0] for r in rows if r[0]}, key=str.casefold)


def _apply_fields(task: Task, data: dict, partial: bool):
    if "title" in data or not partial:
        title = clean_text(data.get("title"), 200)
        if not title:
            abort(400, description="A title is required.")
        task.title = title
    if "description" in data:
        task.description = str(data.get("description") or "").strip()[:2000] or None
    if "assignee_id" in data:
        raw = str(data.get("assignee_id") or "").strip()
        if raw:
            member = db.session.get(User, int(raw)) if raw.isdigit() else None
            if member is None or member.household_id != current_user.household_id:
                abort(400, description="That person isn't in your household.")
            task.assignee_id = member.id
        else:
            task.assignee_id = None
    if "due_date" in data:
        raw = str(data.get("due_date") or "").strip()
        if raw:
            due = parse_date(raw)
            if due is None:
                abort(400, description="Invalid date.")
            task.due_date = due
        else:
            task.due_date = None
    if "priority" in data:
        try:
            task.priority = min(3, max(0, int(data.get("priority") or 0)))
        except ValueError:
            task.priority = 0
    if "category" in data:
        task.category = clean_text(data.get("category"), 40) or None
    if "recurrence" in data:
        rec = str(data.get("recurrence") or "").strip()
        task.recurrence = rec if rec in RECURRENCES else None


@bp.route("")
@household_required
def index():
    ctx = _board_context()
    return render_template("tasks/index.html", title="Tasks", nav="tasks", **ctx)


@bp.route("/list")
@household_required
def list_partial():
    ctx = _board_context()
    return render_template("tasks/_board.html", **ctx)


@bp.route("/version")
@household_required
def version():
    return jsonify(version=current_user.household.tasks_version)


@bp.route("", methods=["POST"])
@household_required
def create():
    data = _payload()
    task = Task(household_id=current_user.household_id, created_by_id=current_user.id)
    _apply_fields(task, data, partial=False)
    db.session.add(task)
    current_user.household.touch_tasks()
    db.session.commit()
    return jsonify(ok=True, task=task.to_dict())


@bp.route("/<int:task_id>", methods=["POST"])
@household_required
def update(task_id):
    task = _get_task(task_id)
    _apply_fields(task, _payload(), partial=True)
    current_user.household.touch_tasks()
    db.session.commit()
    return jsonify(ok=True, task=task.to_dict())


@bp.route("/<int:task_id>/complete", methods=["POST"])
@household_required
def complete(task_id):
    task = _get_task(task_id)
    if task.completed_at is None:
        task.completed_at = utcnow()
        if task.recurrence and task.spawned_task_id is None:
            nxt = Task(
                household_id=task.household_id,
                title=task.title,
                description=task.description,
                assignee_id=task.assignee_id,
                created_by_id=current_user.id,
                priority=task.priority,
                category=task.category,
                recurrence=task.recurrence,
                due_date=next_occurrence(task.due_date, task.recurrence, today_local()),
            )
            db.session.add(nxt)
            db.session.flush()
            task.spawned_task_id = nxt.id
        current_user.household.touch_tasks()
        db.session.commit()
    return jsonify(ok=True, task=task.to_dict())


@bp.route("/<int:task_id>/uncomplete", methods=["POST"])
@household_required
def uncomplete(task_id):
    task = _get_task(task_id)
    if task.completed_at is not None:
        task.completed_at = None
        if task.spawned_task_id:
            spawned = db.session.get(Task, task.spawned_task_id)
            if (
                spawned is not None
                and spawned.household_id == task.household_id
                and spawned.completed_at is None
            ):
                db.session.delete(spawned)
            task.spawned_task_id = None
        current_user.household.touch_tasks()
        db.session.commit()
    return jsonify(ok=True, task=task.to_dict())


@bp.route("/<int:task_id>/delete", methods=["POST"])
@household_required
def delete(task_id):
    task = _get_task(task_id)
    db.session.delete(task)
    current_user.household.touch_tasks()
    db.session.commit()
    return jsonify(ok=True)
