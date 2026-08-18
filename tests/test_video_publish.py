"""Clips → Studio content queue bridge."""
from app.content import queue
from app.db import get_session, init_db
from app.db.models import ContentPiece
from app.video.publish import clip_to_piece, queue_clips
from app.video.segment import Clip


def _reset():
    init_db()
    with get_session() as s:
        s.query(ContentPiece).delete()


def _clips():
    return [
        Clip(index=0, start=0.0, end=360.0, reason="sentence end", text="Intro talk.",
             title="The Intro"),
        Clip(index=1, start=360.0, end=720.0, reason="topic shift", text="Main point.",
             title="The Main Point"),
    ]


def test_clip_to_piece_shape():
    c = _clips()[0]
    p = clip_to_piece("/videos/podcast.mp4", c, "youtube", file_path="/out/clip_01.mp4")
    assert p["channel"] == "youtube"
    assert p["kind"] == "video_clip"
    assert p["title"] == "The Intro"
    assert p["body"] == "Intro talk."
    assert "podcast.mp4" in p["tags"][0]
    assert p["dedupe_key"] == "clip:podcast.mp4:0.0-360.0"
    assert p["origin_ref"].endswith("clip_01.mp4")


def test_queue_clips_adds_pieces_to_channel():
    _reset()
    clips = _clips()
    results = [{"index": 0, "ok": True, "path": "/out/clip_01.mp4"},
               {"index": 1, "ok": True, "path": "/out/clip_02.mp4"}]
    out = queue_clips("/videos/podcast.mp4", clips, channel="tiktok", results=results)
    assert out["added"] == 2
    assert out["channel"] == "tiktok"
    assert queue.depth_by_channel("tiktok") == 2
    rows = queue.list_pieces(channel="tiktok", status="open")
    assert all(r["kind"] == "video_clip" for r in rows)
    assert {r["title"] for r in rows} == {"The Intro", "The Main Point"}


def test_queue_clips_is_idempotent():
    _reset()
    clips = _clips()
    results = [{"index": 0, "ok": True, "path": "/out/a.mp4"},
               {"index": 1, "ok": True, "path": "/out/b.mp4"}]
    queue_clips("/v/pod.mp4", clips, results=results)
    again = queue_clips("/v/pod.mp4", clips, results=results)  # same clips
    assert again["added"] == 0
    assert again["skipped"] == 2       # dedup hits
    assert queue.stats()["open_total"] == 2  # not doubled


def test_queue_clips_skips_failed_cuts():
    _reset()
    clips = _clips()
    results = [{"index": 0, "ok": True, "path": "/out/a.mp4"},
               {"index": 1, "ok": False, "error": "ffmpeg blew up"}]
    out = queue_clips("/v/pod.mp4", clips, channel="youtube", results=results)
    assert out["added"] == 1           # only the clip that was written
    assert out["skipped"] == 1
    assert queue.depth_by_channel("youtube") == 1


def test_queue_clips_without_results_queues_all():
    _reset()
    out = queue_clips("/v/pod.mp4", _clips(), channel="youtube")  # no results -> plan-only
    assert out["added"] == 2
