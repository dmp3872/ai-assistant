"""Bridge cut clips into the Studio content queue.

Clipping a long video should also stock your posting shelf: each clip becomes a
`video_clip` ContentPiece on a channel (YouTube/TikTok), carrying its auto-title, its
local file path, and its timecodes. From there it flows through the same queue → Studio →
Plan surfaces as any other piece, and fills that channel's daily quota.

Still read-only to the outside world: this only writes rows to our own SQLite. The clip
file already exists on disk; nothing is uploaded anywhere.
"""
from __future__ import annotations

from pathlib import Path

from app.content import queue
from app.video.segment import Clip, hms


def clip_to_piece(source: str, clip: Clip, channel: str,
                  file_path: str | None = None) -> dict:
    """Shape one Clip into an add_piece() payload."""
    src_name = Path(source).name
    caption = (clip.text or "").strip()[:600]
    time_range = f"{hms(clip.start)}→{hms(clip.end)}"
    resolved = None
    if file_path:
        try:
            resolved = str(Path(file_path).resolve())
        except OSError:
            resolved = file_path
    return {
        "channel": channel,
        "kind": "video_clip",
        "origin": "clip",
        "origin_ref": resolved or "",
        "title": clip.title or f"Clip {clip.index + 1}",
        # The transcript is the raw material for a caption/description — copy-editable.
        "body": caption,
        "tags": [src_name, time_range, f"{clip.duration/60:.1f}min"],
        "confidence": "medium",
        "review_reason": f"Auto-clip from {src_name} ({time_range}); cut on {clip.reason}.",
        "sources_used": [resolved] if resolved else [],
        "dedupe_key": f"clip:{src_name}:{clip.start:.1f}-{clip.end:.1f}",
    }


def queue_clips(source: str, clips: list[Clip], channel: str = "youtube",
                results: list[dict] | None = None) -> dict:
    """Add clips to the content queue. When `results` (from clip.cut_all) is given, only
    clips that were successfully written are queued, and each piece links to its file.
    Idempotent via dedupe_key — re-running the same clip job won't duplicate rows."""
    by_index = {r.get("index"): r for r in (results or [])}
    added, skipped, ids = 0, 0, []
    for c in clips:
        r = by_index.get(c.index)
        if results is not None and not (r and r.get("ok")):
            skipped += 1
            continue  # don't queue a piece pointing at a clip that failed to cut
        file_path = r.get("path") if r else None
        pid = queue.add_piece(clip_to_piece(source, c, channel, file_path))
        if pid:
            added += 1
            ids.append(pid)
        else:
            skipped += 1  # dedup hit — already on the shelf
    return {"added": added, "skipped": skipped, "piece_ids": ids, "channel": channel}
