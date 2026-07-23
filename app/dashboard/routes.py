"""Dashboard JSON API. Read models over SQLite + a few safe local mutations
(mark handled, snooze, save your paste-back for learning, emergency stop).

Nothing here contacts an external source. The only 'writes' are to our own DB and the
local EMERGENCY_STOP file.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body
from sqlalchemy import desc

from app.classifiers import tab_for_category
from app.db import get_session
from app.db.models import Connector, Draft, Item, ReviewHistory, Sale
from app.retrieval import ingest_review_examples
from app.scheduler.run_cycle import run_cycle
from app.settings import get_settings

router = APIRouter()
_settings = get_settings()


def _item_dict(item: Item, draft: Draft | None) -> dict:
    return {
        "id": item.id,
        "source": item.source,
        "author": item.author,
        "title": item.title,
        "summary": (item.body_clean or "")[:280],
        "url": item.url,
        "category": item.category,
        "priority": item.priority,
        "needs_response": item.needs_response,
        "injection_flag": item.injection_flag,
        "handled": item.handled,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "draft": draft.draft_text if draft else None,
        "confidence": draft.confidence if draft else None,
        "review_reason": draft.review_reason if draft else None,
        "draft_id": draft.id if draft else None,
    }


def _active_filter(q):
    now = datetime.now(timezone.utc)
    return q.filter(Item.handled == False).filter(  # noqa: E712
        (Item.snoozed_until == None) | (Item.snoozed_until < now)  # noqa: E711
    )


@router.get("/summary")
def summary():
    """Per-tab counts + scan stats + connectors for the sidebar and rail."""
    counts = {"priority": 0, "community": 0, "sales": 0, "content": 0,
              "personal": 0, "email": 0}
    scanned = relevant = filtered = flagged = 0
    with get_session() as s:
        for item in _active_filter(s.query(Item)).all():
            tab = tab_for_category(item.category)
            if item.priority == "urgent" or item.needs_response or item.injection_flag:
                counts["priority"] += 1
            if tab in counts:
                counts[tab] += 1
            scanned += 1
            if item.injection_flag:
                flagged += 1
            if item.spam:
                filtered += 1
            else:
                relevant += 1
        connectors = [
            {"name": c.name, "status": c.status,
             "last_success": c.last_success_at.isoformat() if c.last_success_at else None}
            for c in s.query(Connector).all()
        ]
        # sales ending soon (has an end_date)
        sales_soon = [
            {"vendor": r.vendor, "promo": r.promo_name,
             "end": f"{r.end_date}{(' ' + r.end_tz) if r.end_tz else ''}"}
            for r in s.query(Sale).filter(Sale.end_iso != None)  # noqa: E711
            .order_by(Sale.end_iso.asc()).limit(6).all()  # soonest-ending first
        ]
    return {"counts": counts,
            "scan": {"scanned": scanned, "relevant": relevant,
                     "filtered": filtered, "flagged": flagged},
            "connectors": connectors, "sales_soon": sales_soon,
            "emergency_stopped": _settings.emergency_stopped}


@router.get("/status")
def status():
    with get_session() as s:
        connectors = [
            {"name": c.name, "status": c.status, "enabled": c.enabled,
             "last_success": c.last_success_at.isoformat() if c.last_success_at else None,
             "last_error": c.last_error}
            for c in s.query(Connector).all()
        ]
    return {"emergency_stopped": _settings.emergency_stopped, "connectors": connectors}


@router.get("/items")
def items(tab: str = "priority"):
    """Return items for a dashboard tab."""
    out = []
    with get_session() as s:
        q = _active_filter(s.query(Item)).order_by(desc(Item.created_at))
        for item in q.limit(200):
            item_tab = tab_for_category(item.category)
            if tab == "priority":
                if item.priority == "urgent" or item.needs_response or item.injection_flag:
                    pass
                else:
                    continue
            elif item_tab != tab:
                continue
            draft = (s.query(Draft).filter_by(item_id=item.id)
                     .order_by(desc(Draft.id)).first())
            out.append(_item_dict(item, draft))
    return {"tab": tab, "items": out}


@router.get("/sales")
def sales():
    with get_session() as s:
        rows = s.query(Sale).order_by(desc(Sale.id)).limit(200).all()
        return {"sales": [
            {"id": r.id, "item_id": r.item_id, "vendor": r.vendor, "promo_name": r.promo_name,
             "discount": r.discount, "coupon_code": r.coupon_code,
             "start_date": r.start_date, "end_date": r.end_date, "end_tz": r.end_tz,
             "exclusions": r.exclusions, "free_shipping_threshold": r.free_shipping_threshold,
             "giveaway": r.giveaway, "confidence": r.confidence,
             "contradicts_sale_id": r.contradicts_sale_id}
            for r in rows
        ]}


@router.post("/items/{item_id}/handled")
def mark_handled(item_id: int):
    with get_session() as s:
        item = s.get(Item, item_id)
        if item:
            item.handled = True
    return {"ok": True}


@router.post("/items/{item_id}/snooze")
def snooze(item_id: int, hours: int = Body(embed=True, default=24)):
    with get_session() as s:
        item = s.get(Item, item_id)
        if item:
            item.snoozed_until = datetime.now(timezone.utc) + timedelta(hours=hours)
    return {"ok": True}


@router.post("/items/{item_id}/review")
def save_review(item_id: int, payload: dict = Body(...)):
    """Store what you actually posted vs the AI draft, and re-embed it as a
    style example so future drafts sound more like you."""
    final_text = (payload.get("final_text") or "").strip()
    rejected = bool(payload.get("rejected", False))
    feedback = payload.get("feedback", "")
    with get_session() as s:
        item = s.get(Item, item_id)
        draft = (s.query(Draft).filter_by(item_id=item_id)
                 .order_by(desc(Draft.id)).first())
        dist = None
        if draft and final_text:
            dist = abs(len(final_text) - len(draft.draft_text))
        s.add(ReviewHistory(item_id=item_id, draft_id=draft.id if draft else None,
                            final_text=final_text, edit_distance=dist,
                            rejected=rejected, feedback=feedback))
        url = item.url if item else ""
    if final_text and not rejected:
        ingest_review_examples([{"text": final_text, "url": url or "", "ref_id": str(item_id)}])
    return {"ok": True}


@router.post("/run")
def run_now():
    """Manually trigger a collection cycle (same code launchd runs)."""
    return run_cycle()


@router.post("/emergency-stop")
def emergency_stop(payload: dict = Body(default={})):
    on = bool(payload.get("on", True))
    if on:
        _settings.emergency_stop_path.write_text(datetime.now(timezone.utc).isoformat())
    else:
        _settings.emergency_stop_path.unlink(missing_ok=True)
    return {"emergency_stopped": _settings.emergency_stopped}
