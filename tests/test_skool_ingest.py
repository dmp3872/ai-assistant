"""Routing + normalization for Skool voice retrieval (no browser, no vector store)."""
from app.collectors.skool import SkoolCollector
from app.models import NormalizedItem
from app.retrieval.ingest import _namespace_for


def _item(kind, mine):
    return NormalizedItem(source="skool", source_id="x", body="text",
                          raw={"kind": kind, "authored_by_me": mine})


def test_namespace_routing():
    assert _namespace_for(_item("lesson", True)) == "courses"
    assert _namespace_for(_item("lesson", False)) == "courses"       # lessons always ingest
    assert _namespace_for(_item("post", True)) == "skool_posts"
    assert _namespace_for(_item("comment", True)) == "skool_comments"
    # someone else's post/comment is not your voice -> skipped
    assert _namespace_for(_item("post", False)) is None
    assert _namespace_for(_item("comment", False)) is None


def test_collector_authorship_detection():
    c = SkoolCollector()  # reads config.example.yaml: author_name "Derek Pruski", handle "derek"
    assert c._is_me("Derek Pruski", None) is True
    assert c._is_me("derek pruski", None) is True           # case-insensitive
    assert c._is_me("Jane Doe", None) is False
    assert c._is_me(None, "@derek") is True                  # handle match
    assert c._is_me(None, "someone") is False


def test_collector_normalize_tags_author():
    c = SkoolCollector()
    rec = {"kind": "post", "id": "p9", "title": "T", "author": "Derek Pruski",
           "body": "b", "url": "u", "created_at": "2026-01-01T00:00:00Z", "parent_id": None}
    item = c._normalize(rec, None)
    assert item.raw["authored_by_me"] is True
    assert item.raw["kind"] == "post"


def test_collector_to_dt_handles_iso_and_epoch():
    c = SkoolCollector()
    dt_iso, ts_iso = c._to_dt("2026-01-01T00:00:00Z")
    assert ts_iso > 0 and dt_iso is not None
    dt_ms, ts_ms = c._to_dt(1767225600000)   # ms epoch
    dt_s, ts_s = c._to_dt(1767225600)        # sec epoch
    assert abs(ts_ms - ts_s) < 1             # same instant, different units
    assert c._to_dt(None) == (None, 0.0)
