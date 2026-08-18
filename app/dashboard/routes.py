"""Dashboard JSON API. Read models over SQLite + a few safe local mutations
(mark handled, snooze, save your paste-back for learning, emergency stop).

Nothing here contacts an external source. The only 'writes' are to our own DB and the
local EMERGENCY_STOP file.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Body, File, Form, UploadFile
from fastapi.responses import FileResponse
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


TAB_ORDER = ["priority", "community", "sales", "content", "tiktok", "personal", "email"]


def _tab_of(item: Item) -> str:
    """Which single tab an item belongs to (source-aware). 'hidden' = filtered."""
    if item.source == "tiktok":
        return "tiktok"
    if item.category == "peptideprice_sales":
        return "sales"
    if item.category == "content":
        return "content"
    if item.source == "skool" and item.category == "community":
        return "community"
    if item.category in ("email_work", "email_personal"):
        return "email"
    if item.category in ("personal", "financial_legal"):
        return "personal"
    return "hidden"


def _is_priority(item: Item) -> bool:
    return bool((item.priority == "urgent" or item.needs_response or item.injection_flag)
                and not item.spam)


def _in_tab(item: Item, tab: str) -> bool:
    return _is_priority(item) if tab == "priority" else _tab_of(item) == tab


def _relevance(item: Item) -> int:
    score = 0
    if item.injection_flag or item.priority == "urgent":
        score += 3
    if item.needs_response:
        score += 2
    if item.priority == "today":
        score += 1
    return score


def _sort_items(rows: list[Item], sort: str) -> list[Item]:
    floor = datetime.min
    if sort == "oldest":
        return sorted(rows, key=lambda i: i.created_at or floor)
    if sort == "relevant":
        return sorted(rows, key=lambda i: (_relevance(i), i.created_at or floor), reverse=True)
    return sorted(rows, key=lambda i: i.created_at or floor, reverse=True)  # newest


@router.get("/summary")
def summary():
    """Per-tab counts + scan stats + connectors for the sidebar and rail."""
    counts = {t: 0 for t in TAB_ORDER}
    counts["handled"] = 0
    scanned = relevant = filtered = flagged = 0
    with get_session() as s:
        for item in _active_filter(s.query(Item)).all():
            if _is_priority(item):
                counts["priority"] += 1
            t = _tab_of(item)
            if t in counts:
                counts[t] += 1
            scanned += 1
            if item.injection_flag:
                flagged += 1
            if item.spam:
                filtered += 1
            else:
                relevant += 1
        counts["handled"] = s.query(Item).filter(Item.handled == True).count()  # noqa: E712
    from app import planner
    from app.db.models import DailyTask
    today = datetime.now(timezone.utc).date().isoformat()
    planner.ensure_day(today)
    with get_session() as s2:
        counts["plan"] = s2.query(DailyTask).filter_by(day=today, done=False).count()
    try:
        from app.content import queue as content_queue
        counts["studio"] = content_queue.stats()["open_total"]
    except Exception:
        counts["studio"] = 0
    with get_session() as s:
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
def items(tab: str = "priority", sort: str = "newest"):
    """Return items for a dashboard tab, sorted newest|oldest|relevant."""
    out = []
    with get_session() as s:
        if tab == "handled":
            rows = s.query(Item).filter(Item.handled == True).all()  # noqa: E712
        else:
            rows = [it for it in _active_filter(s.query(Item)).all() if _in_tab(it, tab)]
        for item in _sort_items(rows, sort)[:200]:
            draft = (s.query(Draft).filter_by(item_id=item.id)
                     .order_by(desc(Draft.id)).first())
            out.append(_item_dict(item, draft))
    return {"tab": tab, "sort": sort, "items": out}


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


@router.get("/plan")
def get_plan(date: str | None = None):
    from app import planner
    day = date or datetime.now(timezone.utc).date().isoformat()
    return planner.plan(day)


@router.post("/plan/task/{task_id}/toggle")
def toggle_task(task_id: int):
    from app import planner
    return {"done": planner.toggle(task_id)}


@router.get("/content/recommendation")
def content_recommendation():
    """A new-post idea grounded in your classroom content (on-demand; uses the API)."""
    from app.drafting.claude_drafter import recommend_post
    rec = recommend_post()
    return {"recommendation": rec}


# --- Studio: the content queue + answer bank --------------------------------------

@router.get("/content/studio")
def content_studio():
    """Everything the Studio tab renders: queue stats, the post queue grouped by
    channel, and the Answer Bank (recurring questions + their canonical answers)."""
    from app.content import queue, opportunities
    channels = ["skool", "tiktok", "substack", "youtube"]
    open_by_channel = {c: queue.list_pieces(channel=c, status="open") for c in channels}
    posts = {c: [p for p in rows if p["kind"] not in ("answer", "video_clip")]
             for c, rows in open_by_channel.items()}
    clips = {c: [p for p in rows if p["kind"] == "video_clip"]
             for c, rows in open_by_channel.items()}
    answers = queue.list_pieces(kind="answer", status="open")
    return {"stats": queue.stats(), "posts": posts, "clips": clips, "answers": answers,
            "opportunities": opportunities.open_opportunities(limit=100)}


@router.get("/content/queue")
def content_queue(channel: str | None = None, status: str = "open",
                  kind: str | None = None):
    from app.content import queue
    return {"pieces": queue.list_pieces(channel=channel, status=status, kind=kind)}


@router.post("/content/piece/{piece_id}/status")
def content_piece_status(piece_id: int, payload: dict = Body(default={})):
    """Move a piece through queued→approved→posted (or discard). 'posted' can carry the
    text you actually posted for style learning."""
    from app.content import queue
    status = (payload.get("status") or "").strip()
    ok = queue.set_status(piece_id, status, edited_text=payload.get("edited_text"))
    return {"ok": ok}


@router.post("/content/piece/{piece_id}/edit")
def content_piece_edit(piece_id: int, payload: dict = Body(default={})):
    from app.content import queue
    ok = queue.update_body(piece_id, title=payload.get("title"),
                           body=payload.get("body"))
    return {"ok": ok}


@router.post("/content/generate")
def content_generate(payload: dict = Body(default={})):
    """On-demand generation. With {channel, seed} it drafts one post from that seed;
    otherwise it runs a bounded replenish to top the shelf up. Uses the API."""
    from app.content import engine, generator, opportunities, queue
    opp_id = payload.get("opportunity_id")
    if opp_id:
        opp = next((o for o in opportunities.open_opportunities()
                    if o["id"] == int(opp_id)), None)
        if not opp:
            return {"created": 0, "reason": "opportunity not found"}
        ans = generator.generate_answer(opp["question"])
        if not ans:
            return {"created": 0, "reason": "no API key or no answer produced"}
        pid = queue.add_piece({
            "channel": "skool", "kind": "answer", "origin": "opportunity",
            "opportunity_id": opp["id"], "origin_ref": str(opp["id"]),
            "title": ans["title"], "body": ans["body"], "confidence": ans["confidence"],
            "review_reason": ans["review_reason"], "sources_used": ans["sources_used"],
            "model": ans["model"], "dedupe_key": f"answer:{opp['id']}"})
        if pid:
            opportunities.mark_answered(opp["id"], pid)
        return {"created": 1 if pid else 0, "piece_id": pid}
    seed = (payload.get("seed") or "").strip()
    channel = (payload.get("channel") or "skool").strip()
    if seed:
        post = generator.generate_post(channel, seed)
        if not post:
            return {"created": 0, "reason": "no grounding content or no API key"}
        avoid = [p["title"] for p in queue.list_pieces(channel=channel, status="open")
                 if p.get("title")]
        pid = queue.add_piece({
            "channel": channel, "kind": "post", "origin": "manual",
            "title": post["title"], "hook": post["hook"], "body": post["body"],
            "cta": post["cta"], "angle": post["angle"], "tags": post["tags"],
            "confidence": post["confidence"], "review_reason": post["review_reason"],
            "sources_used": post["sources_used"], "model": post["model"]})
        return {"created": 1 if pid else 0, "piece_id": pid}
    return engine.replenish()


@router.get("/content/opportunities")
def content_opportunities():
    from app.content import opportunities
    return {"opportunities": opportunities.open_opportunities(limit=200)}


@router.post("/content/opportunity/{opp_id}/dismiss")
def content_opportunity_dismiss(opp_id: int):
    from app.content import opportunities
    return {"ok": opportunities.dismiss(opp_id)}


# --- Clipper: drop a video, get natural 5–7 min clips -----------------------------

def _clip_opts(min_: float, max_: float, target: float, model: str, fast: bool,
               queue_channel: str | None) -> dict:
    qc = (queue_channel or "").strip().lower()
    return {"min": float(min_), "max": float(max_), "target": float(target),
            "model": model or "base", "fast": bool(fast),
            "queue_channel": qc if qc in ("youtube", "tiktok", "skool", "substack") else None}


@router.post("/clipper/upload")
async def clipper_upload(
    file: UploadFile = File(...),
    min: float = Form(5.0), max: float = Form(7.0), target: float = Form(6.0),
    model: str = Form("base"), fast: bool = Form(False),
    queue_channel: str | None = Form(None),
):
    """Drag-drop entry point: stream the uploaded video to a temp file on THIS machine,
    then kick off a background clip job. (localhost upload — the file never leaves your
    computer.)"""
    from app.dashboard import clipper
    clipper.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    safe = Path(file.filename or "video.mp4").name
    dest = clipper.UPLOADS_DIR / f"{uuid.uuid4().hex[:8]}_{safe}"
    with dest.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            out.write(chunk)
    opts = _clip_opts(min, max, target, model, fast, queue_channel)
    return {"job_id": clipper.create_job(str(dest), safe, opts)}


@router.post("/clipper/jobs")
def clipper_start(payload: dict = Body(...)):
    """Path entry point (best for very large files — no upload copy): the server reads the
    video straight from disk. Also accepts an existing transcript to skip transcription."""
    from app.dashboard import clipper
    path = (payload.get("path") or "").strip()
    if not path or not Path(path).expanduser().exists():
        return {"error": f"File not found: {path or '(empty)'}"}
    p = Path(path).expanduser()
    opts = _clip_opts(payload.get("min", 5.0), payload.get("max", 7.0),
                      payload.get("target", 6.0), payload.get("model", "base"),
                      payload.get("fast", False), payload.get("queue_channel"))
    return {"job_id": clipper.create_job(str(p), p.name, opts,
                                         transcript=payload.get("transcript"))}


@router.get("/clipper/jobs")
def clipper_jobs():
    from app.dashboard import clipper
    return {"jobs": clipper.list_jobs()}


@router.get("/clipper/jobs/{job_id}")
def clipper_job(job_id: str):
    from app.dashboard import clipper
    return clipper.get_job(job_id) or {"error": "job not found"}


@router.post("/clipper/jobs/{job_id}/queue")
def clipper_queue(job_id: str, payload: dict = Body(default={})):
    from app.dashboard import clipper
    channel = (payload.get("channel") or "youtube").strip().lower()
    return clipper.queue_job(job_id, channel)


@router.get("/clipper/file/{job_id}/{name}")
def clipper_file(job_id: str, name: str):
    """Serve a cut clip file for play/download. Path-jailed to the job's own folder."""
    from app.dashboard import clipper
    base = (clipper.CLIPS_DIR / job_id).resolve()
    target = (base / name).resolve()
    if base not in target.parents or not target.exists():
        return {"error": "not found"}
    return FileResponse(str(target), filename=name)


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
