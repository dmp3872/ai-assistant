"""Ingest content into the retrieval store.

- ingest_items: seed namespaces from collected items (e.g. your Skool posts/comments).
- ingest_review_examples: re-embed your approved/edited responses so drafts drift
  toward how you actually write. This closes the learning loop from review_history.
"""
from __future__ import annotations

from app.models import NormalizedItem
from app.retrieval.store import get_store

# map a source to the namespace its content belongs in
_SOURCE_NAMESPACE = {
    "skool": "skool_posts",
    "tiktok": "tiktok_transcripts",
}


def ingest_items(items: list[NormalizedItem], namespace: str | None = None) -> int:
    store = get_store()
    n = 0
    for it in items:
        ns = namespace or _SOURCE_NAMESPACE.get(it.source)
        if not ns:
            continue
        store.add(ns, it.body_clean or it.body, source=it.source,
                  url=it.url or "", ref_id=it.source_id)
        n += 1
    return n


def ingest_review_examples(examples: list[dict]) -> int:
    """examples: [{text, url, ref_id}] of responses you approved/edited."""
    store = get_store()
    for ex in examples:
        store.add("approved_email_responses", ex["text"],
                  source="review", url=ex.get("url", ""), ref_id=ex.get("ref_id", ""))
    return len(examples)
