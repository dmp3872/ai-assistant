"""Deduplication. Two layers:

1. Exact: (source, source_id) uniqueness is enforced by the DB — the incremental
   cursors already prevent re-collecting the same native item.
2. Near-duplicate: content hash on normalized body catches the same content arriving
   via two paths (e.g. a promo emailed and also posted). We treat an identical
   body_hash within a recent window as a duplicate.
"""
from __future__ import annotations

from app.db import get_session
from app.db.models import Item
from app.models import NormalizedItem


def is_duplicate(item: NormalizedItem) -> bool:
    """True if we already have this exact item, or the same content very recently."""
    with get_session() as s:
        # exact native id
        exact = (
            s.query(Item.id)
            .filter(Item.source == item.source, Item.source_id == item.source_id)
            .first()
        )
        if exact:
            return True
        # same normalized content hash (cross-path duplicate)
        if item.body_hash:
            same = s.query(Item.id).filter(Item.body_hash == item.body_hash).first()
            if same:
                return True
    return False
