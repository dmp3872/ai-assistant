"""The content queue — your stocked shelf of copy-ready posts and answers.

Everything here touches ONLY our own SQLite. Nothing posts to Skool or anywhere else;
a piece leaves the queue when *you* mark it posted from the Studio tab. Depth counts
drive replenishment: the engine tops the shelf up to a per-channel target each cycle.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import desc, func

from app.db import get_session
from app.db.models import ContentPiece

# A piece is "on the shelf" (counts toward queue depth) while it's waiting for you.
OPEN_STATUSES = ("queued", "approved", "scheduled")
# Terminal statuses no longer count toward depth.
CLOSED_STATUSES = ("posted", "discarded")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def piece_dict(p: ContentPiece) -> dict:
    return {
        "id": p.id,
        "channel": p.channel,
        "kind": p.kind,
        "title": p.title,
        "hook": p.hook,
        "body": p.body,
        "cta": p.cta,
        "status": p.status,
        "origin": p.origin,
        "origin_ref": p.origin_ref,
        "opportunity_id": p.opportunity_id,
        "angle": p.angle,
        "tags": json.loads(p.tags) if p.tags else [],
        "confidence": p.confidence,
        "review_reason": p.review_reason,
        "sources_used": json.loads(p.sources_used) if p.sources_used else [],
        "model": p.model,
        "scheduled_day": p.scheduled_day,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "posted_at": p.posted_at.isoformat() if p.posted_at else None,
    }


def add_piece(data: dict) -> int | None:
    """Insert a piece. `dedupe_key` (if set) makes this idempotent — a repeat topic on
    the next cycle is skipped rather than duplicated. Returns the id, or None if a piece
    with the same dedupe_key already exists."""
    dedupe = data.get("dedupe_key")
    with get_session() as s:
        if dedupe:
            exists = s.query(ContentPiece.id).filter_by(dedupe_key=dedupe).first()
            if exists:
                return None
        row = ContentPiece(
            channel=data.get("channel", "skool"),
            kind=data.get("kind", "post"),
            title=data.get("title"),
            hook=data.get("hook"),
            body=(data.get("body") or "").strip(),
            cta=data.get("cta"),
            status=data.get("status", "queued"),
            origin=data.get("origin", "classroom"),
            origin_ref=data.get("origin_ref"),
            opportunity_id=data.get("opportunity_id"),
            angle=data.get("angle"),
            tags=json.dumps(data["tags"]) if data.get("tags") else None,
            confidence=data.get("confidence", "medium"),
            review_reason=data.get("review_reason"),
            sources_used=json.dumps(data["sources_used"]) if data.get("sources_used") else None,
            model=data.get("model"),
            dedupe_key=dedupe,
        )
        s.add(row)
        s.flush()
        return row.id


def depth_by_channel(channel: str, *, kind: str | None = None) -> int:
    """How many open (unposted, non-discarded) pieces are waiting for a channel."""
    with get_session() as s:
        q = s.query(func.count(ContentPiece.id)).filter(
            ContentPiece.channel == channel,
            ContentPiece.status.in_(OPEN_STATUSES),
        )
        if kind:
            q = q.filter(ContentPiece.kind == kind)
        return int(q.scalar() or 0)


def list_pieces(channel: str | None = None, status: str | None = None,
                kind: str | None = None, limit: int = 200) -> list[dict]:
    with get_session() as s:
        q = s.query(ContentPiece)
        if channel:
            q = q.filter(ContentPiece.channel == channel)
        if status == "open":
            q = q.filter(ContentPiece.status.in_(OPEN_STATUSES))
        elif status:
            q = q.filter(ContentPiece.status == status)
        if kind:
            q = q.filter(ContentPiece.kind == kind)
        rows = q.order_by(desc(ContentPiece.id)).limit(limit).all()
        return [piece_dict(r) for r in rows]


def set_status(piece_id: int, status: str, *, edited_text: str | None = None) -> bool:
    """Move a piece through the workflow. 'posted' stamps posted_at and stores what you
    actually posted (edited_text) for later style learning."""
    if status not in OPEN_STATUSES + CLOSED_STATUSES:
        return False
    with get_session() as s:
        p = s.get(ContentPiece, piece_id)
        if not p:
            return False
        p.status = status
        if edited_text is not None:
            p.edited_text = edited_text
        if status == "posted":
            p.posted_at = _now()
        return True


def update_body(piece_id: int, *, title: str | None = None, body: str | None = None) -> bool:
    with get_session() as s:
        p = s.get(ContentPiece, piece_id)
        if not p:
            return False
        if title is not None:
            p.title = title
        if body is not None:
            p.body = body
        return True


def pull_for_day(channel: str, day: str, n: int) -> list[dict]:
    """Return up to `n` open pieces for a channel to fill that day's quota, pinning them
    to `day` (scheduled_day) so the same posts back the planner cards every refresh.
    Already-pinned pieces for the day come first; the rest are freshly pinned."""
    with get_session() as s:
        pinned = (s.query(ContentPiece)
                  .filter(ContentPiece.channel == channel,
                          ContentPiece.status.in_(OPEN_STATUSES),
                          ContentPiece.scheduled_day == day)
                  .order_by(ContentPiece.id).all())
        need = n - len(pinned)
        if need > 0:
            fresh = (s.query(ContentPiece)
                     .filter(ContentPiece.channel == channel,
                             ContentPiece.status.in_(OPEN_STATUSES),
                             (ContentPiece.scheduled_day == None))  # noqa: E711
                     .order_by(ContentPiece.id).limit(need).all())
            for p in fresh:
                p.scheduled_day = day
            pinned = pinned + fresh
        return [piece_dict(p) for p in pinned[:n]]


def stats() -> dict:
    """Queue depth per channel + kind breakdown, for the Studio header and summary."""
    with get_session() as s:
        rows = (s.query(ContentPiece.channel, ContentPiece.kind,
                        func.count(ContentPiece.id))
                .filter(ContentPiece.status.in_(OPEN_STATUSES))
                .group_by(ContentPiece.channel, ContentPiece.kind).all())
        posted = (s.query(func.count(ContentPiece.id))
                  .filter(ContentPiece.status == "posted").scalar() or 0)
    by_channel: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for channel, kind, count in rows:
        by_channel[channel] = by_channel.get(channel, 0) + int(count)
        by_kind[kind] = by_kind.get(kind, 0) + int(count)
    return {"open_by_channel": by_channel, "open_by_kind": by_kind,
            "open_total": sum(by_channel.values()), "posted_total": int(posted)}
