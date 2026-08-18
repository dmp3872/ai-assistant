"""Cut the planned clips out of the source video with ffmpeg — and nothing destructive.

We only ever READ the source and WRITE new clip files into an output folder; the original
is never touched. Two modes:
  - accurate (default): re-encode so every clip starts exactly on the planned frame.
  - fast (--fast): stream-copy (no re-encode) — near-instant, but may start on the nearest
    keyframe, so the first fraction of a second can be off. Fine for rough cuts.

If ffmpeg isn't installed we say so plainly (with the install line) instead of throwing a
raw FileNotFoundError.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from app.video.segment import Clip, hms


class FFmpegMissing(RuntimeError):
    pass


def _require(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        raise FFmpegMissing(
            f"'{tool}' not found on PATH. Install ffmpeg (bundles ffprobe):\n"
            "  macOS:  brew install ffmpeg\n"
            "  Debian: sudo apt-get install ffmpeg")
    return path


def has_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def probe_duration(path: str | Path) -> float | None:
    """Total media duration in seconds via ffprobe, or None if it can't be read."""
    try:
        ffprobe = _require("ffprobe")
    except FFmpegMissing:
        return None
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=60)
        return float(out.stdout.strip())
    except (ValueError, subprocess.SubprocessError):
        return None


def build_ffmpeg_cmd(src: str | Path, start: float, end: float, out: str | Path,
                     *, reencode: bool = True) -> list[str]:
    """The exact ffmpeg argument vector for one clip. Kept pure so it's inspectable and
    testable (the CLI's --dry-run prints these without running anything)."""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    duration = max(0.0, end - start)
    if reencode:
        # Accurate: input-seek near the cut, then precise trim; re-encode audio+video.
        return [
            ffmpeg, "-y", "-ss", f"{start:.3f}", "-i", str(src),
            "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out),
        ]
    # Fast: no re-encode. Seek before input for speed; copy streams.
    return [
        ffmpeg, "-y", "-ss", f"{start:.3f}", "-i", str(src),
        "-t", f"{duration:.3f}", "-c", "copy", "-movflags", "+faststart", str(out),
    ]


def _safe_name(index: int, clip: Clip, ext: str) -> str:
    base = f"clip_{index + 1:02d}"
    if clip.title:
        slug = "".join(c if c.isalnum() or c in " -_" else "" for c in clip.title)
        slug = "-".join(slug.split())[:50].strip("-").lower()
        if slug:
            base = f"{base}_{slug}"
    return f"{base}{ext}"


def cut_clip(src: str | Path, clip: Clip, out_path: str | Path,
             *, reencode: bool = True, timeout: int = 3600) -> dict:
    """Cut a single clip. Returns {ok, path, error?}. Never raises on ffmpeg failure —
    one bad clip shouldn't abort the batch."""
    _require("ffmpeg")
    cmd = build_ffmpeg_cmd(src, clip.start, clip.end, out_path, reencode=reencode)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            return {"ok": False, "path": str(out_path),
                    "error": (proc.stderr or "").strip()[-500:]}
        return {"ok": True, "path": str(out_path)}
    except subprocess.SubprocessError as exc:
        return {"ok": False, "path": str(out_path), "error": str(exc)}


def cut_all(src: str | Path, clips: list[Clip], out_dir: str | Path,
            *, reencode: bool = True, ext: str = ".mp4", progress=None) -> list[dict]:
    """Cut every clip into out_dir. Returns per-clip results (ok/path/error).
    `progress`, if given, is called (done_count, total) after each clip for a UI bar."""
    _require("ffmpeg")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    total = len(clips)
    for i, clip in enumerate(clips):
        out_path = out_dir / _safe_name(i, clip, ext)
        res = cut_clip(src, clip, out_path, reencode=reencode)
        res["index"] = i
        res["title"] = clip.title
        results.append(res)
        if progress:
            progress(i + 1, total)
    return results


def plan_rows(clips: list[Clip]) -> list[str]:
    """Human-readable one-line-per-clip plan for --dry-run / summaries."""
    rows = []
    for c in clips:
        title = f"  “{c.title}”" if c.title else ""
        rows.append(f"#{c.index + 1:02d}  {hms(c.start)} → {hms(c.end)}  "
                    f"({c.duration/60:.1f} min)  [{c.reason}]{title}")
    return rows


def write_manifest(src: str | Path, clips: list[Clip], out_dir: str | Path,
                   *, results: list[dict] | None = None) -> str:
    """Write clips.json — the record of what was cut, why, and each clip's transcript."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "source": str(src),
        "clip_count": len(clips),
        "clips": [c.to_dict() for c in clips],
    }
    if results:
        by_index = {r.get("index"): r for r in results}
        for c in manifest["clips"]:
            r = by_index.get(c["index"])
            if r:
                c["file"] = r.get("path")
                c["ok"] = r.get("ok")
                if r.get("error"):
                    c["error"] = r["error"]
    path = out_dir / "clips.json"
    path.write_text(json.dumps(manifest, indent=2))
    return str(path)
