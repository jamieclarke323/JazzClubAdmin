from datetime import date, timedelta

import pytest

from app import create_app
from app.extensions import db
from app.models import Household, ShoppingItem, Task, User
from app.utils import add_months, next_occurrence, parse_shopping_input
from config import TestConfig


@pytest.fixture()
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def register(client, email, name="Sam", password="password123"):
    return client.post(
        "/auth/register",
        data={"email": email, "display_name": name, "password": password},
        follow_redirects=True,
    )


def login(client, email, password="password123"):
    return client.post("/auth/login", data={"email": email, "password": password}, follow_redirects=True)


def logout(client):
    return client.post("/auth/logout", follow_redirects=True)


def setup_household(client, email="a@example.com", name="Alex", household="Home"):
    register(client, email, name)
    client.post("/household/new", data={"name": household}, follow_redirects=True)
    return User.query.filter_by(email=email).first()


# --- utils --------------------------------------------------------------------


def test_add_months_clamps_day():
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months(date(2024, 12, 15), 1) == date(2025, 1, 15)


def test_next_occurrence_skips_past_dates():
    today = date(2025, 6, 10)
    assert next_occurrence(date(2025, 6, 10), "daily", today) == date(2025, 6, 11)
    # Overdue weekly task keeps its weekday anchor but moves into the future.
    assert next_occurrence(date(2025, 5, 20), "weekly", today) == date(2025, 6, 17)
    assert next_occurrence(None, "monthly", today) == date(2025, 7, 10)


def test_parse_shopping_input():
    assert parse_shopping_input("Milk x2") == ("Milk", "2")
    assert parse_shopping_input("3 x eggs") == ("eggs", "3")
    assert parse_shopping_input("  Bread  ") == ("Bread", None)


# --- auth & household ------------------------------------------------------------


def test_register_login_and_household_flow(client):
    rv = register(client, "a@example.com", "Alex")
    assert b"Set up your household" in rv.data
    rv = client.post("/household/new", data={"name": "Our flat"}, follow_redirects=True)
    assert b"Our flat" in rv.data or b"Tasks" in rv.data
    user = User.query.filter_by(email="a@example.com").first()
    assert user.household is not None

    logout(client)
    rv = login(client, "a@example.com")
    assert b"Tasks" in rv.data


def test_invite_link_joins_household(client):
    setup_household(client)
    code = Household.query.first().invite_code
    logout(client)

    rv = client.get(f"/household/join/{code}", follow_redirects=True)
    assert b"Create your account" in rv.data
    register(client, "b@example.com", "Bo")
    user_b = User.query.filter_by(email="b@example.com").first()
    assert user_b.household_id == Household.query.first().id


def test_invalid_invite_code_rejected(client):
    rv = client.get("/household/join/nope", follow_redirects=True)
    assert b"valid any more" in rv.data


def test_registration_can_be_closed_but_invites_still_work(app, client):
    app.config["ALLOW_REGISTRATION"] = False
    rv = client.get("/auth/register", follow_redirects=True)
    assert b"invitation only" in rv.data

    app.config["ALLOW_REGISTRATION"] = True
    setup_household(client)
    code = Household.query.first().invite_code
    logout(client)
    app.config["ALLOW_REGISTRATION"] = False
    client.get(f"/household/join/{code}")
    rv = register(client, "c@example.com", "Cy")
    assert User.query.filter_by(email="c@example.com").first().household_id is not None


def test_leaving_household_unassigns_tasks_or_deletes(client):
    user = setup_household(client)
    hid = user.household_id
    client.post("/tasks", json={"title": "Bins", "assignee_id": user.id})

    # Second member joins then leaves: their tasks become unassigned.
    code = db.session.get(Household, hid).invite_code
    logout(client)
    client.get(f"/household/join/{code}")
    register(client, "b@example.com", "Bo")
    bo = User.query.filter_by(email="b@example.com").first()
    client.post("/tasks", json={"title": "Dentist", "assignee_id": bo.id})
    client.post("/household/leave", data={"confirm": "yes"})
    assert Task.query.filter_by(title="Dentist").first().assignee_id is None
    assert db.session.get(Household, hid) is not None

    # Last member leaving deletes everything.
    logout(client)
    login(client, "a@example.com")
    client.post("/household/leave", data={"confirm": "yes"})
    assert db.session.get(Household, hid) is None
    assert Task.query.count() == 0


# --- tasks ------------------------------------------------------------------------


def test_task_crud_and_views(client):
    user = setup_household(client)
    today = date.today()
    rv = client.post(
        "/tasks",
        json={"title": "Take bins out", "assignee_id": user.id, "due_date": today.isoformat(), "priority": 3},
    )
    assert rv.status_code == 200
    task_id = rv.get_json()["task"]["id"]
    client.post("/tasks", json={"title": "Someday", "due_date": (today - timedelta(days=2)).isoformat()})

    assert b"Take bins out" in client.get("/tasks?view=mine").data
    assert b"Take bins out" in client.get("/tasks?view=today").data
    assert b"Someday" in client.get("/tasks?view=overdue").data
    assert b"Someday" not in client.get("/tasks?view=mine").data

    client.post(f"/tasks/{task_id}", json={"title": "Take the bins out", "assignee_id": ""})
    task = db.session.get(Task, task_id)
    assert task.title == "Take the bins out" and task.assignee_id is None

    client.post(f"/tasks/{task_id}/complete")
    assert db.session.get(Task, task_id).is_done
    assert b"Take the bins out" in client.get("/tasks?view=done").data
    client.post(f"/tasks/{task_id}/uncomplete")
    assert not db.session.get(Task, task_id).is_done

    client.post(f"/tasks/{task_id}/delete")
    assert db.session.get(Task, task_id) is None


def test_task_requires_title_and_valid_assignee(client):
    setup_household(client)
    assert client.post("/tasks", json={"title": "   "}).status_code == 400
    assert client.post("/tasks", json={"title": "x", "assignee_id": 999}).status_code == 400
    assert client.post("/tasks", json={"title": "x", "due_date": "not-a-date"}).status_code == 400


def test_recurring_task_spawns_next_once_and_undo_removes_it(client):
    setup_household(client)
    today = date.today()
    rv = client.post("/tasks", json={"title": "Change sheets", "recurrence": "weekly", "due_date": today.isoformat()})
    task_id = rv.get_json()["task"]["id"]

    client.post(f"/tasks/{task_id}/complete")
    client.post(f"/tasks/{task_id}/complete")  # idempotent
    active = Task.query.filter(Task.completed_at.is_(None)).all()
    assert len(active) == 1
    assert active[0].due_date == today + timedelta(days=7)
    assert active[0].recurrence == "weekly"

    client.post(f"/tasks/{task_id}/uncomplete")
    assert Task.query.count() == 1
    assert db.session.get(Task, task_id).spawned_task_id is None


def test_household_isolation(client):
    setup_household(client, "a@example.com", "Alex", "House A")
    rv = client.post("/tasks", json={"title": "Secret A"})
    task_a = rv.get_json()["task"]["id"]
    rv = client.post("/shopping/items", json={"name": "Caviar"})
    item_a = rv.get_json()["item"]["id"]
    logout(client)

    setup_household(client, "b@example.com", "Bo", "House B")
    assert b"Secret A" not in client.get("/tasks?view=all").data
    assert b"Caviar" not in client.get("/shopping").data
    assert client.post(f"/tasks/{task_a}/complete").status_code == 404
    assert client.post(f"/tasks/{task_a}", json={"title": "pwned"}).status_code == 404
    assert client.post(f"/shopping/items/{item_a}/toggle").status_code == 404
    assert client.post(f"/shopping/items/{item_a}/delete").status_code == 404
    assert db.session.get(Task, task_a).title == "Secret A"


def test_requires_login_and_household(client):
    rv = client.get("/tasks")
    assert rv.status_code == 302 and "/auth/login" in rv.headers["Location"]
    rv = client.post("/tasks", json={"title": "x"})
    assert rv.status_code == 401

    register(client, "solo@example.com", "Solo")
    rv = client.get("/shopping")
    assert rv.status_code == 302 and "/household/setup" in rv.headers["Location"]


# --- shopping -----------------------------------------------------------------------


def test_shopping_add_dedupe_restore_and_clear(client):
    setup_household(client)
    rv = client.post("/shopping/items", json={"name": "Milk x2"})
    data = rv.get_json()
    assert data["status"] == "added" and data["item"]["quantity"] == "2"
    item_id = data["item"]["id"]

    rv = client.post("/shopping/items", json={"name": "  milk "})
    assert rv.get_json()["status"] == "exists"
    assert ShoppingItem.query.count() == 1

    client.post(f"/shopping/items/{item_id}/toggle")
    assert db.session.get(ShoppingItem, item_id).is_checked

    rv = client.post("/shopping/items", json={"name": "Milk"})
    assert rv.get_json()["status"] == "restored"
    assert not db.session.get(ShoppingItem, item_id).is_checked
    assert ShoppingItem.query.count() == 1

    client.post(f"/shopping/items/{item_id}", json={"name": "Oat milk", "category": "groceries", "quantity": ""})
    assert db.session.get(ShoppingItem, item_id).name == "Oat milk"

    client.post(f"/shopping/items/{item_id}/toggle")
    rv = client.post("/shopping/clear-checked")
    assert rv.get_json()["deleted"] == 1
    assert ShoppingItem.query.count() == 0


def test_shopping_suggestions_and_recent(client):
    setup_household(client)
    client.post("/shopping/items", json={"name": "Bananas", "category": "groceries"})
    client.post("/shopping/items", json={"name": "Bin bags", "category": "household"})
    rv = client.get("/shopping/suggest?q=b")
    names = {s["name"]: s for s in rv.get_json()["suggestions"]}
    assert names["Bananas"]["on_list"] is True
    assert names["Bin bags"]["category"] == "household"

    item = ShoppingItem.query.filter_by(name="Bin bags").first()
    client.post(f"/shopping/items/{item.id}/delete")
    rv = client.get("/shopping")
    assert b"+ Bin bags" in rv.data  # recent chip shows items not currently on the list
    assert b"+ Bananas" not in rv.data

    # Re-adding without a category reuses the remembered one.
    rv = client.post("/shopping/items", json={"name": "bin bags"})
    assert rv.get_json()["item"]["category"] == "household"


def test_grouping_cookie(client):
    setup_household(client)
    client.post("/shopping/items", json={"name": "Soap", "category": "toiletries"})
    rv = client.post("/shopping/group")
    assert rv.get_json()["grouped"] is True
    assert b"Toiletries</h3>" in client.get("/shopping").data


def test_csrf_enforced_when_enabled(app, client):
    app.config["CSRF_ENABLED"] = True
    rv = client.post("/auth/login", data={"email": "x@example.com", "password": "nope"})
    assert rv.status_code == 400
    client.get("/auth/login")  # sets the token
    with client.session_transaction() as sess:
        token = sess["_csrf"]
    rv = client.post("/auth/login", data={"email": "x@example.com", "password": "nope", "csrf_token": token})
    assert rv.status_code == 401


# --- info ---------------------------------------------------------------------------

import io
import os

from app.models import InfoAttachment, InfoItem

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7V\xbd\xfa\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_info_item_with_photo_upload_view_and_delete(app, client):
    setup_household(client)
    rv = client.post(
        "/info",
        data={
            "title": "Spain flights",
            "notes": "BA2712 · ref ABC123",
            "files": [(io.BytesIO(PNG_BYTES), "flights.png"), (io.BytesIO(b"%PDF-1.4 fake"), "boarding.pdf")],
        },
        content_type="multipart/form-data",
    )
    assert rv.status_code == 200, rv.data
    item = rv.get_json()["item"]
    assert len(item["attachments"]) == 2
    photo = next(a for a in item["attachments"] if a["is_image"])
    att = db.session.get(InfoAttachment, photo["id"])
    path = os.path.join(app.config["UPLOAD_DIR"], str(att.item.household_id), att.stored_name)
    assert os.path.exists(path)

    page = client.get("/info")
    assert b"Spain flights" in page.data and b"ABC123" in page.data
    served = client.get(f"/info/files/{att.id}/flights.png")
    assert served.status_code == 200
    assert served.data == PNG_BYTES
    assert served.mimetype == "image/png"

    rv = client.post(f"/info/{item['id']}", data={"title": "Spain flights (Sept)", "notes": ""}, content_type="multipart/form-data")
    assert rv.get_json()["item"]["title"] == "Spain flights (Sept)"

    client.post(f"/info/files/{att.id}/delete")
    assert not os.path.exists(path)
    assert db.session.get(InfoAttachment, att.id) is None

    client.post(f"/info/{item['id']}/delete")
    assert InfoItem.query.count() == 0
    assert InfoAttachment.query.count() == 0


def test_info_rejects_unsupported_files_and_requires_title(client):
    setup_household(client)
    rv = client.post("/info", data={"title": ""}, content_type="multipart/form-data")
    assert rv.status_code == 400
    rv = client.post(
        "/info",
        data={"title": "Virus", "files": [(io.BytesIO(b"MZ..."), "evil.exe")]},
        content_type="multipart/form-data",
    )
    assert rv.status_code == 400
    assert InfoItem.query.count() == 0


def test_info_isolated_between_households(client):
    setup_household(client, "a@example.com", "Alex", "House A")
    rv = client.post(
        "/info",
        data={"title": "Wifi password", "files": [(io.BytesIO(PNG_BYTES), "wifi.png")]},
        content_type="multipart/form-data",
    )
    item = rv.get_json()["item"]
    att_id = item["attachments"][0]["id"]
    logout(client)

    setup_household(client, "b@example.com", "Bo", "House B")
    assert b"Wifi password" not in client.get("/info").data
    assert client.get(f"/info/files/{att_id}/wifi.png").status_code == 404
    assert client.post(f"/info/{item['id']}/delete").status_code == 404
    assert client.post(f"/info/files/{att_id}/delete").status_code == 404
    assert client.get(f"/info/files/{att_id}/wifi.png").status_code == 404
