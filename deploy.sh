#!/usr/bin/env bash
# Production deploy script for the Maisha Chat backend (PM2 + gunicorn).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

detect_venv() {
  if [[ -n "${VENV:-}" && -f "$VENV/bin/activate" ]]; then echo "$VENV"; return; fi
  for c in "./.env" "./venv" "./.venv" "/home/happiness/blood_donation_ai/llm_env"; do
    if [[ -f "$c/bin/activate" ]]; then echo "$c"; return; fi
  done
}

VENV_PATH="$(detect_venv)"
if [[ -z "$VENV_PATH" ]]; then
  echo "[deploy.sh] Could not find a virtualenv. Create one first." >&2
  exit 1
fi

# shellcheck disable=SC1091
source "$VENV_PATH/bin/activate"
echo "[deploy.sh] Using virtualenv: $VENV_PATH"
# Expose the venv to PM2 so ecosystem.config.js can locate gunicorn.
export VENV_PATH

if [[ -f .env.local ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env.local
  set +a
  echo "[deploy.sh] Loaded environment from .env.local"
fi

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-bd_backend.settings}"

echo "[deploy.sh] Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "[deploy.sh] Running migrations..."
python manage.py migrate --noinput

echo "[deploy.sh] Ensuring admin account exists..."
python manage.py seed_admin || echo "[deploy.sh] seed_admin failed (continuing)"

echo "[deploy.sh] Collecting static files..."
python manage.py collectstatic --noinput

echo "[deploy.sh] (Re)starting PM2 process..."
pm2 startOrReload ecosystem.config.js --update-env
pm2 save

echo "[deploy.sh] Done. Backend is live on 127.0.0.1:8090 -> https://api.maishachat.or.tz"
