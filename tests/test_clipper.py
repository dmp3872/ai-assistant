"""Standalone Video Clipper job runner (app/video/jobs.py).

No ffmpeg/Whisper in CI, so jobs are fed a transcript file and land in 'plan_only' (cut
points computed; cutting skipped). The runner is self-contained — no DB, no content queue.
"""
import time

from app.video import jobs


def _plain_srt(path, n=240):
    """Filler transcript (no engagement) — used for even-chunk counting."""
    lines, t = [], 0.0
    def fmt(x):
        h = int(x // 3600); m = int((x % 3600) // 60); s = x % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")
    for i in range(n):
        lines.append(f"{i+1}\n{fmt(t)} --> {fmt(t+5)}\nWe should probably discuss the schedule.\n")
        t += 5
    path.write_text("\n".join(lines))
    return str(path)


def _wait(job_id, timeout=15):
    for _ in range(int(timeout * 10)):
        j = jobs.get_job(job_id)
        if j and j["status"] in ("done", "plan_only", "error"):
            return j
        time.sleep(0.1)
    return jobs.get_job(job_id)


def _opts(mode="even", **kw):
    base = {"mode": mode, "min": 5, "max": 7, "target": 6, "model": "base", "fast": False}
    base.update(kw)
    return base


def test_even_mode_plans_uniform_chunks(tmp_path):
    jid = jobs.create_job(_plain_srt(tmp_path / "d.srt"), "d.srt", _opts(mode="even"))
    j = _wait(jid)
    assert j["status"] == "plan_only"      # no ffmpeg in CI -> plan only
    assert j["est_clips"] and len(j["clips"]) == j["est_clips"]
    c0 = j["clips"][0]
    assert c0["start_hms"] == "00:00:00.000"
    assert c0["ok"] is False               # not cut (no ffmpeg)
    assert j["progress"] == 1.0


def test_highlights_mode_selects_engaging_moments(tmp_path):
    # a boring run, then one clearly engaging moment
    lines, t = [], 0.0
    def fmt(x):
        h = int(x // 3600); m = int((x % 3600) // 60); s = x % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")
    def add(txt, dur=5.0):
        nonlocal t
        lines.append(f"{len(lines)+1}\n{fmt(t)} --> {fmt(t+dur)}\n{txt}\n"); t += dur
    for _ in range(30):
        add("We should probably discuss the schedule for the meeting.")
    add("So here's the biggest mistake people make, and it's honestly insane.")
    add("When I first started I wasted 2,000 dollars on a total disaster.")
    add("Why? Because nobody tells you the one secret that changes everything.")
    for _ in range(6):
        add("The lab results were only 40 percent pure, which is crazy dangerous.")
    for _ in range(30):
        add("Anyway back to the boring logistics of the room booking, I guess.")
    p = tmp_path / "eng.srt"; p.write_text("\n".join(lines))

    j = _wait(jobs.create_job(str(p), "eng.srt", _opts(mode="highlights", max=8, target=3)))
    assert j["status"] == "plan_only"
    # far fewer than the ~12 uniform chunks this 9-min file would slice into
    assert 1 <= len(j["clips"]) <= 4
    top = j["clips"][0]
    assert top["score"] is not None and top["reason"]


def test_job_error_on_empty_transcript(tmp_path):
    empty = tmp_path / "empty.srt"
    empty.write_text("")
    j = _wait(jobs.create_job(str(empty), "empty.srt", _opts()))
    assert j["status"] == "error"
    assert "nothing to clip" in (j["error"] or "").lower()


def test_public_job_is_json_safe(tmp_path):
    import json
    j = _wait(jobs.create_job(_plain_srt(tmp_path / "d.srt", n=120), "d.srt", _opts()))
    json.dumps(j)  # no raw objects leak into the API view
