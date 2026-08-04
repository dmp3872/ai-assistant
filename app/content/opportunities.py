"""Turn community questions into Answer-Bank seeds (ContentOpportunity rows).

Recurring questions are the highest-leverage content you own: answer once, reuse
forever. This clusters the questions people actually ask in your Skool community into
canonical opportunities. Clustering is deliberately dependency-light — a normalized
keyword signature, no embeddings/Ollama — so it runs anywhere and is unit-testable.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from app.db import get_session
from app.db.models import ContentOpportunity, Item

# Common words that carry no topic signal. Question words are dropped too — "how do I
# reconstitute" and "reconstitute how much" should land on the same key.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "is", "are", "was", "were",
    "be", "been", "being", "to", "of", "in", "on", "for", "with", "at", "by", "from",
    "up", "about", "into", "over", "after", "do", "does", "did", "doing", "can", "could",
    "should", "would", "will", "shall", "may", "might", "must", "i", "you", "he", "she",
    "it", "we", "they", "me", "my", "your", "our", "this", "that", "these", "those",
    "how", "what", "when", "where", "why", "who", "which", "whom", "whose", "any",
    "some", "get", "got", "use", "using", "used", "need", "want", "know", "anyone",
    "please", "thanks", "thank", "hi", "hey", "guys", "there", "here", "just", "much",
    "many", "one", "also", "still", "even", "really", "way", "am", "have", "has", "had",
}
_QUESTION_WORDS = ("how", "what", "when", "where", "why", "who", "which", "does", "do",
                   "is", "are", "can", "should", "would", "will", "could", "any")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def is_question(text: str) -> bool:
    """A light 'is this a question' heuristic — a '?' anywhere, or a question-word open."""
    t = (text or "").strip().lower()
    if not t:
        return False
    if "?" in t:
        return True
    first = t.split()[0] if t.split() else ""
    return first in _QUESTION_WORDS


def _significant_tokens(text: str) -> list[str]:
    toks = _TOKEN_RE.findall((text or "").lower())
    return [t for t in toks if t not in _STOPWORDS and len(t) > 2]


def _sig_set(text: str) -> set[str]:
    return set(_significant_tokens(text))


def norm_key(text: str) -> str | None:
    """Signature that collapses near-duplicate questions to one cluster key.

    Sorted unique significant tokens, capped — order and filler don't matter, topic
    words do. Returns None when there's too little signal to cluster on."""
    sig = sorted(_sig_set(text))
    if len(sig) < 2:
        return None
    return " ".join(sig[:6])


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _canonical_question(text: str) -> str:
    """First question-ish sentence, trimmed, as the display question."""
    text = (text or "").strip()
    # prefer the sentence that contains the '?'
    for part in re.split(r"(?<=[.?!])\s+", text):
        if "?" in part:
            return part.strip()[:280]
    return text[:280]


def refresh_opportunities(min_occurrences: int = 1, max_new: int = 25,
                          similarity: float = 0.5) -> list[int]:
    """Scan community questions and upsert ContentOpportunity clusters.

    Clustering is greedy by Jaccard overlap of significant tokens: a question joins an
    existing cluster when it shares enough topic words (>= `similarity`), so paraphrases
    of the same question ("how do I reconstitute" / "reconstitute how much water") merge.
    Returns the ids of 'open' opportunities still needing an answer, most-asked first,
    capped at `max_new`.
    """
    with get_session() as s:
        items = (s.query(Item)
                 .filter(Item.source == "skool", Item.category == "community",
                         Item.spam == False)  # noqa: E712
                 .order_by(Item.id).all())

        # Greedy clustering: each cluster keeps the representative token set + key.
        clusters: list[dict] = []
        for it in items:
            text = f"{it.title or ''} {it.body_clean or ''}".strip()
            if not is_question(text):
                continue
            key = norm_key(text)
            if not key:
                continue
            toks = _sig_set(text)
            best, best_score = None, 0.0
            for c in clusters:
                score = _jaccard(toks, c["tokens"])
                if score > best_score:
                    best, best_score = c, score
            if best is not None and best_score >= similarity:
                best["count"] += 1
                if it.url and it.url not in best["sources"]:
                    best["sources"].append(it.url)
            else:
                clusters.append({"key": key, "tokens": toks,
                                 "question": _canonical_question(text),
                                 "sources": [it.url] if it.url else [], "count": 1})

        now = datetime.now(timezone.utc)
        open_ids: list[tuple[int, int]] = []  # (occurrences, id)
        for c in clusters:
            key = c["key"]
            if c["count"] < min_occurrences:
                continue
            existing = s.query(ContentOpportunity).filter_by(norm_key=key).first()
            if existing:
                existing.occurrences = c["count"]
                existing.last_seen = now
                existing.sources = json.dumps(c["sources"][:10])
                if existing.status == "open":
                    open_ids.append((existing.occurrences, existing.id))
            else:
                row = ContentOpportunity(
                    question=c["question"], norm_key=key, occurrences=c["count"],
                    sources=json.dumps(c["sources"][:10]),
                    suggested_format="skool_post", status="open", last_seen=now)
                s.add(row)
                s.flush()
                open_ids.append((row.occurrences, row.id))

    open_ids.sort(reverse=True)  # most-asked first
    return [oid for _, oid in open_ids[:max_new]]


def open_opportunities(limit: int = 200) -> list[dict]:
    with get_session() as s:
        rows = (s.query(ContentOpportunity)
                .order_by(ContentOpportunity.occurrences.desc(),
                          ContentOpportunity.id.desc()).limit(limit).all())
        return [{"id": r.id, "question": r.question, "occurrences": r.occurrences,
                 "status": r.status, "answer_piece_id": r.answer_piece_id,
                 "sources": json.loads(r.sources) if r.sources else []}
                for r in rows]


def mark_answered(opportunity_id: int, piece_id: int) -> None:
    with get_session() as s:
        row = s.get(ContentOpportunity, opportunity_id)
        if row:
            row.status = "answered"
            row.answer_piece_id = piece_id


def dismiss(opportunity_id: int) -> bool:
    with get_session() as s:
        row = s.get(ContentOpportunity, opportunity_id)
        if not row:
            return False
        row.status = "dismissed"
        return True
