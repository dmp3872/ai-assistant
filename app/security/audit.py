"""Append-only structured audit log. Mirrors to SQLite and a daily JSONL file.

Every collection, model call, draft, and error should call audit(). This is the
record of what the assistant read and did — kept local, never sent anywhere.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from app.settings import get_settings

_settings = get_settings()


def audit(kind: str, source: str | None = None, **detail: Any) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "source": source,
        "detail": detail,
    }
    # 1) local JSONL, append-only
    path = _settings.log_dir / f"audit-{date.today().isoformat()}.jsonl"
    try:
        with path.open("a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        pass  # logging must never break the pipeline

    # 2) DB mirror (best-effort; avoid import cycle at module load)
    try:
        from app.db import get_session
        from app.db.models import AuditLog

        with get_session() as s:
            s.add(AuditLog(kind=kind, source=source, detail=json.dumps(detail, default=str)))
    except Exception:
        pass
