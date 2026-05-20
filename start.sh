#!/usr/bin/env bash
# Local development launcher for the Maisha Chat backend.
# Starts Django on 0.0.0.0:8090 using the project-local virtualenv at ./.env
# (or whichever venv $VENV points to).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Find the virtualenv. Preference order:
#   1. $VENV env var
#   2. ./.env        (the venv living at bd-backend/.env)
#   3. ./venv  /  ./.venv
#   4. /home/happiness/blood_donation_ai/llm_env (fallback)
detect_venv() {
  if [[ -n "${VENV:-}" && -f "$VENV/bin/activate" ]]; then echo "$VENV"; return; fi
  for c in "./.env" "./venv" "./.venv" "/home/happiness/blood_donation_ai/llm_env"; do
    if [[ -f "$c/bin/activate" ]]; then echo "$c"; return; fi
  done
}

VENV_PATH="$(detect_venv)"
if [[ -z "$VENV_PATH" ]]; then
  echo "[start.sh] Could not find a virtualenv. Create one with:" >&2
  echo "           python3 -m venv .env && source .env/bin/activate && pip install -r requirements.txt" >&2
  exit 1
fi

# shellcheck disable=SC1091
source "$VENV_PATH/bin/activate"
echo "[start.sh] Using virtualenv: $VENV_PATH"

# Load env vars from .env.local (since .env is the venv directory).
if [[ -f .env.local ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env.local
  set +a
  echo "[start.sh] Loaded environment from .env.local"
fi

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-bd_backend.settings}"

echo "[start.sh] Applying migrations..."
python manage.py migrate --noinput

echo "[start.sh] Ensuring admin account exists..."
python manage.py seed_admin || echo "[start.sh] seed_admin failed (continuing anyway)"

echo "[start.sh] GPU status (read-only, shared-host safe)..."
python manage.py check_gpu || true

PORT="${PORT:-8090}"
HOST="${HOST:-0.0.0.0}"
echo "[start.sh] Starting Django dev server on ${HOST}:${PORT}"
exec python manage.py runserver "${HOST}:${PORT}"
