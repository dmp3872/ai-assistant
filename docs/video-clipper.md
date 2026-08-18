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
python scripts/clip_video.py talk.mp4 --outdir ~/clips
python scripts/clip_video.py talk.mp4 --titles          # opt in to AI titles (off by default)

# stock the Studio queue while you clip
python scripts/clip_video.py talk.mp4 --queue           # each clip -> a YouTube piece
python scripts/clip_video.py talk.mp4 --queue tiktok    # ...or TikTok
```

## Feeding the content queue (`--queue`)

Pass `--queue` and every clip that gets cut is also added to the **Studio** content queue
as a `video_clip` piece on a channel (default `youtube`, or `--queue tiktok`). Each piece
carries the clip's auto-title, its transcript (as a caption/description to edit), its
timecodes, and the local file path. They show up in Studio under **🎬 Video clips** and
fill that channel's daily quota on the **Plan** tab — so clipping a video also stocks your
posting shelf. It's idempotent (dedup keyed on source + timecodes), and only clips that
were actually written get queued. Nothing is uploaded; you still post the files yourself.

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
- **No AI by default.** Nothing writes hooks, titles, or captions — a clip is just a
  naturally-cut segment. Clips are numbered (`clip_01`, `clip_02`, …) and the transcript
  travels with each clip in the manifest. AI titling is strictly opt-in via `--titles`
  (a batched Claude call over each clip's transcript). Transcription itself uses Whisper
  (speech-to-text), which runs regardless.
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
