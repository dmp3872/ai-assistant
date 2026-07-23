"""Import Skool content into the retrieval store for voice/knowledge retrieval.

    python scripts/import_skool.py                 # feed history + classroom
    python scripts/import_skool.py --classroom-only # just courses/lessons
    python scripts/import_skool.py --feed-only       # just posts/comments
    python scripts/import_skool.py --debug           # dump what was discovered, no ingest

This is the one-time (re-runnable) deep import. The 45-minute cycle keeps things fresh
incrementally afterward. Bodies are HTML-stripped before embedding; items are routed by
authorship/kind (your posts/comments -> voice namespaces, lessons -> `courses`).
"""

from __future__ import annotations

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse

from app.collectors.skool import SkoolCollector
from app.models import NormalizedItem
from app.retrieval import ingest_skool
from app.security import sanitize


def _clean(items: list[NormalizedItem]) -> list[NormalizedItem]:
    for it in items:
        it.body_clean, _ = sanitize(it.body or "")
    return items


def _collect(feed: bool, classroom: bool) -> list[NormalizedItem]:
    collector = SkoolCollector()
    if feed and classroom:
        return collector.historical_import()
    if classroom:
        return collector.import_classroom()
    # feed-only: reuse the incremental path from a zero cursor
    items, _ = collector.fetch_new(None)
    return items


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--classroom-only", action="store_true")
    ap.add_argument("--feed-only", action="store_true")
    ap.add_argument("--debug", action="store_true", help="print discovered items, no ingest")
    args = ap.parse_args()

    feed = not args.classroom_only
    classroom = not args.feed_only

    print(f"Collecting from Skool (feed={feed}, classroom={classroom})…")
    items = _clean(_collect(feed, classroom))

    kinds: dict[str, int] = {}
    mine = 0
    for it in items:
        k = (it.raw or {}).get("kind", "?")
        kinds[k] = kinds.get(k, 0) + 1
        if (it.raw or {}).get("authored_by_me"):
            mine += 1
    print(f"  collected {len(items)} items: {kinds} | authored-by-you: {mine}")

    if args.debug:
        for it in items[:25]:
            tag = "ME" if (it.raw or {}).get("authored_by_me") else "  "
            print(f"  [{tag}] {(it.raw or {}).get('kind','?'):8} | "
                  f"{(it.title or '')[:50]:50} | {len(it.body_clean or '')} chars | {it.url}")
        print("\n--debug: nothing ingested. Verify authorship + fields look right, then "
              "re-run without --debug.")
        return

    counts = ingest_skool(items)
    print(f"  ingested chunks -> {counts}")
    print("Done. Your voice namespaces (skool_posts, skool_comments, courses) are seeded.")


if __name__ == "__main__":
    main()
