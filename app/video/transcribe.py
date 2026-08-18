"""Get a timestamped transcript for a video — the input the clipper's brain needs.

Three paths, tried in order of least work:
  1. You already have a transcript file (.srt / .vtt / .json / whisper json) → just parse it.
  2. A local media file → transcribe with Whisper (faster-whisper preferred, then
     openai-whisper). Both are optional deps; we raise a clear "pip install" message if
     neither is present rather than failing cryptically.

Parsers are pure-Python and unit-tested; transcription shells out to the ML backend.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

TRANSCRIPT_EXTS = {".srt", ".vtt", ".json"}
MEDIA_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mp3", ".wav",
              ".m4a", ".aac", ".flac", ".ogg"}


# --- timestamp parsing ------------------------------------------------------------

def parse_timestamp(ts: str) -> float:
    """'HH:MM:SS,mmm' or 'HH:MM:SS.mmm' or 'MM:SS.mmm' -> seconds."""
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    parts = [float(p) for p in parts]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, m, s = parts[-3], parts[-2], parts[-1]
    return h * 3600 + m * 60 + s


def parse_srt(text: str) -> list[dict]:
    """Parse SubRip (.srt) into [{start,end,text}]."""
    segments: list[dict] = []
    blocks = re.split(r"\n\s*\n", text.strip())
    time_re = re.compile(r"(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})")
    for block in blocks:
        m = time_re.search(block)
        if not m:
            continue
        lines = block.splitlines()
        # transcript text = everything after the timestamp line
        text_lines = []
        seen_time = False
        for ln in lines:
            if time_re.search(ln):
                seen_time = True
                continue
            if seen_time:
                text_lines.append(ln)
        body = " ".join(text_lines).strip()
        if body:
            segments.append({"start": parse_timestamp(m.group(1)),
                             "end": parse_timestamp(m.group(2)), "text": body})
    return segments


def parse_vtt(text: str) -> list[dict]:
    """Parse WebVTT (.vtt) into [{start,end,text}]. Ignores NOTE/STYLE and cue tags."""
    segments: list[dict] = []
    time_re = re.compile(r"(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*"
                         r"(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})")
    blocks = re.split(r"\n\s*\n", text.strip())
    for block in blocks:
        if block.strip().startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        m = time_re.search(block)
        if not m:
            continue
        lines = block.splitlines()
        text_lines = [ln for ln in lines if not time_re.search(ln)]
        body = re.sub(r"<[^>]+>", "", " ".join(text_lines)).strip()  # strip cue tags
        if body:
            segments.append({"start": parse_timestamp(m.group(1)),
                             "end": parse_timestamp(m.group(2)), "text": body})
    return segments


def parse_whisper_json(data) -> list[dict]:
    """Accept Whisper's JSON ({'segments':[{start,end,text}]}) or a bare list."""
    if isinstance(data, dict):
        data = data.get("segments", [])
    out = []
    for s in data:
        if "start" in s and "end" in s:
            out.append({"start": float(s["start"]), "end": float(s["end"]),
                        "text": str(s.get("text", "")).strip()})
    return out


def load_transcript_file(path: str | Path) -> list[dict]:
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    ext = p.suffix.lower()
    if ext == ".srt":
        return parse_srt(text)
    if ext == ".vtt":
        return parse_vtt(text)
    if ext == ".json":
        return parse_whisper_json(json.loads(text))
    # last resort: try VTT then SRT shapes
    return parse_vtt(text) or parse_srt(text)


# --- transcription ----------------------------------------------------------------

class TranscriptionUnavailable(RuntimeError):
    """Neither Whisper backend is installed."""


def transcribe_media(path: str | Path, *, model_size: str = "base",
                     language: str | None = None, progress=None) -> list[dict]:
    """Transcribe a local media file to [{start,end,text}] using whatever Whisper backend
    is installed. Prefers faster-whisper (much faster, CPU-friendly).

    `progress`, if given, is called with a 0.0–1.0 fraction as transcription advances so a
    UI can show a live bar (faster-whisper streams segments; we track them against the
    media duration)."""
    path = str(path)
    try:
        from faster_whisper import WhisperModel  # type: ignore

        model = WhisperModel(model_size, device="auto", compute_type="auto")
        segments, info = model.transcribe(path, language=language, vad_filter=True)
        duration = float(getattr(info, "duration", 0) or 0)
        out = []
        for s in segments:
            out.append({"start": float(s.start), "end": float(s.end),
                        "text": s.text.strip()})
            if progress and duration:
                progress(min(s.end / duration, 0.99))
        if progress:
            progress(1.0)
        return out
    except ImportError:
        pass

    try:
        import whisper  # type: ignore

        if progress:
            progress(0.05)  # openai-whisper doesn't stream; can't show fine-grained %
        model = whisper.load_model(model_size)
        result = model.transcribe(path, language=language)
        if progress:
            progress(1.0)
        return [{"start": float(s["start"]), "end": float(s["end"]),
                 "text": str(s["text"]).strip()} for s in result.get("segments", [])]
    except ImportError:
        raise TranscriptionUnavailable(
            "No Whisper backend found. Install one:\n"
            "  pip install faster-whisper        # recommended (fast, CPU-friendly)\n"
            "  # or\n"
            "  pip install openai-whisper\n"
            "…or pass an existing transcript with --transcript file.srt/.vtt/.json")


def get_segments(source: str | Path, *, transcript: str | Path | None = None,
                 model_size: str = "base", language: str | None = None) -> list[dict]:
    """Top-level: return timestamped segments for `source`.

    If `transcript` is given, parse it. Else if `source` is itself a transcript file,
    parse it. Else transcribe the media. This is what makes the CLI 'just point at it'."""
    if transcript:
        return load_transcript_file(transcript)
    p = Path(source)
    if p.suffix.lower() in TRANSCRIPT_EXTS:
        return load_transcript_file(p)
    return transcribe_media(p, model_size=model_size, language=language)
