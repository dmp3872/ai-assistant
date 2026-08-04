"""The content engine — keeps your shelf stocked so you always have something ready.

Called once per collection cycle (guarded, never aborts the run). Two jobs:

  1. Answer Bank — cluster recurring community questions, draft a canonical answer for
     any that don't have one yet (capped per cycle).
  2. Post Queue — top each channel up to a target depth with fresh, grounded posts.

Everything it produces is queued for YOUR review. Nothing is ever posted anywhere.
Dedup keys make it idempotent: a full shelf means (near) zero API calls next cycle.
"""
from __future__ import annotations

from app.content import generator, opportunities, queue
from app.content.opportunities import norm_key
from app.retrieval import get_store
from app.security import audit
from app.settings import get_settings

_settings = get_settings()

_DEFAULT_TARGETS = {"skool": 10, "tiktok": 6, "substack": 3, "youtube": 1}


def _cfg() -> dict:
    return _settings.config.get("content", {}) or {}


def enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def _targets() -> dict[str, int]:
    t = dict(_DEFAULT_TARGETS)
    t.update(_cfg().get("queue_targets", {}) or {})
    return t


def _classroom_seeds(limit: int) -> list[str]:
    """A few grounding topics drawn from your own classroom material."""
    try:
        hits = get_store().search("courses", "core teaching topics for my audience", k=limit)
    except Exception:
        return []
    seeds = []
    for h in hits:
        text = (h.get("text") or "").strip()
        if text:
            seeds.append(text[:200])
    return seeds


def _post_seeds(limit: int) -> list[tuple[str, str, int | None]]:
    """Assemble candidate post seeds: recurring questions, configured evergreen topics,
    then classroom material. Returns [(seed_text, origin, opportunity_id)] deduped by
    topic signature so we never queue two posts on the same thing."""
    seeds: list[tuple[str, str, int | None]] = []
    seen_keys: set[str] = set()

    def _push(text: str, origin: str, opp_id: int | None) -> None:
        if not text:
            return
        key = norm_key(text) or text.lower().strip()
        if key in seen_keys:
            return
        seen_keys.add(key)
        seeds.append((text, origin, opp_id))

    for opp in opportunities.open_opportunities(limit=50):
        if opp["status"] != "dismissed":
            _push(opp["question"], "opportunity", opp["id"])
    for topic in (_cfg().get("seed_topics", []) or []):
        _push(str(topic), "manual", None)
    for text in _classroom_seeds(limit=12):
        _push(text, "classroom", None)

    return seeds[: max(limit * 3, 12)]


def _replenish_answers(max_answers: int) -> int:
    """Draft canonical answers for open opportunities that don't have one. Capped."""
    if max_answers <= 0:
        return 0
    open_ids = [o for o in opportunities.open_opportunities()
                if o["status"] == "open" and not o["answer_piece_id"]]
    created = 0
    for opp in open_ids:
        if created >= max_answers:
            break
        ans = generator.generate_answer(opp["question"])
        if not ans:
            continue
        piece_id = queue.add_piece({
            "channel": "skool", "kind": "answer", "origin": "opportunity",
            "opportunity_id": opp["id"], "origin_ref": str(opp["id"]),
            "title": ans["title"], "body": ans["body"],
            "confidence": ans["confidence"], "review_reason": ans["review_reason"],
            "sources_used": ans["sources_used"], "model": ans["model"],
            "dedupe_key": f"answer:{opp['id']}",
        })
        if piece_id:
            opportunities.mark_answered(opp["id"], piece_id)
            created += 1
    return created


def _replenish_posts(max_posts: int) -> dict[str, int]:
    """Top each channel up to its target depth, drawing from shared seeds. Capped total."""
    if max_posts <= 0:
        return {}
    targets = _targets()
    seeds = _post_seeds(limit=max_posts)
    made: dict[str, int] = {}
    total = 0
    for channel, target in targets.items():
        if total >= max_posts:
            break
        avoid = [p["title"] for p in queue.list_pieces(channel=channel, status="open")
                 if p.get("title")]
        for seed_text, origin, opp_id in seeds:
            if total >= max_posts or queue.depth_by_channel(channel) >= target:
                break
            dk = f"{channel}:post:{norm_key(seed_text) or seed_text.lower()[:80]}"
            # Skip cheaply before spending an API call if this topic is already queued.
            if any(p.get("title") for p in queue.list_pieces(channel=channel)
                   if p.get("origin_ref") == dk):
                continue
            post = generator.generate_post(channel, seed_text, avoid_titles=avoid)
            if not post:
                continue
            piece_id = queue.add_piece({
                "channel": channel, "kind": "post", "origin": origin,
                "opportunity_id": opp_id, "origin_ref": dk,
                "title": post["title"], "hook": post["hook"], "body": post["body"],
                "cta": post["cta"], "angle": post["angle"], "tags": post["tags"],
                "confidence": post["confidence"], "review_reason": post["review_reason"],
                "sources_used": post["sources_used"], "model": post["model"],
                "dedupe_key": dk,
            })
            if piece_id:
                made[channel] = made.get(channel, 0) + 1
                total += 1
                avoid.append(post["title"])
    return made


def replenish() -> dict:
    """Cycle entry point. Cluster questions, then fill the answer bank and post queue up
    to targets. Cheap no-op when the shelf is already full or content is disabled."""
    if not enabled():
        return {"status": "disabled"}

    cfg = _cfg()
    try:
        opportunities.refresh_opportunities(
            min_occurrences=int(cfg.get("min_question_occurrences", 1)))
    except Exception as exc:
        audit("error", stage="content_opportunities", error=str(exc))

    # Only spend generation budget on channels that are actually below target.
    targets = _targets()
    below = {c: t for c, t in targets.items() if queue.depth_by_channel(c) < t}
    open_needs_answer = any(o["status"] == "open" and not o["answer_piece_id"]
                            for o in opportunities.open_opportunities())
    if not below and not open_needs_answer:
        return {"status": "full", "answers_created": 0, "posts_created": {},
                "queue": queue.stats()}

    answers = 0
    posts: dict[str, int] = {}
    try:
        answers = _replenish_answers(int(cfg.get("max_answers_per_cycle", 3)))
    except Exception as exc:
        audit("error", stage="content_answers", error=str(exc))
    try:
        posts = _replenish_posts(int(cfg.get("max_posts_per_cycle", 5)))
    except Exception as exc:
        audit("error", stage="content_posts", error=str(exc))

    result = {"status": "ok", "answers_created": answers, "posts_created": posts,
              "queue": queue.stats()}
    audit("draft", subtype="content_replenish", answers=answers,
          posts=sum(posts.values()))
    return result
