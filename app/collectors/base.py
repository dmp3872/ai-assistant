"""BaseCollector: cursor persistence, health tracking, retry/backoff, pacing.

Subclasses implement:
    name: str
    fetch_new(cursor) -> tuple[list[NormalizedItem], new_cursor]

They MUST be read-only. There is no write path in this base class by design.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from tenacity import retry, stop_after_attempt, wait_exponential

from app.db import get_session
from app.db.models import Connector
from app.models import NormalizedItem
from app.security import audit


class CollectorError(RuntimeError):
    pass


class BaseCollector:
    name: str = "base"

    # --- subclass hook -----------------------------------------------------
    def fetch_new(self, cursor: str | None) -> tuple[list[NormalizedItem], str | None]:
        """Return (new_items, new_cursor). Read-only. Override me."""
        raise NotImplementedError

    def health_check(self) -> bool:
        """Cheap liveness probe. Override where a connector can pre-flight."""
        return True

    # --- shared machinery --------------------------------------------------
    def _load_cursor(self) -> str | None:
        with get_session() as s:
            row = s.query(Connector).filter_by(name=self.name).one_or_none()
            return row.cursor if row else None

    def _save_state(self, cursor: str | None, status: str, error: str | None = None) -> None:
        now = datetime.now(timezone.utc)
        with get_session() as s:
            row = s.query(Connector).filter_by(name=self.name).one_or_none()
            if row is None:
                row = Connector(name=self.name)
                s.add(row)
            row.last_run_at = now
            row.status = status
            row.last_error = error
            if status == "ok":
                row.cursor = cursor
                row.last_success_at = now

    @retry(stop=stop_after_attempt(4),
           wait=wait_exponential(multiplier=2, min=2, max=16),
           reraise=True)
    def _fetch_with_retry(self, cursor: str | None):
        return self.fetch_new(cursor)

    def run(self) -> list[NormalizedItem]:
        """Full collection with health check, retry, cursor persistence, audit."""
        if not self.health_check():
            self._save_state(None, "degraded", "health_check failed")
            audit("error", source=self.name, stage="health")
            return []
        cursor = self._load_cursor()
        try:
            items, new_cursor = self._fetch_with_retry(cursor)
            self._save_state(new_cursor, "ok")
            audit("collect", source=self.name, count=len(items), cursor=str(new_cursor))
            return items
        except Exception as exc:
            self._save_state(cursor, "error", str(exc))
            audit("error", source=self.name, stage="fetch", error=str(exc))
            return []

    @staticmethod
    def _pace(ms: int) -> None:
        if ms > 0:
            time.sleep(ms / 1000.0)
