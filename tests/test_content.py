"""Content engine: clustering, queue accounting, and the replenish orchestrator.

No cloud, no Ollama. Generation is monkeypatched so we test the engine's logic — depth
targets, dedup, idempotency, no-op-when-full — not the Claude call itself.
"""
from app.content import engine, opportunities, queue
from app.content.opportunities import is_question, norm_key
from app.db import get_session, init_db
from app.db.models import ContentOpportunity, ContentPiece, Item


def _reset():
    init_db()
    with get_session() as s:
        s.query(ContentPiece).delete()
        s.query(ContentOpportunity).delete()
        s.query(Item).delete()


def _add_community_question(source_id: str, body: str, url: str = ""):
    with get_session() as s:
        s.add(Item(source="skool", source_id=source_id, category="community",
                   body_clean=body, url=url, spam=False))


# --- question detection + clustering ---------------------------------------------

def test_is_question_heuristic():
    assert is_question("Does LC-MS confirm authenticity?")
    assert is_question("how do I reconstitute this")
    assert not is_question("Here is my log for the week.")


def test_norm_key_collapses_near_duplicates():
    a = norm_key("How do I reconstitute BPC-157?")
    b = norm_key("reconstitute BPC-157 — how much bac water?")
    assert a is not None and b is not None
    # both share the salient tokens 'reconstitute' + 'bpc' -> overlapping signature
    assert "reconstitute" in a and "reconstitute" in b


def test_refresh_opportunities_clusters_repeats():
    _reset()
    _add_community_question("q1", "How do I reconstitute BPC-157?", "u1")
    _add_community_question("q2", "reconstitute BPC-157 how much bac water?", "u2")
    _add_community_question("q3", "Which vendor has the best COA?", "u3")
    ids = opportunities.refresh_opportunities(min_occurrences=1)
    opps = opportunities.open_opportunities()
    # the two reconstitution phrasings collapse to one opportunity; COA is a second
    assert len(opps) == 2
    recon = next(o for o in opps if "reconstitute" in o["question"].lower())
    assert recon["occurrences"] == 2
    assert set(ids)  # returns the open ids

    # idempotent: a second pass updates counts, doesn't duplicate rows
    opportunities.refresh_opportunities(min_occurrences=1)
    assert len(opportunities.open_opportunities()) == 2


def test_min_occurrences_gate():
    _reset()
    _add_community_question("q1", "Is 10mg the right vial size for research?")
    opportunities.refresh_opportunities(min_occurrences=2)  # asked once, needs 2
    assert opportunities.open_opportunities() == []


# --- queue accounting -------------------------------------------------------------

def test_queue_depth_and_dedupe():
    _reset()
    pid = queue.add_piece({"channel": "skool", "kind": "post", "body": "hello",
                           "dedupe_key": "k1"})
    assert pid is not None
    assert queue.depth_by_channel("skool") == 1
    # same dedupe_key -> skipped, not duplicated
    assert queue.add_piece({"channel": "skool", "body": "hello again",
                            "dedupe_key": "k1"}) is None
    assert queue.depth_by_channel("skool") == 1


def test_status_transitions_drop_from_depth():
    _reset()
    pid = queue.add_piece({"channel": "tiktok", "body": "x"})
    assert queue.depth_by_channel("tiktok") == 1
    queue.set_status(pid, "posted", edited_text="what I really posted")
    assert queue.depth_by_channel("tiktok") == 0  # posted no longer counts
    with get_session() as s:
        row = s.get(ContentPiece, pid)
        assert row.edited_text == "what I really posted"
        assert row.posted_at is not None


def test_pull_for_day_pins_and_is_stable():
    _reset()
    for i in range(3):
        queue.add_piece({"channel": "skool", "body": f"post {i}"})
    day = "2026-08-04"
    first = queue.pull_for_day("skool", day, 2)
    assert len(first) == 2
    # a second pull for the same day returns the SAME pinned pieces (stable planner cards)
    second = queue.pull_for_day("skool", day, 2)
    assert [p["id"] for p in first] == [p["id"] for p in second]


# --- replenish orchestrator (generation stubbed) ---------------------------------

def test_replenish_generates_answers_and_posts(monkeypatch):
    _reset()
    _add_community_question("q1", "How do I reconstitute BPC-157?")
    _add_community_question("q2", "reconstitute BPC-157 how much water?")

    monkeypatch.setattr(engine.generator, "generate_answer",
                        lambda q: {"title": "Reconstitution", "body": "Use bac water.",
                                   "confidence": "high", "review_reason": "",
                                   "sources_used": [], "model": "test"})
    monkeypatch.setattr(engine.generator, "generate_post",
                        lambda ch, seed, avoid_titles=None: {
                            "title": f"{ch}:{seed[:12]}", "hook": "h", "body": "b",
                            "cta": "c", "angle": "a", "tags": [], "confidence": "medium",
                            "review_reason": "", "sources_used": [], "model": "test"})
    # keep the test cheap + deterministic
    monkeypatch.setattr(engine, "_cfg", lambda: {
        "enabled": True, "queue_targets": {"skool": 3},
        "max_posts_per_cycle": 3, "max_answers_per_cycle": 2,
        "min_question_occurrences": 1})

    result = engine.replenish()
    assert result["status"] == "ok"
    assert result["answers_created"] == 1          # one cluster -> one canonical answer
    assert result["posts_created"].get("skool", 0) >= 1
    # the answered opportunity is linked to its piece
    answered = [o for o in opportunities.open_opportunities() if o["status"] == "answered"]
    assert answered and answered[0]["answer_piece_id"]


def test_replenish_is_noop_when_full(monkeypatch):
    _reset()
    # fill skool to target; no open opportunities exist
    for i in range(3):
        queue.add_piece({"channel": "skool", "body": f"p{i}"})

    def _boom(*a, **k):
        raise AssertionError("generation must not run when the shelf is full")

    monkeypatch.setattr(engine.generator, "generate_answer", _boom)
    monkeypatch.setattr(engine.generator, "generate_post", _boom)
    monkeypatch.setattr(engine, "_cfg", lambda: {
        "enabled": True, "queue_targets": {"skool": 3, "tiktok": 0,
                                            "substack": 0, "youtube": 0},
        "min_question_occurrences": 1})

    result = engine.replenish()
    assert result["status"] == "full"


def test_replenish_respects_disabled(monkeypatch):
    _reset()
    monkeypatch.setattr(engine, "_cfg", lambda: {"enabled": False})
    assert engine.replenish()["status"] == "disabled"


def test_replenish_survives_generation_failure(monkeypatch):
    _reset()
    _add_community_question("q1", "How do I store peptides long term?")

    monkeypatch.setattr(engine.generator, "generate_answer",
                        lambda q: (_ for _ in ()).throw(RuntimeError("api down")))
    monkeypatch.setattr(engine.generator, "generate_post", lambda *a, **k: None)
    monkeypatch.setattr(engine, "_cfg", lambda: {
        "enabled": True, "queue_targets": {"skool": 2},
        "max_answers_per_cycle": 2, "max_posts_per_cycle": 2,
        "min_question_occurrences": 1})

    # must not raise; a failed generator just yields nothing
    result = engine.replenish()
    assert result["status"] == "ok"
    assert result["answers_created"] == 0
