"""Standalone Video Clipper job runner (app/video/jobs.py).

No ffmpeg/Whisper in CI, so jobs are fed a transcript file and land in 'plan_only' (cut
points computed; cutting skipped with a clear status). That still exercises the whole job
lifecycle and progress. The runner is self-contained — no DB, no content queue.
"""
import time

from app.video import jobs


def _srt(path):
    lines, t = [], 0.0
    def fmt(x):
        h = int(x // 3600); m = int((x % 3600) // 60); s = x % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")
    for i in range(240):  # 240 x 5s = 20 min
        a, b = t, t + 5
        lines.append(f"{i+1}\n{fmt(a)} --> {fmt(b)}\nSentence {i}.\n")
        t = b
    path.write_text("\n".join(lines))
    return str(path)


def _wait(job_id, timeout=15):
    for _ in range(int(timeout * 10)):
        j = jobs.get_job(job_id)
        if j and j["status"] in ("done", "plan_only", "error"):
            return j
        time.sleep(0.1)
    return jobs.get_job(job_id)


def _opts(**kw):
    base = {"min": 5, "max": 7, "target": 6, "model": "base", "fast": False}
    base.update(kw)
    return base


def test_job_runs_and_plans_clips(tmp_path):
    jid = jobs.create_job(_srt(tmp_path / "demo.srt"), "demo.srt", _opts())
    j = _wait(jid)
    assert j["status"] == "plan_only"      # no ffmpeg in CI -> plan only
    assert j["est_clips"] and len(j["clips"]) == j["est_clips"]
    c0 = j["clips"][0]
    assert c0["start_hms"] == "00:00:00.000"
    assert c0["reason"]
    assert c0["ok"] is False               # not cut (no ffmpeg)
    assert j["progress"] == 1.0


def test_short_length_makes_more_clips(tmp_path):
    src = _srt(tmp_path / "demo.srt")
    std = _wait(jobs.create_job(src, "d.srt", _opts(min=5, max=7, target=6)))
    short = _wait(jobs.create_job(src, "d.srt", _opts(min=1, max=2, target=1.5)))
    assert short["est_clips"] > std["est_clips"]   # shorter clips -> more of them


def test_job_error_on_empty_transcript(tmp_path):
    empty = tmp_path / "empty.srt"
    empty.write_text("")
    j = _wait(jobs.create_job(str(empty), "empty.srt", _opts()))
    assert j["status"] == "error"
    assert "nothing to clip" in (j["error"] or "").lower()


def test_public_job_has_no_source_leak(tmp_path):
    j = _wait(jobs.create_job(_srt(tmp_path / "demo.srt"), "demo.srt", _opts()))
    # job view is JSON-serializable primitives (no raw Clip objects)
    import json
    json.dumps(j)
