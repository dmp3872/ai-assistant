"""Clip a long video into natural 5–7 minute segments — automatically.

Point it at a video and walk away:

    python scripts/clip_video.py ~/Desktop/podcast.mp4
    python scripts/clip_video.py lecture.mp4 --outdir ~/clips --fast
    python scripts/clip_video.py talk.mp4 --transcript talk.srt   # skip transcription
    python scripts/clip_video.py talk.mp4 --dry-run                # just show the plan

It transcribes the audio (Whisper), scans the transcript for natural break points near
the 6-minute mark (sentence ends, pauses, topic shifts), and cuts clips there with
ffmpeg. It never modifies the original. No AI writes hooks, titles, or captions — a clip
is just a naturally-cut segment (pass --titles if you ever want AI titles). Nothing is
posted anywhere — clips land in a folder for you.

Runtime needs (on your Mac): ffmpeg (`brew install ffmpeg`) and a Whisper backend
(`pip install faster-whisper`) — unless you pass a transcript with --transcript.
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import json
from pathlib import Path

from app.settings import get_settings
from app.video import clip as clipmod
from app.video import transcribe
from app.video.segment import segment_transcript


def _cfg() -> dict:
    return (get_settings().config.get("clips") or {})


def main() -> int:
    c = _cfg()
    ap = argparse.ArgumentParser(description="Auto-clip a long video into 5–7 min segments.")
    ap.add_argument("source", help="video/audio file, or a transcript (.srt/.vtt/.json)")
    ap.add_argument("--transcript", help="existing transcript file (skips transcription)")
    ap.add_argument("--outdir", help="output folder (default: <source>_clips)")
    ap.add_argument("--min", type=float, default=c.get("min_minutes", 5.0), help="min clip minutes")
    ap.add_argument("--max", type=float, default=c.get("max_minutes", 7.0), help="max clip minutes")
    ap.add_argument("--target", type=float, default=c.get("target_minutes", 6.0), help="ideal clip minutes")
    ap.add_argument("--model", default=c.get("whisper_model", "base"), help="Whisper model size")
    ap.add_argument("--language", default=c.get("language"), help="force transcription language")
    ap.add_argument("--fast", action="store_true", help="stream-copy (no re-encode); faster, less precise")
    ap.add_argument("--titles", action="store_true",
                    help="opt in to AI-generated clip titles (off by default; no AI otherwise)")
    ap.add_argument("--dry-run", action="store_true", help="print the clip plan; cut nothing")
    ap.add_argument("--json", action="store_true", help="emit the plan as JSON to stdout")
    ap.add_argument("--queue", nargs="?", const=c.get("queue_channel", "youtube"),
                    default=None, metavar="CHANNEL",
                    help="add each cut clip to the Studio content queue "
                         "(optional channel; default youtube, e.g. --queue tiktok)")
    args = ap.parse_args()

    src = Path(args.source)
    if not src.exists():
        print(f"✗ Not found: {src}")
        return 2

    # 1) Transcript ---------------------------------------------------------------
    try:
        print("• Getting transcript…")
        segments = transcribe.get_segments(src, transcript=args.transcript,
                                           model_size=args.model, language=args.language)
    except transcribe.TranscriptionUnavailable as exc:
        print(f"✗ {exc}")
        return 3
    if not segments:
        print("✗ Empty transcript — nothing to clip.")
        return 3
    print(f"  {len(segments)} transcript segments "
          f"({segments[-1]['end']/60:.1f} min of speech).")

    # 2) Find the clip points -----------------------------------------------------
    clips = segment_transcript(
        segments, min_s=args.min * 60, max_s=args.max * 60, target_s=args.target * 60)
    if not clips:
        print("✗ Could not form any clips.")
        return 3
    print(f"• Found {len(clips)} clip points.")

    # 3) Titles — OFF by default; AI only if you explicitly opt in with --titles -----
    if args.titles and not args.dry_run:
        print("• Titling clips with AI (--titles)…")
        from app.video.titles import suggest_titles
        suggest_titles(clips)

    for row in clipmod.plan_rows(clips):
        print(row)

    if args.json:
        print(json.dumps({"source": str(src),
                          "clips": [cl.to_dict() for cl in clips]}, indent=2))

    if args.dry_run:
        print("\n(dry run — no files written)")
        return 0

    # 4) Cut ----------------------------------------------------------------------
    out_dir = Path(args.outdir) if args.outdir else src.with_name(src.stem + "_clips")
    if not clipmod.has_ffmpeg():
        print("\n✗ ffmpeg/ffprobe not found — install ffmpeg to cut clips "
              "(`brew install ffmpeg`).\n  The clip plan above is saved; re-run once "
              "ffmpeg is installed.")
        clipmod.write_manifest(src, clips, out_dir)
        return 4

    print(f"• Cutting {len(clips)} clips into {out_dir} "
          f"({'copy' if args.fast else 're-encode'})…")
    results = clipmod.cut_all(src, clips, out_dir, reencode=not args.fast)
    manifest = clipmod.write_manifest(src, clips, out_dir, results=results)

    ok = sum(1 for r in results if r.get("ok"))
    failed = [r for r in results if not r.get("ok")]
    print(f"\n✓ {ok}/{len(results)} clips written to {out_dir}")
    print(f"  manifest: {manifest}")
    for r in failed:
        print(f"  ✗ clip #{r['index']+1}: {r.get('error','failed')[:160]}")

    # 5) Stock the Studio queue (optional) ----------------------------------------
    if args.queue:
        from app.video import publish
        q = publish.queue_clips(str(src), clips, channel=args.queue, results=results)
        print(f"• Queued {q['added']} clip(s) to Studio ({q['channel']})"
              + (f", {q['skipped']} skipped" if q["skipped"] else "")
              + ". They now fill that channel's daily quota on the Plan tab.")

    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
