"""WhatsApp collector (Phase 2 — STUB).

Meta's Cloud API targets business numbers, not your personal Messenger account. The
practical read-only path for an existing personal number is Playwright automation of
WhatsApp Web on your authenticated profile. Fragile; never sends. Implement similarly
to the Skool collector (persistent context + isolated selectors) when you reach Phase 2.
"""
from __future__ import annotations

from app.collectors.base import BaseCollector


class WhatsAppCollector(BaseCollector):
    name = "whatsapp"

    def fetch_new(self, cursor):
        raise NotImplementedError(
            "WhatsApp is Phase 2. Use read-only WhatsApp Web automation on your "
            "authenticated profile; never enable autonomous sending."
        )
