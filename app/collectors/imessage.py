"""Apple Messages collector (Phase 2 — STUB).

Design (read-only): open ~/Library/Messages/chat.db read-only (requires Full Disk
Access), copy new rows into our normalized DB, track last processed ROWID, never touch
the original DB. The attributedBody BLOB (Apple typedstream) needs careful decoding for
newer messages; the `text` column covers older ones. Attachments ignored initially.

Enable in config only after implementing decode + FDA handling on your Mac.
"""
from __future__ import annotations

from app.collectors.base import BaseCollector


class IMessageCollector(BaseCollector):
    name = "imessage"

    # Sketch of the real query, kept for when you implement Phase 2:
    #   SELECT ROWID, text, attributedBody, handle_id, date, is_from_me
    #   FROM message WHERE ROWID > :cursor ORDER BY ROWID ASC
    # date is Apple epoch (nanoseconds since 2001-01-01); convert accordingly.

    def fetch_new(self, cursor):
        raise NotImplementedError(
            "iMessage is Phase 2. Grant Full Disk Access, implement chat.db read + "
            "attributedBody decode, then enable in config."
        )
