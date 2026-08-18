"""Background clipper jobs for the dashboard's Clipper tab.

Runs the transcribe → find-cut-points → cut pipeline off the request thread so the browser
can drop a video, get a job id back immediately, and poll a live progress bar. Jobs are
kept in memory (the dashboard is a single-user localhost app) and their clip files land
under data/clips/<job_id>/ where the API serves them back for play/download.

Nothing here talks to the outside world — it reads the local video and writes local clip
files, exactly like the CLI.
"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from app.security import audit
from app.settings import get_settings
from app.video import clip as clipmod
from app.video import publish, transcribe
from app.video.segment import segment_transcript

_settings = get_settings()
CLIPS_DIR = _settings.data_dir / "clips"
UPLOADS_DIR = CLIPS_DIR / "_uploads"

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _set(job_id: str, **kw) -> None:
    with _lock:
        j = _jobs.get(job_id)
        if j:
            j.update(kw)


def _public(job: dict) -> dict:
    """Job view for the API — drops private (underscore) keys like raw Clip objects."""
    pub = {k: v for k, v in job.items() if not k.startswith("_")}
    return pub


def get_job(job_id: str) -> dict | None:
    with _lock:
        j = _jobs.get(job_id)
        return _public(dict(j)) if j else None


def list_jobs(limit: int = 20) -> list[dict]:
    with _lock:
        jobs = sorted(_jobs.values(), key=lambda j: j["created_at"], reverse=True)
        return [{"id": j["id"], "source_name": j["source_name"], "status": j["status"],
                 "progress": j["progress"], "clip_count": len(j.get("clips", [])),
                 "created_at": j["created_at"]} for j in jobs[:limit]]


def create_job(source: str, source_name: str, opts: dict,
               transcript: str | None = None) -> str:
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id, "status": "queued", "progress": 0.0, "stage": "Queued",
        "source": source, "source_name": source_name, "opts": opts,
        "transcript": transcript, "clips": [], "est_clips": None,
        "out_dir": str(CLIPS_DIR / job_id), "error": None, "queued": None,
        "created_at": time.time(),
        "_clips": None, "_results": None,
    }
    with _lock:
        _jobs[job_id] = job
    threading.Thread(target=_run, args=(job_id,), daemon=True).start()
    return job_id


def _clip_public(job_id: str, clip, result: dict | None) -> dict:
    d = clip.to_dict()
    d["ok"] = bool(result and result.get("ok"))
    if result and result.get("ok"):
        d["file_url"] = f"/api/clipper/file/{job_id}/{Path(result['path']).name}"
    if result and result.get("error"):
        d["error"] = result["error"]
    return d


def _run(job_id: str) -> None:
    with _lock:
        job = dict(_jobs[job_id])
    opts = job["opts"]
    source = job["source"]
    try:
        # 1) Transcript -----------------------------------------------------------
        _set(job_id, status="transcribing", stage="Transcribing audio…", progress=0.02)

        def _tprog(frac: float) -> None:
            _set(job_id, progress=round(0.03 + 0.62 * frac, 3))

        if job["transcript"]:
            segments = transcribe.load_transcript_file(job["transcript"])
        elif Path(source).suffix.lower() in transcribe.TRANSCRIPT_EXTS:
            segments = transcribe.load_transcript_file(source)
        else:
            segments = transcribe.transcribe_media(
                source, model_size=opts.get("model", "base"),
                language=opts.get("language"), progress=_tprog)
        if not segments:
            raise RuntimeError("Empty transcript — nothing to clip.")

        # 2) Find cut points ------------------------------------------------------
        _set(job_id, status="segmenting", stage="Finding natural cut points…",
             progress=0.68)
        clips = segment_transcript(
            segments, min_s=opts["min"] * 60, max_s=opts["max"] * 60,
            target_s=opts["target"] * 60)
        if not clips:
            raise RuntimeError("Could not form any clips from this transcript.")
        _set(job_id, est_clips=len(clips))

        # 3) Cut ------------------------------------------------------------------
        if not clipmod.has_ffmpeg():
            out_dir = Path(job["out_dir"])
            out_dir.mkdir(parents=True, exist_ok=True)
            clipmod.write_manifest(source, clips, out_dir)
            _set(job_id, status="plan_only", progress=1.0,
                 stage="Plan ready — install ffmpeg to cut the files",
                 clips=[_clip_public(job_id, c, None) for c in clips],
                 _clips=clips)
            return

        _set(job_id, status="cutting", stage=f"Cutting {len(clips)} clips…")

        def _cprog(done: int, total: int) -> None:
            _set(job_id, progress=round(0.7 + 0.28 * (done / total), 3),
                 stage=f"Cutting clip {done}/{total}…")

        results = clipmod.cut_all(source, clips, job["out_dir"],
                                  reencode=not opts.get("fast", False), progress=_cprog)
        clipmod.write_manifest(source, clips, job["out_dir"], results=results)

        # 4) Optional: stock the content queue ------------------------------------
        queued = None
        if opts.get("queue_channel"):
            queued = publish.queue_clips(source, clips, channel=opts["queue_channel"],
                                         results=results)

        clips_pub = [_clip_public(job_id, c, r) for c, r in zip(clips, results)]
        ok = sum(1 for r in results if r.get("ok"))
        _set(job_id, status="done", progress=1.0,
             stage=f"Done — {ok}/{len(results)} clips ready",
             clips=clips_pub, queued=queued, _clips=clips, _results=results)
        audit("draft", subtype="clipper_job", clips=ok, source=job["source_name"])
    except transcribe.TranscriptionUnavailable as exc:
        _set(job_id, status="error", stage="Whisper not installed", error=str(exc))
    except Exception as exc:  # a bad job must never take the server down
        _set(job_id, status="error", stage="Error", error=str(exc))
        audit("error", stage="clipper_job", error=str(exc))


def queue_job(job_id: str, channel: str) -> dict:
    """Push an already-finished job's clips into the content queue on `channel`."""
    with _lock:
        job = dict(_jobs.get(job_id) or {})
    clips = job.get("_clips")
    if not clips:
        return {"ok": False, "reason": "job not finished or has no clips"}
    q = publish.queue_clips(job["source"], clips, channel=channel,
                            results=job.get("_results"))
    _set(job_id, queued=q)
    return {"ok": True, **q}
