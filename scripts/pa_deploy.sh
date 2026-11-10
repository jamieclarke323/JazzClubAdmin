#!/usr/bin/env bash
# Update the app on PythonAnywhere: pull, install, migrate, reload.
# Usage (in a PythonAnywhere Bash console):  bash ~/JazzClubAdmin/scripts/pa_deploy.sh
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/JazzClubAdmin}"
PA_USER="${PA_USER:-$(whoami)}"
WSGI_FILE="/var/www/${PA_USER}_pythonanywhere_com_wsgi.py"

cd "$APP_DIR"
echo "==> Pulling latest code"
git pull --ff-only

echo "==> Installing dependencies"
source .venv/bin/activate
pip install -q -r requirements.txt

echo "==> Applying database migrations"
flask --app wsgi db upgrade

if [ -f "$WSGI_FILE" ]; then
  echo "==> Reloading web app"
  touch "$WSGI_FILE"
else
  echo "==> WSGI file not found at $WSGI_FILE - click Reload on the Web tab instead."
fi
echo "Done."
