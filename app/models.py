import secrets
from datetime import date

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db
from .utils import utcnow

PALETTE = ["#2563eb", "#db2777", "#059669", "#d97706", "#7c3aed", "#0891b2", "#dc2626", "#65a30d"]

SHOPPING_CATEGORIES = [
    ("groceries", "Groceries"),
    ("household", "Household"),
    ("toiletries", "Toiletries"),
    ("other", "Other"),
]
SHOPPING_CATEGORY_KEYS = [key for key, _ in SHOPPING_CATEGORIES]


def new_invite_code() -> str:
    return secrets.token_urlsafe(9)


class Household(db.Model):
    __tablename__ = "households"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    invite_code = db.Column(db.String(32), unique=True, nullable=False, index=True, default=new_invite_code)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    # Bumped on every change so clients can cheaply poll for updates.
    tasks_version = db.Column(db.Integer, nullable=False, default=0)
    shopping_version = db.Column(db.Integer, nullable=False, default=0)
    info_version = db.Column(db.Integer, nullable=False, default=0)

    members = db.relationship("User", back_populates="household", order_by="User.created_at")
    tasks = db.relationship("Task", back_populates="household", cascade="all, delete-orphan")
    shopping_items = db.relationship("ShoppingItem", back_populates="household", cascade="all, delete-orphan")
    shopping_history = db.relationship("ShoppingHistory", back_populates="household", cascade="all, delete-orphan")
    info_items = db.relationship("InfoItem", back_populates="household", cascade="all, delete-orphan")

    def regenerate_invite(self):
        self.invite_code = new_invite_code()

    def touch_tasks(self):
        self.tasks_version = (self.tasks_version or 0) + 1

    def touch_shopping(self):
        self.shopping_version = (self.shopping_version or 0) + 1

    def touch_info(self):
        self.info_version = (self.info_version or 0) + 1


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(40), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    household_id = db.Column(db.Integer, db.ForeignKey("households.id", ondelete="SET NULL"), index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    household = db.relationship("Household", back_populates="members")

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def initials(self) -> str:
        parts = self.display_name.split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        return self.display_name[:1].upper()

    @property
    def color(self) -> str:
        return PALETTE[(self.id or 0) % len(PALETTE)]

    def to_dict(self):
        return {"id": self.id, "name": self.display_name, "initials": self.initials, "color": self.color}


class Task(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    household_id = db.Column(db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    assignee_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    due_date = db.Column(db.Date, index=True)
    priority = db.Column(db.SmallInteger, nullable=False, default=0)
    category = db.Column(db.String(40))
    recurrence = db.Column(db.String(12))
    completed_at = db.Column(db.DateTime, index=True)
    # Set when completing a recurring task so the next occurrence is created exactly once
    # and can be removed again if the completion is undone.
    spawned_task_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    household = db.relationship("Household", back_populates="tasks")
    assignee = db.relationship("User", foreign_keys=[assignee_id])
    created_by = db.relationship("User", foreign_keys=[created_by_id])

    @property
    def is_done(self) -> bool:
        return self.completed_at is not None

    def is_overdue(self, today: date) -> bool:
        return self.due_date is not None and self.completed_at is None and self.due_date < today

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description or "",
            "assignee_id": self.assignee_id,
            "due_date": self.due_date.isoformat() if self.due_date else "",
            "priority": self.priority or 0,
            "category": self.category or "",
            "recurrence": self.recurrence or "",
            "done": self.is_done,
        }


class ShoppingItem(db.Model):
    __tablename__ = "shopping_items"

    id = db.Column(db.Integer, primary_key=True)
    household_id = db.Column(db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    name_key = db.Column(db.String(120), nullable=False, index=True)
    quantity = db.Column(db.String(30))
    category = db.Column(db.String(20), nullable=False, default="groceries")
    checked_at = db.Column(db.DateTime, index=True)
    added_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    household = db.relationship("Household", back_populates="shopping_items")

    @property
    def is_checked(self) -> bool:
        return self.checked_at is not None

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "quantity": self.quantity or "",
            "category": self.category,
            "checked": self.is_checked,
        }


class ShoppingHistory(db.Model):
    """Remembers what a household buys, powering suggestions and one-tap re-adds."""

    __tablename__ = "shopping_history"
    __table_args__ = (db.UniqueConstraint("household_id", "name_key", name="uq_history_household_name"),)

    id = db.Column(db.Integer, primary_key=True)
    household_id = db.Column(db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    name_key = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(20), nullable=False, default="groceries")
    quantity = db.Column(db.String(30))
    count = db.Column(db.Integer, nullable=False, default=1)
    last_used_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    household = db.relationship("Household", back_populates="shopping_history")


class InfoItem(db.Model):
    """A piece of household reference info: flight details, insurance docs, wifi password..."""

    __tablename__ = "info_items"

    id = db.Column(db.Integer, primary_key=True)
    household_id = db.Column(db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(120), nullable=False)
    notes = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    household = db.relationship("Household", back_populates="info_items")
    created_by = db.relationship("User")
    attachments = db.relationship(
        "InfoAttachment", back_populates="item", cascade="all, delete-orphan", order_by="InfoAttachment.created_at"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "notes": self.notes or "",
            "attachments": [a.to_dict() for a in self.attachments],
        }


class InfoAttachment(db.Model):
    __tablename__ = "info_attachments"

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("info_items.id", ondelete="CASCADE"), nullable=False, index=True)
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(80), nullable=False, unique=True)
    content_type = db.Column(db.String(80), nullable=False)
    size = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    item = db.relationship("InfoItem", back_populates="attachments")

    @property
    def is_image(self) -> bool:
        return self.content_type.startswith("image/")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.original_name,
            "is_image": self.is_image,
            "size": self.size,
        }
