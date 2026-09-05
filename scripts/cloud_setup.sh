#!/usr/bin/env bash
# Cloud Agent environment bootstrap for Radar Assistant.
#
# Idempotent: safe to run repeatedly. Creates a Python virtualenv, installs the
# project dependencies, seeds local (non-secret) config from the committed examples,
# initializes the SQLite schema, and loads demo data so the dashboard has content to
# render without any external credentials, Ollama, or the Claude API.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# --- system deps: python venv module (Debian/Ubuntu splits it into its own package) ---
if ! python3 -m venv --help >/dev/null 2>&1; then
  echo "[cloud_setup] installing python3-venv"
  sudo apt-get update -y
  sudo apt-get install -y python3-venv
fi

# --- virtualenv ---
if [ ! -x .venv/bin/python ]; then
  echo "[cloud_setup] creating virtualenv"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "[cloud_setup] installing python dependencies"
python -m pip install --upgrade pip
pip install -r requirements.txt

# --- local, non-secret config (settings.py falls back to *.example.yaml otherwise) ---
[ -f config/config.yaml ] || cp config/config.example.yaml config/config.yaml
[ -f config/style_profile.yaml ] || cp config/style_profile.example.yaml config/style_profile.yaml

# --- database schema + demo content ---
echo "[cloud_setup] initializing database and seeding demo data"
python scripts/init_db.py
python scripts/seed_demo.py

echo "[cloud_setup] done. Start the dashboard with:"
echo "  source .venv/bin/activate && uvicorn app.main:app --host 127.0.0.1 --port 4317"
