"""Background clip jobs for the standalone Video Clipper app.

Self-contained: it uses ONLY the clipping engine (segment / transcribe / clip). No
database, no content queue, no account — just transcribe → find natural cut points → cut
files. Jobs run on a worker thread so the browser can show a live progress bar, and clip
files land under an output folder the app serves back for play/download.

Nothing here talks to the outside world: it reads your local video and writes local clip
files. That's the whole footprint.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from pathlib import Path

from app.video import clip as clipmod
from app.video import transcribe
from app.video.moments import find_moments
from app.video.segment import segment_transcript

# Where clips are written. Override with CLIPPER_OUT; defaults to ./clipper_output.
OUT_DIR = Path(os.getenv("CLIPPER_OUT", "clipper_output")).expanduser().resolve()
UPLOADS_DIR = OUT_DIR / "_uploads"

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _set(job_id: str, **kw) -> None:
    with _lock:
        j = _jobs.get(job_id)
        if j:
            j.update(kw)


def get_job(job_id: str) -> dict | None:
    with _lock:
        j = _jobs.get(job_id)
        return dict(j) if j else None


def create_job(source: str, source_name: str, opts: dict,
               transcript: str | None = None) -> str:
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id, "status": "queued", "progress": 0.0, "stage": "Queued",
        "source": source, "source_name": source_name, "opts": opts,
        "transcript": transcript, "clips": [], "est_clips": None,
        "out_dir": str(OUT_DIR / job_id), "error": None, "created_at": time.time(),
    }
    with _lock:
        _jobs[job_id] = job
    threading.Thread(target=_run, args=(job_id,), daemon=True).start()
    return job_id


def _clip_public(job_id: str, clip, result: dict | None) -> dict:
    d = clip.to_dict()
    d["ok"] = bool(result and result.get("ok"))
    if result and result.get("ok"):
        d["file_url"] = f"/file/{job_id}/{Path(result['path']).name}"
    if result and result.get("error"):
        d["error"] = result["error"]
    return d


def _run(job_id: str) -> None:
    with _lock:
        job = dict(_jobs[job_id])
    opts = job["opts"]
    source = job["source"]
    try:
        # 1) Transcript ----------------------------------------------------------
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

        # 2) Find the clips -------------------------------------------------------
        if opts.get("mode", "highlights") == "even":
            _set(job_id, status="segmenting", stage="Cutting even chunks…", progress=0.68)
            clips = segment_transcript(
                segments, min_s=opts["min"] * 60, max_s=opts["max"] * 60,
                target_s=opts["target"] * 60)
        else:
            _set(job_id, status="segmenting",
                 stage="Scanning the transcript for engaging moments…", progress=0.68)
            clips = find_moments(
                segments, min_s=opts.get("min_moment_s", 45),
                max_s=opts["max"] * 60, target_s=opts["target"] * 60,
                max_moments=opts.get("max_moments"))
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
                 clips=[_clip_public(job_id, c, None) for c in clips])
            return

        _set(job_id, status="cutting", stage=f"Cutting {len(clips)} clips…")

        def _cprog(done: int, total: int) -> None:
            _set(job_id, progress=round(0.7 + 0.28 * (done / total), 3),
                 stage=f"Cutting clip {done}/{total}…")

        results = clipmod.cut_all(source, clips, job["out_dir"],
                                  reencode=not opts.get("fast", False), progress=_cprog)
        clipmod.write_manifest(source, clips, job["out_dir"], results=results)

        clips_pub = [_clip_public(job_id, c, r) for c, r in zip(clips, results)]
        ok = sum(1 for r in results if r.get("ok"))
        _set(job_id, status="done", progress=1.0,
             stage=f"Done — {ok}/{len(results)} clips ready",
             clips=clips_pub, out_dir=job["out_dir"])
    except transcribe.TranscriptionUnavailable as exc:
        _set(job_id, status="error", stage="Whisper not installed", error=str(exc))
    except Exception as exc:  # a bad job must never take the app down
        _set(job_id, status="error", stage="Error", error=str(exc))
