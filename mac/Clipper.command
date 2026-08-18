#!/bin/bash
# Double-click this file (in Finder) to start the Video Clipper on your Mac.
# First run installs what's needed; after that it just opens the app in your browser.
# If macOS blocks it the first time: right-click → Open → Open.

set -e
cd "$(dirname "$0")/.."          # repo root (this file lives in mac/)
REPO="$(pwd)"
echo "🎬  Video Clipper — setting up in: $REPO"
echo

# --- Python -------------------------------------------------------------------
PY=""
for c in python3.11 python3; do command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }; done
if [ -z "$PY" ]; then
  echo "→ Python 3 not found. Installing via Homebrew…"
  command -v brew >/dev/null 2>&1 || { echo "✗ Homebrew missing — install from https://brew.sh then re-run."; read -r -p "Press Return to close."; exit 1; }
  brew install python@3.11
  PY=python3.11
fi

# --- venv + deps (first run only) --------------------------------------------
if [ ! -d ".venv" ]; then
  echo "→ Creating virtual environment…"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

if [ ! -f ".venv/.clipper_ready" ]; then
  echo "→ Installing Python packages (one time, may take a few minutes)…"
  pip install -q --upgrade pip
  pip install -q -r requirements.txt
  pip install -q faster-whisper
  touch .venv/.clipper_ready
fi

# --- ffmpeg -------------------------------------------------------------------
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "→ Installing ffmpeg…"
  if command -v brew >/dev/null 2>&1; then brew install ffmpeg; else
    echo "⚠ Homebrew missing — install ffmpeg from https://ffmpeg.org (the app will still"
    echo "  show the clip plan, but can't cut the files without it)."
  fi
fi

# --- launch -------------------------------------------------------------------
echo
echo "✓ Ready. Opening the Video Clipper in your browser…"
echo "  (drag a video onto the page · close this window to stop)"
echo
exec python scripts/clipper.py
