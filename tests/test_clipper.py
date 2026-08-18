"""Dashboard Clipper job manager — runs the real transcribe→segment→(cut) pipeline.

No ffmpeg/Whisper here, so jobs are fed a transcript file and land in 'plan_only' (the
cut points are computed; cutting is skipped with a clear status). That still exercises the
whole job lifecycle, progress, and the queue bridge.
"""
import time

from app.content import queue
from app.dashboard import clipper
from app.db import get_session, init_db
from app.db.models import ContentPiece


def _srt(path):
    lines, t = [], 0.0
    def fmt(x):
        h = int(x // 3600); m = int((x % 3600) // 60); s = x % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")
    for i in range(240):  # 240 x 5s = 20 min
        a, b = t, t + 5
        txt = "So, let's talk about the next idea." if i % 40 == 0 and i else f"Sentence {i}."
        lines.append(f"{i+1}\n{fmt(a)} --> {fmt(b)}\n{txt}\n")
        t = b
    path.write_text("\n".join(lines))
    return str(path)


def _wait(job_id, timeout=15):
    for _ in range(int(timeout * 10)):
        j = clipper.get_job(job_id)
        if j and j["status"] in ("done", "plan_only", "error"):
            return j
        time.sleep(0.1)
    return clipper.get_job(job_id)


def test_job_runs_and_plans_clips(tmp_path):
    src = _srt(tmp_path / "demo.srt")
    jid = clipper.create_job(src, "demo.srt",
                             {"min": 5, "max": 7, "target": 6, "model": "base",
                              "fast": False, "queue_channel": None})
    j = _wait(jid)
    assert j["status"] == "plan_only"      # no ffmpeg in CI -> plan only
    assert j["est_clips"] == 3
    assert len(j["clips"]) == 3
    c0 = j["clips"][0]
    assert c0["start_hms"] == "00:00:00.000"
    assert c0["reason"]
    assert c0["ok"] is False               # not cut (no ffmpeg)
    assert j["progress"] == 1.0


def test_job_error_on_empty_transcript(tmp_path):
    empty = tmp_path / "empty.srt"
    empty.write_text("")
    jid = clipper.create_job(str(empty), "empty.srt",
                             {"min": 5, "max": 7, "target": 6, "model": "base",
                              "fast": False, "queue_channel": None})
    j = _wait(jid)
    assert j["status"] == "error"
    assert "nothing to clip" in (j["error"] or "").lower()


def test_queue_job_pushes_clips(tmp_path):
    init_db()
    with get_session() as s:
        s.query(ContentPiece).delete()
    src = _srt(tmp_path / "demo.srt")
    jid = clipper.create_job(src, "demo.srt",
                             {"min": 5, "max": 7, "target": 6, "model": "base",
                              "fast": False, "queue_channel": None})
    _wait(jid)
    out = clipper.queue_job(jid, "tiktok")   # plan_only still keeps _clips for queueing
    assert out["ok"] and out["added"] == 3
    assert queue.depth_by_channel("tiktok") == 3


def test_public_view_hides_private_keys(tmp_path):
    src = _srt(tmp_path / "demo.srt")
    jid = clipper.create_job(src, "demo.srt",
                             {"min": 5, "max": 7, "target": 6, "model": "base",
                              "fast": False, "queue_channel": None})
    j = _wait(jid)
    assert not any(k.startswith("_") for k in j)   # no _clips/_results leaked to API
