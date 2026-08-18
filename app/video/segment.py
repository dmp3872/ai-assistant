"""Find good places to clip a long video — purely from its transcript.

This is the brain of the clipper. Given timestamped transcript segments, it walks the
timeline and cuts 5–7 minute clips at *natural* boundaries: the end of a sentence, a
pause in speech, or a topic shift ("so anyway…", "next up…"). It never cuts mid-sentence
when it can help it, and it snaps every cut to a real segment boundary so clips start and
end on clean words.

Deliberately dependency-free (no ffmpeg, no ML) so it's deterministic and unit-testable.
Feed it Whisper/SRT/VTT segments; get back a clip plan you can hand to ffmpeg.
"""
from __future__ import annotations

from dataclasses import dataclass

# A clip is "good" anywhere in [MIN, MAX]; we aim for TARGET and score candidates by how
# natural the boundary is, not just how close to target.
DEFAULT_MIN_S = 300.0    # 5:00
DEFAULT_MAX_S = 420.0    # 7:00
DEFAULT_TARGET_S = 360.0  # 6:00
# A trailing remnant shorter than this gets merged back into the previous clip instead of
# shipping a 20-second orphan.
DEFAULT_MIN_TAIL_S = 90.0

SENTENCE_ENDINGS = (".", "?", "!", "…", '."', '?"', '!"', ".'", "?'", "!'")

# Openers that usually mark a fresh thought — a natural place for the *next* clip to begin.
TOPIC_MARKERS = (
    "so ", "so,", "now ", "now,", "okay", "ok ", "ok,", "alright", "all right",
    "anyway", "anyways", "next", "moving on", "another thing", "another", "let's",
    "lets ", "first", "second", "third", "finally", "lastly", "the next", "one more",
    "here's the thing", "which brings", "on top of that", "and then", "but here",
    "the point is", "bottom line", "to be clear", "quick", "real quick",
)


@dataclass
class Segment:
    """One timestamped transcript line."""
    start: float
    end: float
    text: str

    @property
    def dur(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class Clip:
    index: int
    start: float
    end: float
    reason: str          # why we cut here (for the manifest / transparency)
    text: str            # the transcript spanning this clip
    title: str | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "duration": round(self.duration, 3),
            "start_hms": hms(self.start),
            "end_hms": hms(self.end),
            "reason": self.reason,
            "title": self.title,
            "text": self.text,
        }


def hms(seconds: float) -> str:
    """Seconds -> HH:MM:SS.mmm (ffmpeg-friendly, and readable in a manifest)."""
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _coerce(segments) -> list[Segment]:
    out: list[Segment] = []
    for s in segments:
        if isinstance(s, Segment):
            seg = s
        else:  # dict-like from Whisper / SRT / VTT
            seg = Segment(float(s["start"]), float(s["end"]), str(s.get("text", "")))
        if seg.end > seg.start and seg.text.strip():
            out.append(seg)
    out.sort(key=lambda x: x.start)
    return out


def _is_sentence_end(text: str) -> bool:
    t = text.strip()
    return bool(t) and t.endswith(SENTENCE_ENDINGS)


def _starts_topic(text: str) -> bool:
    t = text.strip().lower()
    return any(t.startswith(m) for m in TOPIC_MARKERS)


def _boundary_score(segs: list[Segment], k: int, clip_start: float,
                    target_s: float) -> tuple[float, str]:
    """Score cutting *after* segment k (i.e. between segs[k] and segs[k+1]).

    Higher is better. The dominant reason is returned for the manifest so the cut is
    explainable ("sentence end + 1.8s pause")."""
    n = len(segs)
    score = 0.0
    reasons: list[str] = []

    if _is_sentence_end(segs[k].text):
        score += 3.0
        reasons.append("sentence end")
    else:
        score -= 4.0  # cutting mid-sentence is bad; only accepted if nothing else exists

    # A pause between this segment and the next is a natural seam. Cap the reward at 2s.
    if k + 1 < n:
        gap = max(0.0, segs[k + 1].start - segs[k].end)
        if gap > 0.35:
            score += min(gap, 2.0)
            if gap >= 0.8:
                reasons.append(f"{gap:.1f}s pause")
        if _starts_topic(segs[k + 1].text):
            score += 1.5
            reasons.append("topic shift")

    # Mild pull toward the target length — the whole window is fine, target is just nicer.
    length = segs[k].end - clip_start
    score += 1.0 - min(abs(length - target_s) / max(target_s, 1.0), 1.0)

    return score, (" + ".join(reasons) if reasons else "best available boundary")


def segment_transcript(segments, *, min_s: float = DEFAULT_MIN_S,
                       max_s: float = DEFAULT_MAX_S, target_s: float = DEFAULT_TARGET_S,
                       min_tail_s: float = DEFAULT_MIN_TAIL_S) -> list[Clip]:
    """Turn timestamped transcript segments into a clip plan of 5–7 minute clips cut at
    natural boundaries. Accepts Segment objects or {'start','end','text'} dicts."""
    segs = _coerce(segments)
    if not segs:
        return []

    total = segs[-1].end - segs[0].start
    if total <= max_s:  # whole thing is already clip-sized
        return _merge_tail(
            [_make_clip(0, segs, 0, len(segs) - 1, "whole video")], min_tail_s)

    clips: list[Clip] = []
    i = 0
    n = len(segs)
    while i < n:
        clip_start = segs[i].start
        # Candidate cut points: every segment boundary from i onward, with its length.
        cands: list[tuple[int, float]] = []
        for k in range(i, n):
            length = segs[k].end - clip_start
            cands.append((k, length))
            if length >= max_s:
                break

        in_window = [(k, ln) for k, ln in cands if min_s <= ln <= max_s]
        if in_window:
            best_k = max(in_window,
                         key=lambda c: _boundary_score(segs, c[0], clip_start, target_s)[0])[0]
            _, reason = _boundary_score(segs, best_k, clip_start, target_s)
        elif cands and cands[-1][1] < min_s:
            # Everything left is shorter than one clip — take it all as the final clip.
            best_k, reason = n - 1, "end of video"
        else:
            # Segments too coarse to land inside the window (e.g. one long monologue
            # segment). Take the boundary closest to target without a clean seam.
            best_k = min(cands, key=lambda c: abs(c[1] - target_s))[0]
            reason = "coarse boundary (no clean seam in window)"

        clips.append(_make_clip(len(clips), segs, i, best_k, reason))
        i = best_k + 1

    return _merge_tail(clips, min_tail_s)


def _make_clip(index: int, segs: list[Segment], i: int, k: int, reason: str) -> Clip:
    text = " ".join(s.text.strip() for s in segs[i:k + 1]).strip()
    return Clip(index=index, start=segs[i].start, end=segs[k].end, reason=reason, text=text)


def _merge_tail(clips: list[Clip], min_tail_s: float) -> list[Clip]:
    """Fold a too-short final clip back into its predecessor and renumber."""
    if len(clips) >= 2 and clips[-1].duration < min_tail_s:
        tail = clips.pop()
        prev = clips[-1]
        clips[-1] = Clip(index=prev.index, start=prev.start, end=tail.end,
                         reason=prev.reason + " + merged short tail",
                         text=(prev.text + " " + tail.text).strip())
    for n, c in enumerate(clips):
        c.index = n
    return clips
