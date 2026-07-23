"""Ingest content into the retrieval store.

Routing for Skool content (this is the voice-retrieval core):
  * lesson              -> `courses`          (your classroom material — always)
  * post, authored_by_me    -> `skool_posts`     (your voice)
  * comment, authored_by_me -> `skool_comments`  (your voice)
  * anyone else's post/comment -> skipped for voice (not your writing)

Long text is chunked before embedding. Each chunk is stored with a title prefix so a
retrieved snippet carries its lesson/post context, and a ref_id of `source_id#<chunk>`.

- ingest_items: generic seed by source (kept for other collectors).
- ingest_skool: the routed, chunked path used by the historical/classroom import.
- ingest_review_examples: re-embed your approved responses as style examples.
"""
from __future__ import annotations

from app.models import NormalizedItem
from app.retrieval.chunk import chunk_text
from app.retrieval.store import get_store

_SOURCE_NAMESPACE = {"skool": "skool_posts", "tiktok": "tiktok_transcripts"}


def _namespace_for(item: NormalizedItem) -> str | None:
    kind = (item.raw or {}).get("kind")
    mine = bool((item.raw or {}).get("authored_by_me"))
    if kind == "lesson":
        return "courses"
    if kind == "post" and mine:
        return "skool_posts"
    if kind == "comment" and mine:
        return "skool_comments"
    return None


def _add_chunked(store, namespace: str, item: NormalizedItem) -> int:
    text = (item.body_clean or item.body or "").strip()
    if not text:
        return 0
    n = 0
    for i, chunk in enumerate(chunk_text(text)):
        payload = f"[{item.title}] {chunk}" if item.title else chunk
        store.add(namespace, payload, source="skool",
                  url=item.url or "", ref_id=f"{item.source_id}#{i}")
        n += 1
    return n


def ingest_skool(items: list[NormalizedItem]) -> dict[str, int]:
    """Route + chunk Skool items into voice/course namespaces. Returns per-namespace
    counts (of chunks) plus how many items were skipped as not-your-writing."""
    store = get_store()
    counts = {"courses": 0, "skool_posts": 0, "skool_comments": 0, "skipped": 0}
    for it in items:
        ns = _namespace_for(it)
        if ns is None:
            counts["skipped"] += 1
            continue
        counts[ns] += _add_chunked(store, ns, it)
    return counts


def ingest_items(items: list[NormalizedItem], namespace: str | None = None) -> int:
    """Generic seed. For Skool prefer ingest_skool (routing + chunking + authorship)."""
    store = get_store()
    n = 0
    for it in items:
        ns = namespace or _SOURCE_NAMESPACE.get(it.source)
        if not ns:
            continue
        n += _add_chunked(store, ns, it)
    return n


def ingest_review_examples(examples: list[dict]) -> int:
    store = get_store()
    for ex in examples:
        store.add("approved_email_responses", ex["text"],
                  source="review", url=ex.get("url", ""), ref_id=ex.get("ref_id", ""))
    return len(examples)
