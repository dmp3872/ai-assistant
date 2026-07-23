"""TikTok collector (Phase 3 — STUB).

TikTok's comment access lives behind the Research API scope, not a normal creator
integration. Phase 3 starts with (a) TikTok notification emails parsed out of Gmail and
(b) TikTok Studio browser automation for YOUR own posts/comments, capturing direct
links to each video/comment. Treat as a secondary connector — UI changes will break it.
"""
from __future__ import annotations

from app.collectors.base import BaseCollector


class TikTokCollector(BaseCollector):
    name = "tiktok"

    def fetch_new(self, cursor):
        raise NotImplementedError(
            "TikTok is Phase 3. Start with notification-email parsing + TikTok Studio "
            "automation for your own posts/comments."
        )
