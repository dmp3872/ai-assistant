"""Standalone Video Clipper web app — a single page, nothing else attached.

Run it with `python scripts/clipper.py` (opens your browser), or directly:
    uvicorn app.video.webapp:app --port 4318

It serves one page (drop a video → get clips) and the few endpoints that page needs.
No database, no accounts, no other features. Everything runs locally on your machine;
the uploaded video only ever goes to this local server.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from app.video import jobs

app = FastAPI(title="Video Clipper", docs_url=None, redoc_url=None)
_PAGE = (Path(__file__).resolve().parent / "static" / "index.html").read_text()


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return _PAGE


def _opts(min_: float, max_: float, target: float, model: str, fast: bool) -> dict:
    return {"min": float(min_), "max": float(max_), "target": float(target),
            "model": model or "base", "fast": bool(fast)}


@app.post("/upload")
async def upload(
    file: UploadFile = File(...),
    min: float = Form(5.0), max: float = Form(7.0), target: float = Form(6.0),
    model: str = Form("base"), fast: bool = Form(False),
):
    """Drag-drop entry: stream the video to a temp file on THIS machine, start a job."""
    jobs.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    safe = Path(file.filename or "video.mp4").name
    dest = jobs.UPLOADS_DIR / f"{uuid.uuid4().hex[:8]}_{safe}"
    with dest.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            out.write(chunk)
    return {"job_id": jobs.create_job(str(dest), safe, _opts(min, max, target, model, fast))}


@app.post("/jobs")
def start(payload: dict = Body(...)):
    """Path entry (best for very large files — no upload copy): read straight from disk."""
    raw = (payload.get("path") or "").strip().strip('"').strip("'")
    p = Path(raw).expanduser() if raw else None
    if not p or not p.exists():
        return {"error": f"File not found: {raw or '(empty)'}"}
    opts = _opts(payload.get("min", 5.0), payload.get("max", 7.0),
                 payload.get("target", 6.0), payload.get("model", "base"),
                 payload.get("fast", False))
    return {"job_id": jobs.create_job(str(p), p.name, opts,
                                      transcript=payload.get("transcript"))}


@app.get("/jobs/{job_id}")
def job(job_id: str):
    return jobs.get_job(job_id) or {"error": "job not found"}


@app.get("/file/{job_id}/{name}")
def clip_file(job_id: str, name: str):
    """Serve a cut clip for play/download. Path-jailed to the job's own folder."""
    base = (jobs.OUT_DIR / job_id).resolve()
    target = (base / name).resolve()
    if base not in target.parents or not target.exists():
        return {"error": "not found"}
    return FileResponse(str(target), filename=name)
