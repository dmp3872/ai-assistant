"""One concise macOS notification when the digest is ready (via osascript)."""
from __future__ import annotations

import subprocess

from app.settings import get_settings

_settings = get_settings()


def notify(title: str, message: str) -> None:
    if not (_settings.config.get("notifications", {}) or {}).get("macos", True):
        return
    try:
        safe_msg = message.replace('"', "'")
        safe_title = title.replace('"', "'")
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{safe_msg}" with title "{safe_title}"'],
            check=False, timeout=10,
        )
    except Exception:
        pass  # notification failure must never break the run
