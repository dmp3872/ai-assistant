"""The 45-minute pipeline. Invoked by launchd.

    lock -> emergency-stop check -> per-connector collect -> for each item:
    sanitize -> dedupe -> classify -> (persist) -> if needs_response: retrieve + draft;
    if sales: extract structured fields -> update dashboard state -> one notification.

Every step is defensive: one connector or one item failing never aborts the run.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.classifiers import classify, is_duplicate, tab_for_category
from app.collectors import get_enabled_collectors
from app.db import get_session, init_db
from app.db.models import Draft, Item, Sale
from app.drafting import draft_response, extract_sale
from app.drafting.sales_extractor import find_contradiction
from app.models import NormalizedItem
from app.retrieval import ingest_items
from app.scheduler.lock import FileLock, LockHeld
from app.scheduler.notify import notify
from app.security import audit, sanitize
from app.settings import get_settings

_settings = get_settings()


def _enrich(item: NormalizedItem) -> NormalizedItem:
    clean, injection = sanitize(item.body or "")
    item.body_clean = clean
    item.injection_flag = injection
    item.body_hash = item.compute_hash()
    result = classify(item)
    item.category = result["category"]
    item.priority = result["priority"]
    item.needs_response = result["needs_response"]
    item.spam = result["spam"]
    return item


def _persist_item(item: NormalizedItem) -> int:
    with get_session() as s:
        row = Item(
            source=item.source, source_id=item.source_id, thread_id=item.thread_id,
            author=item.author, author_handle=item.author_handle, url=item.url,
            created_at=item.created_at, title=item.title, body_clean=item.body_clean,
            body_hash=item.body_hash, category=item.category, priority=item.priority,
            needs_response=item.needs_response, injection_flag=item.injection_flag,
            spam=item.spam, raw_json=json.dumps(item.raw, default=str),
        )
        s.add(row)
        s.flush()
        return row.id


def _handle_item(item: NormalizedItem) -> bool:
    """Process one item end to end. Returns True if it was newly stored."""
    try:
        if is_duplicate(item):
            return False
        _enrich(item)
        if is_duplicate(item):  # content-hash dup found after enrich
            return False
        item_id = _persist_item(item)

        # PeptidePrice sales -> structured extraction + contradiction flag
        if item.category == "peptideprice_sales":
            fields = extract_sale(item)
            if fields:
                contradicts = find_contradiction(item_id, fields)
                with get_session() as s:
                    s.add(Sale(item_id=item_id, contradicts_sale_id=contradicts,
                               **fields.model_dump()))

        # Draftable items -> voice draft
        if item.needs_response and not item.spam:
            d = draft_response(item)
            if d:
                with get_session() as s:
                    s.add(Draft(item_id=item_id, draft_text=d["draft_text"],
                                confidence=d["confidence"], review_reason=d["review_reason"],
                                sources_used=d["sources_used"], model=d["model"]))

        # Seed retrieval from your own Skool content
        if item.source == "skool":
            ingest_items([item])
        return True
    except Exception as exc:
        audit("error", source=item.source, stage="handle", error=str(exc))
        return False


def run_cycle() -> dict:
    init_db()
    if _settings.emergency_stopped:
        audit("error", stage="emergency_stop")
        return {"status": "stopped", "reason": "EMERGENCY_STOP file present"}

    try:
        with FileLock(_settings.lock_path):
            started = datetime.now(timezone.utc)
            audit("collect", stage="cycle_start")
            new_count = 0
            by_source: dict[str, int] = {}

            for collector in get_enabled_collectors():
                items = collector.run()
                for item in items:
                    if _handle_item(item):
                        new_count += 1
                        by_source[item.source] = by_source.get(item.source, 0) + 1

            audit("collect", stage="cycle_end", new=new_count, by_source=by_source)
            if new_count:
                summary = ", ".join(f"{k}:{v}" for k, v in by_source.items())
                notify("Radar digest ready", f"{new_count} new items ({summary})")
            return {
                "status": "ok",
                "new": new_count,
                "by_source": by_source,
                "duration_s": (datetime.now(timezone.utc) - started).total_seconds(),
            }
    except LockHeld:
        return {"status": "skipped", "reason": "previous run still in progress"}


if __name__ == "__main__":
    print(json.dumps(run_cycle(), indent=2))
