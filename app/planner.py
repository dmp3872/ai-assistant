"""Daily planner: content quotas (reset each day), calendar schedule, free time.

Quotas seed fresh per day — each day owns its rows, so "daily reset" is automatic and
yesterday's checkmarks never carry over. Calendar events for the day are merged in and
everything is ordered by time; untimed quota items follow the timed schedule.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.db import get_session
from app.db.models import DailyTask, Item

# (kind, count, label) — your daily content targets
QUOTAS = [
    ("youtube", 1, "Film long-form YouTube video"),
    ("substack", 3, "Write Substack article"),
    ("skool", 7, "Write & post Skool post"),
    ("tiktok", 6, "Record & post TikTok"),
]
WORK_START, WORK_END = 8 * 60, 20 * 60  # 08:00–20:00 for free-time math


def ensure_day(day: str) -> None:
    with get_session() as s:
        if s.query(DailyTask.id).filter_by(day=day).first():
            return
        pos = 0
        for kind, count, label in QUOTAS:
            for n in range(1, count + 1):
                lbl = f"{label} ({n}/{count})" if count > 1 else label
                s.add(DailyTask(day=day, kind=kind, label=lbl, position=pos))
                pos += 1


def toggle(task_id: int) -> bool:
    with get_session() as s:
        t = s.get(DailyTask, task_id)
        if not t:
            return False
        t.done = not t.done
        t.done_at = datetime.now(timezone.utc) if t.done else None
        return t.done


def _parse_start(raw_json: str | None):
    if not raw_json:
        return None
    try:
        start = (json.loads(raw_json) or {}).get("start")
    except (ValueError, TypeError):
        return None
    if not start:
        return None
    try:
        return datetime.fromisoformat(str(start).replace("Z", "+00:00"))
    except ValueError:
        return None


def day_schedule(day: str) -> list[dict]:
    """Calendar events on `day`, ordered by start time."""
    out = []
    with get_session() as s:
        for it in s.query(Item).filter(Item.source == "calendar").all():
            dt = _parse_start(it.raw_json)
            if dt and dt.date().isoformat() == day:
                out.append({"time": dt.strftime("%H:%M"), "minute": dt.hour * 60 + dt.minute,
                            "title": it.title or "(event)", "url": it.url})
    return sorted(out, key=lambda x: x["minute"])


def free_slots(schedule: list[dict]) -> list[str]:
    """Gaps between events within the workday (assumes ~1h per event)."""
    busy = sorted((e["minute"], e["minute"] + 60) for e in schedule)
    slots, cur = [], WORK_START
    for start, end in busy:
        if start > cur:
            slots.append(f"{cur//60:02d}:{cur%60:02d}–{start//60:02d}:{start%60:02d}")
        cur = max(cur, end)
    if cur < WORK_END:
        slots.append(f"{cur//60:02d}:{cur%60:02d}–{WORK_END//60:02d}:{WORK_END%60:02d}")
    return slots


def _content_for(kind: str, day: str, count: int) -> list[dict]:
    """Ready-to-post pieces from the content queue backing this channel's quota, so a
    quota slot shows a real draft to copy — not just 'write a post'. Never raises."""
    try:
        from app.content import queue
        return queue.pull_for_day(kind, day, count)
    except Exception:
        return []


def plan(day: str) -> dict:
    ensure_day(day)
    with get_session() as s:
        rows = s.query(DailyTask).filter_by(day=day).order_by(DailyTask.position).all()
        quotas = []
        for kind, count, label in QUOTAS:
            tasks = [{"id": t.id, "label": t.label, "done": t.done}
                     for t in rows if t.kind == kind]
            # Zip each quota slot with a queued piece (if the shelf has one for it).
            pieces = _content_for(kind, day, len(tasks))
            for i, t in enumerate(tasks):
                t["content"] = pieces[i] if i < len(pieces) else None
            quotas.append({"kind": kind, "label": label, "total": count,
                           "done": sum(1 for t in tasks if t["done"]),
                           "ready": len(pieces), "tasks": tasks})
        todos = [{"id": t.id, "label": t.label, "done": t.done}
                 for t in rows if t.kind == "todo"]
    schedule = day_schedule(day)
    return {"day": day, "quotas": quotas, "todos": todos,
            "schedule": schedule, "free": free_slots(schedule)}
