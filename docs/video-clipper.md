# Auto Video Clipper

Point it at a long video; get natural **5–7 minute clips** back. No timeline scrubbing, no
manual in/out points. It reads the transcript, finds good places to cut, and hands you
finished clip files plus a manifest.

```bash
python scripts/clip_video.py ~/Desktop/podcast.mp4
```

That's the whole workflow. Everything below is detail.

---

## What it does

```
video ──▶ transcript (Whisper, with timestamps)
            │
            ▼
      segment_transcript()  ── scan for natural cut points near the 6-min mark:
            │                    • end of a sentence (never cut mid-sentence)
            │                    • a pause in speech (silence gap)
            │                    • a topic shift ("so anyway…", "next up…")
            ▼
      clip plan (5–7 min each, snapped to clean word boundaries)
            │
            ▼
      ffmpeg ──▶ clip_01_*.mp4, clip_02_*.mp4, … + clips.json
```

The cut-point logic (`app/video/segment.py`) is pure Python and fully unit-tested — it
scores every candidate boundary in the 5–7 minute window and picks the most natural one,
falling back gracefully when the speech has no clean seam. Each clip records **why** it
was cut (e.g. `sentence end + 1.8s pause`) in the manifest.

## Usage

```bash
# simplest — transcribe + clip + auto-title
python scripts/clip_video.py talk.mp4

# already have a transcript? skip transcription entirely
python scripts/clip_video.py talk.mp4 --transcript talk.srt      # .srt/.vtt/.json
python scripts/clip_video.py talk.srt                            # a transcript IS a valid source

# see the plan first, cut nothing
python scripts/clip_video.py talk.mp4 --dry-run

# tuning
python scripts/clip_video.py talk.mp4 --min 4 --max 8 --target 6
python scripts/clip_video.py talk.mp4 --model small     # better transcription, slower
python scripts/clip_video.py talk.mp4 --fast            # stream-copy: near-instant, less precise
python scripts/clip_video.py talk.mp4 --outdir ~/clips --no-titles
```

Output: an `<video>_clips/` folder (or `--outdir`) with the clip files and `clips.json`
(start/end, duration, cut reason, title, and the transcript for each clip).

## Requirements (on the machine that runs it)

- **ffmpeg** — does the actual cutting: `brew install ffmpeg` (bundles `ffprobe`).
- **A Whisper backend** — only if you're transcribing (not needed with `--transcript`):
  - `pip install faster-whisper` — recommended (fast, CPU-friendly), **or**
  - `pip install openai-whisper`

The tool checks for these and prints the exact install command if one is missing, rather
than failing cryptically. With `--dry-run` or `--transcript`, no ffmpeg/Whisper is needed
to see the plan.

## Design notes

- **Non-destructive.** The source is only ever read; clips are written to a new folder.
- **Accurate by default.** Clips are re-encoded so they start exactly on the planned frame.
  `--fast` stream-copies instead (near-instant, but may start on the nearest keyframe).
- **Titling is best-effort.** With your Anthropic key set, one batched Claude call names
  each clip from its transcript (fenced as untrusted data). No key / no network → clips
  are still cut, just numbered.
- **Deterministic core.** Segmentation has no ML and no randomness, so the same transcript
  always yields the same clip plan — easy to trust and to test (`tests/test_video_segment.py`).

## Where it lives

| File | Role |
|------|------|
| `app/video/segment.py` | Find natural cut points (the brain; pure, tested) |
| `app/video/transcribe.py` | Whisper backends + SRT/VTT/JSON transcript parsing |
| `app/video/clip.py` | ffprobe duration, ffmpeg cutting, dry-run plan, manifest |
| `app/video/titles.py` | Optional Claude auto-titling (graceful) |
| `scripts/clip_video.py` | The one-command CLI |
| `tests/test_video_segment.py` | Cut-point + parser tests |
