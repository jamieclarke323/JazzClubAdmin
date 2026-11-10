# Nest — shared household life admin

A small, fast, mobile-first web app for the everyday admin of running a home together:
shared and personal to-do lists, a shared shopping list, and who's doing what.

Built with Flask + SQLite + vanilla JavaScript, designed to run on PythonAnywhere's free/standard
Flask hosting without Redis, Celery, Docker, Node or background workers.

## Features

**Tasks**
- Add a task in one tap (title only); progressively reveal assignee, due date, priority, list, repeat and notes.
- Views as simple tabs: Mine · All · Today · Upcoming · Overdue · Done, plus a per-person filter.
- One-tap complete with Undo. Tasks are grouped Overdue / Today / Upcoming / No date.
- Assign to a household member (colour + initial avatar), reassign from the edit sheet.
- Recurring tasks (daily, weekly, every 2 weeks, monthly, yearly). Completing one creates exactly one next
  occurrence; undoing removes it again. No background jobs needed.

**Shopping list**
- Type, press Enter. `Milk x2` / `2x Milk` sets a quantity automatically.
- Tick off with one tap (Undo available), "In the basket" section with a two-tap Clear.
- Duplicate protection: adding something already on the list highlights it; adding something that's
  in the basket puts it back on the list.
- Suggestions while you type and "Add again" chips, based on what your household actually buys.
- Optional grouping by aisle (Groceries / Household / Toiletries / Other). Categories are remembered per item.
- Remaining-item badge on the Shopping tab.

**Info**
- A shared reference drawer for the stuff you always need to find again: flight details, insurance docs,
  the wifi password, appliance serial numbers.
- Each item has a title, optional notes and any number of attached **photos/screenshots or PDFs**.
- Tap a photo to view it full-screen (and download it); PDFs open in a new tab. Instant search.
- Files are stored on disk under `instance/uploads/<household>/` with random names and only served to
  members of that household.

**Household**
- Register, log in, create a household, invite with a secure link (resettable), rename, change display name /
  password, leave (with safeguards — the last member leaving deletes the household's data).
- All data is scoped to the household; cross-household IDs return 404.
- Optional: close public registration (`ALLOW_REGISTRATION=0`) — invite links still work.

**Sync & PWA**
- Lightweight polling keeps both phones in sync (every ~12 s while the page is visible, and on focus).
- Installable PWA (manifest + service worker with offline fallback). Dark mode follows the system.

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # set SECRET_KEY, set SESSION_COOKIE_SECURE=0 for http://localhost
flask --app wsgi db upgrade     # create/upgrade the SQLite database in ./instance/
python run.py                   # http://127.0.0.1:5000
```

Run the tests with `pip install pytest && pytest`.

## Deploying to PythonAnywhere

1. **Get the code onto PythonAnywhere** (Bash console):
   ```bash
   cd ~
   git clone <your-repo-url> JazzClubAdmin     # or upload a zip and unzip it
   cd JazzClubAdmin
   python3.12 -m venv .venv                    # pick a Python version PythonAnywhere offers (3.10+)
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure secrets** — create `~/JazzClubAdmin/.env`:
   ```
   SECRET_KEY=<output of: python -c "import secrets; print(secrets.token_hex(32))">
   TIMEZONE=Europe/London
   APP_NAME=Nest
   SESSION_COOKIE_SECURE=1
   ALLOW_REGISTRATION=1
   ```
   `config.py` loads this file automatically. The database defaults to
   `~/JazzClubAdmin/instance/household.db`; set `DATABASE_URL=sqlite:////home/<user>/path.db` to move it.

3. **Create the database**:
   ```bash
   flask --app wsgi db upgrade
   ```

4. **Web app** — on the *Web* tab, "Add a new web app" → *Manual configuration* → the same Python version
   as your venv. Then set:
   - **Source code**: `/home/<username>/JazzClubAdmin`
   - **Working directory**: `/home/<username>/JazzClubAdmin`
   - **Virtualenv**: `/home/<username>/JazzClubAdmin/.venv`
   - **WSGI configuration file** — replace its contents with:
     ```python
     import sys
     path = "/home/<username>/JazzClubAdmin"
     if path not in sys.path:
         sys.path.insert(0, path)
     from wsgi import application
     ```
   - **Static files**: URL `/static/` → Directory `/home/<username>/JazzClubAdmin/app/static`
   - **Force HTTPS**: enabled (under the Security section). PythonAnywhere provides the certificate.

5. Click **Reload**. Visit `https://<username>.pythonanywhere.com`, create your account and household, then
   open the Household tab and send your partner the invite link. On a phone, use "Add to Home Screen" to
   install it as an app.

6. (Recommended) Once everyone has joined, set `ALLOW_REGISTRATION=0` in `.env` and reload the web app.
   New people can still join via invite links.

### Updating

Push to GitHub, then in a PythonAnywhere Bash console:
```bash
bash ~/JazzClubAdmin/scripts/pa_deploy.sh
```
This pulls, installs any new dependencies, runs `flask db upgrade` and reloads the web app.
(Equivalent manual steps: `git pull`, `pip install -r requirements.txt`, `flask --app wsgi db upgrade`,
then **Reload** on the Web tab.)

### Backups

The database is one file and uploaded attachments live alongside it. From a console or a scheduled task:
```bash
mkdir -p ~/backups
cp ~/JazzClubAdmin/instance/household.db ~/backups/household-$(date +%F).db
tar czf ~/backups/uploads-$(date +%F).tgz -C ~/JazzClubAdmin/instance uploads
```
PythonAnywhere free accounts have a 512 MB disk quota; photos count towards it (a phone screenshot is
typically 0.5–3 MB). Lower `MAX_UPLOAD_MB` if you want to be stricter.

### Database migrations (for developers)

Schema changes use Flask-Migrate/Alembic:
```bash
flask --app wsgi db migrate -m "describe change"   # generate from model changes; review the file
flask --app wsgi db upgrade                        # apply
```
Migrations run with `render_as_batch=True` so `ALTER TABLE` works on SQLite.

## Project layout

```
app/
  __init__.py     app factory, CSRF, login, PWA routes, CLI
  models.py       Household, User, Task, ShoppingItem, ShoppingHistory
  auth.py         register / login / logout
  household.py    create, invite, join, members, leave, account
  tasks.py        task views + JSON endpoints, recurrence
  shopping.py     shopping list + suggestions
  info.py         info items with photo/PDF attachments
  utils.py        dates, recurrence, parsing
  templates/      Jinja templates (HTML-over-the-wire partials for live refresh)
  static/         CSS, vanilla JS, service worker, icons
migrations/       Alembic migrations
tests/            pytest suite
config.py         environment-driven configuration
wsgi.py           WSGI entry point (PythonAnywhere)
run.py            local dev server
```

## Configuration reference

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | dev value | **Set this.** Signs sessions. |
| `DATABASE_URL` | `sqlite:///<project>/instance/household.db` | SQLAlchemy URL. |
| `TIMEZONE` | `Europe/London` | Used for "today", due dates and recurrence. |
| `APP_NAME` | `Nest` | Name in the header and home-screen icon. |
| `SESSION_COOKIE_SECURE` | `1` | Cookies only over HTTPS. Use `0` for local http. |
| `ALLOW_REGISTRATION` | `1` | Allow sign-ups without an invite link. |
| `UPLOAD_DIR` | `<project>/instance/uploads` | Where Info attachments are stored. |
| `MAX_UPLOAD_MB` | `20` | Maximum size of a single upload request. |
