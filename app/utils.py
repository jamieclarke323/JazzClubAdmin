import calendar
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import current_app

RECURRENCES = {
    "daily": "Every day",
    "weekly": "Every week",
    "fortnightly": "Every 2 weeks",
    "monthly": "Every month",
    "yearly": "Every year",
}

PRIORITIES = {0: "None", 1: "Low", 2: "Medium", 3: "High"}

RECURRENCE_SHORT = {
    "daily": "Daily",
    "weekly": "Weekly",
    "fortnightly": "Fortnightly",
    "monthly": "Monthly",
    "yearly": "Yearly",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def today_local() -> date:
    tz = ZoneInfo(current_app.config.get("TIMEZONE", "UTC"))
    return datetime.now(tz).date()


def add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def advance(d: date, recurrence: str) -> date:
    if recurrence == "daily":
        return d + timedelta(days=1)
    if recurrence == "weekly":
        return d + timedelta(days=7)
    if recurrence == "fortnightly":
        return d + timedelta(days=14)
    if recurrence == "monthly":
        return add_months(d, 1)
    if recurrence == "yearly":
        return add_months(d, 12)
    raise ValueError(f"Unknown recurrence: {recurrence}")


def next_occurrence(due: date | None, recurrence: str, today: date) -> date:
    """Next due date after completing a recurring task.

    Keeps the original schedule anchor (e.g. "every Monday") but never
    schedules the next occurrence in the past or for today.
    """
    base = due or today
    nxt = advance(base, recurrence)
    while nxt <= today:
        nxt = advance(nxt, recurrence)
    return nxt


def parse_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def due_label(d: date | None, today: date | None = None) -> str:
    if d is None:
        return ""
    today = today or today_local()
    delta = (d - today).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    if delta == -1:
        return "Yesterday"
    if delta < -1:
        return f"{-delta} days overdue"
    if delta < 7:
        return d.strftime("%A")
    if d.year == today.year:
        return f"{d.strftime('%a')} {d.day} {d.strftime('%b')}"
    return f"{d.day} {d.strftime('%b %Y')}"


def normalise_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def clean_text(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


_QTY_SUFFIX = re.compile(r"^(?P<name>.+?)\s*[x×]\s*(?P<qty>\d+(?:[.,]\d+)?)$", re.IGNORECASE)
_QTY_PREFIX = re.compile(r"^(?P<qty>\d+(?:[.,]\d+)?)\s*[x×]\s*(?P<name>.+)$", re.IGNORECASE)


def parse_shopping_input(raw: str) -> tuple[str, str | None]:
    """'Milk x2' or '2x Milk' -> ('Milk', '2'). Anything else -> (raw, None)."""
    text = clean_text(raw, 160)
    for pattern in (_QTY_SUFFIX, _QTY_PREFIX):
        m = pattern.match(text)
        if m:
            return clean_text(m.group("name"), 120), m.group("qty")
    return text[:120], None
