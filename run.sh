#!/usr/bin/env bash
# Starts the app on http://127.0.0.1:8000
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    echo "Creating virtualenv..."
    python3 -m venv .venv
    ./.venv/bin/pip install --upgrade pip
    ./.venv/bin/pip install -r requirements.txt
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

echo "Personal Finance Manager -> http://${HOST}:${PORT}"
exec ./.venv/bin/uvicorn app.main:app --host "$HOST" --port "$PORT" --reload
