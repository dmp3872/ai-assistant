"""Collectors: one per source. Each turns raw source objects into NormalizedItems.

Register enabled collectors here so the scheduler can discover them.
"""
from __future__ import annotations

from app.settings import get_settings

from .base import BaseCollector


def get_enabled_collectors() -> list[BaseCollector]:
    """Instantiate collectors that are enabled in config. Import lazily so a
    missing optional dependency for one connector doesn't break the others."""
    settings = get_settings()
    collectors: list[BaseCollector] = []

    def _try(name: str, factory):
        if not settings.connector_enabled(name):
            return
        try:
            collectors.append(factory())
        except Exception as exc:  # pragma: no cover
            from app.security import audit
            audit("error", source=name, stage="init", error=str(exc))

    _try("gmail", lambda: _import("gmail", "GmailCollector")())
    _try("calendar", lambda: _import("calendar", "CalendarCollector")())
    _try("telegram", lambda: _import("telegram", "TelegramCollector")())
    _try("skool", lambda: _import("skool", "SkoolCollector")())
    # Phase 2/3 (stubs, disabled by default):
    _try("imessage", lambda: _import("imessage", "IMessageCollector")())
    _try("whatsapp", lambda: _import("whatsapp", "WhatsAppCollector")())
    _try("tiktok", lambda: _import("tiktok", "TikTokCollector")())
    return collectors


def _import(module: str, cls: str):
    mod = __import__(f"app.collectors.{module}", fromlist=[cls])
    return getattr(mod, cls)


__all__ = ["BaseCollector", "get_enabled_collectors"]
