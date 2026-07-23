"""TikTok profile parsing from the server-rendered SIGI_STATE JSON (offline)."""
import json

from app.collectors import tiktok_parse as tp


def _page(state):
    return f'<html><script id="SIGI_STATE" type="application/json">{json.dumps(state)}</script></html>'


STATE = {"ItemModule": {
    "7401": {"id": "7401", "desc": "leg day never skipped 🦵 #peptides",
             "createTime": "1753200000",
             "stats": {"diggCount": 1200, "commentCount": 47, "playCount": 33000, "shareCount": 12},
             "author": "dereklifts2"},
    "7402": {"id": "7402", "desc": "BPC-157 explained",
             "createTime": "1753100000",
             "stats": {"diggCount": 800, "commentCount": 19, "playCount": 21000, "shareCount": 4},
             "author": "dereklifts2"},
}}


def test_parse_profile_extracts_videos_with_real_links():
    vids = tp.parse_profile(_page(STATE), "dereklifts2")
    assert len(vids) == 2
    v = next(x for x in vids if x["id"] == "7401")
    assert v["url"] == "https://www.tiktok.com/@dereklifts2/video/7401"
    assert v["comment_count"] == 47
    assert v["desc"].startswith("leg day")
    assert v["create_time"].startswith("2025-")  # unix -> ISO


def test_parse_profile_handles_universal_data_shape():
    page = ('<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">'
            + json.dumps({"__DEFAULT_SCOPE__": {"webapp.user-detail": {"itemList": [
                {"id": "999", "desc": "test clip", "createTime": "1753000000",
                 "stats": {"commentCount": 3}}]}}}) + "</script>")
    vids = tp.parse_profile(page, "dereklifts2")
    assert len(vids) == 1 and vids[0]["id"] == "999" and vids[0]["comment_count"] == 3


def test_no_data_returns_empty():
    assert tp.parse_profile("<html>nothing</html>", "dereklifts2") == []


def test_collector_normalizes(monkeypatch):
    from app.collectors.tiktok import TikTokCollector
    c = TikTokCollector.__new__(TikTokCollector)  # bypass config __init__
    c.name = "tiktok"; c.username = "dereklifts2"; c.cookie = None
    monkeypatch.setattr(c, "_fetch_html", lambda: _page(STATE))
    items, cursor = c.fetch_new(None)
    assert len(items) == 2
    it = next(i for i in items if i.source_id == "7401")
    assert it.url == "https://www.tiktok.com/@dereklifts2/video/7401"
    assert it.raw["comment_count"] == 47
    assert it.author == "@dereklifts2"
