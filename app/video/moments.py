"""Find the *clippable moments* in a transcript — not every-5-minutes slices.

The difference from segment.py: that walks the whole timeline and cuts uniform chunks,
covering everything. This one hunts for the engaging bits and leaves the boring stretches
on the floor:

  1. TOPIC BOUNDARIES — detect where the subject changes, from lexical cohesion (adjacent
     windows that stop sharing vocabulary), discourse openers ("so anyway…", "here's the
     thing…"), and pauses. That carves the transcript into topic segments of natural,
     varying length.
  2. ENGAGEMENT SCORE — rate each topic segment on how clip-worthy it is: a strong hook
     opener, questions, stories, vivid/intense language, concrete specifics, and a good
     length. Filler and monotone stretches score low.
  3. SELECT — return the best moments ranked by score, dropping the weak ones. A boring
     hour yields a few clips, not twelve.

Deterministic and dependency-free (Counter + math), so it's testable and needs no AI/API.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from app.video.segment import Clip, Segment, _coerce, _is_sentence_end

_TOKEN_RE = re.compile(r"[a-z0-9']+")
_NUM_RE = re.compile(r"\b\d[\d,.]*\b|\$\d|\d+\s?%|\bpercent\b")

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "is", "are", "was", "were", "be",
    "been", "being", "to", "of", "in", "on", "for", "with", "at", "by", "from", "as", "up",
    "about", "into", "over", "it", "its", "this", "that", "these", "those", "i", "you",
    "he", "she", "we", "they", "me", "him", "her", "us", "them", "my", "your", "our",
    "their", "so", "just", "like", "yeah", "okay", "ok", "um", "uh", "gonna", "kind",
    "sort", "really", "very", "actually", "basically", "right", "know", "think", "mean",
    "thing", "things", "get", "got", "going", "go", "one", "would", "could", "should",
    "do", "does", "did", "have", "has", "had", "can", "will", "not", "no", "yes", "well",
    "there", "here", "what", "when", "where", "who", "how", "why", "because", "them",
}

# --- engagement lexicons ----------------------------------------------------------
# Openers that promise a payoff — great first lines for a clip.
_HOOK_OPENERS = (
    "the biggest", "the worst", "the best", "the craziest", "the number one", "the truth",
    "most people", "nobody", "here's the thing", "here's why", "here's what", "the secret",
    "the problem with", "the reason", "let me tell you", "i'll tell you", "the mistake",
    "what most", "if you", "listen", "look", "the thing is", "the key", "the crazy thing",
    "you need to", "you have to", "never", "always", "stop", "the fact is", "the wild",
    "one of the", "this is the", "the hardest", "the funny thing",
)
# Strong, content-bearing intensity words — NOT filler like "honestly/actually/literally"
# (those pepper boring speech and would flag everything).
_INTENSIFIERS = {
    "crazy", "insane", "wild", "huge", "massive", "incredible", "amazing", "unbelievable",
    "shocking", "terrifying", "scary", "obsessed", "brutal", "ridiculous", "mind-blowing",
    "game-changer", "life-changing", "dangerous", "powerful", "secret", "hack", "mistake",
    "disaster", "nightmare", "worst", "biggest", "surprising", "shocked", "hilarious",
}
_STORY_MARKERS = (
    "when i", "i was", "i remember", "one time", "the first time", "back when", "years ago",
    "so i", "we were", "i had", "i used to", "there was", "the other day", "last year",
    "my first", "i started", "i ended up",
)
_CURIOSITY = (
    "why", "how", "what if", "the reason", "turns out", "it turns out", "the truth about",
    "nobody talks about", "what nobody", "what they don't", "here's why", "the secret",
)
# Openers that signal the *next* topic is starting — good boundary cues.
_TOPIC_MARKERS = (
    "so anyway", "anyway", "moving on", "next", "the next", "another thing", "another",
    "let's talk", "let's get", "which brings", "on top of that", "and then", "but here",
    "the other thing", "so the", "alright so", "okay so", "now,", "now ", "so let's",
    "one more", "speaking of", "that reminds", "the second", "the third", "finally",
)


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall((text or "").lower())
            if t not in _STOPWORDS and len(t) > 2]


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[t] * b[t] for t in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _starts_topic(text: str) -> bool:
    t = (text or "").strip().lower()
    return any(t.startswith(m) for m in _TOPIC_MARKERS)


def _topic_boundaries(segs: list[Segment], window: int = 6) -> list[int]:
    """Segment-indices where a new topic block begins (always includes 0).

    Cohesion gap = 1 - cosine(vocab of the `window` segments before, `window` after). A
    boundary is a gap that stands out (local peak above a depth threshold), or a clear
    discourse opener / long pause. TextTiling in spirit, kept simple."""
    n = len(segs)
    if n <= 2:
        return [0]
    gaps = [0.0] * n
    for b in range(1, n):
        before = Counter()
        for s in segs[max(0, b - window):b]:
            before.update(_tokens(s.text))
        after = Counter()
        for s in segs[b:b + window]:
            after.update(_tokens(s.text))
        gaps[b] = 1.0 - _cosine(before, after)

    vals = [g for g in gaps[1:] if g > 0]
    if vals:
        mean = sum(vals) / len(vals)
        var = sum((g - mean) ** 2 for g in vals) / len(vals)
        std = math.sqrt(var)
    else:
        mean = std = 0.0
    depth_threshold = mean + 0.5 * std   # "notably higher than usual dissimilarity"

    boundaries = [0]
    for b in range(1, n):
        pause = segs[b].start - segs[b - 1].end
        is_peak = gaps[b] >= gaps[b - 1] and (b + 1 >= n or gaps[b] >= gaps[b + 1])
        cohesion_break = is_peak and gaps[b] >= depth_threshold and gaps[b] > 0.55
        # A discourse opener ("so anyway…") only counts as a boundary if the vocabulary is
        # ALSO shifting — otherwise filler that merely starts with "anyway/so" would split
        # a monotone stretch into dozens of fake clips.
        marker = _starts_topic(segs[b].text) and gaps[b] >= mean
        if (cohesion_break or marker or pause >= 1.4) and b - boundaries[-1] >= 3:
            boundaries.append(b)
    return boundaries


def _build_blocks(segs: list[Segment], boundaries: list[int],
                  min_s: float, max_s: float) -> list[tuple[int, int]]:
    """Turn boundary indices into (start_idx, end_idx) blocks, honoring min/max length.
    Blocks shorter than min_s merge forward; blocks longer than max_s split at the best
    internal sentence-ending boundary."""
    n = len(segs)
    spans = []
    for bi, start in enumerate(boundaries):
        end = (boundaries[bi + 1] - 1) if bi + 1 < len(boundaries) else n - 1
        spans.append((start, end))

    # merge too-short blocks forward
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged:
            ps, pe = merged[-1]
            if segs[pe].end - segs[ps].start < min_s:
                merged[-1] = (ps, end)
                continue
        merged.append((start, end))

    # split too-long blocks at internal sentence ends nearest the midpoint
    out: list[tuple[int, int]] = []
    for start, end in merged:
        while segs[end].end - segs[start].start > max_s:
            target_t = segs[start].start + max_s
            cut = None
            for k in range(start + 1, end):
                if segs[k].end - segs[start].start > max_s:
                    break
                if _is_sentence_end(segs[k].text):
                    cut = k
            if cut is None:  # no sentence seam; hard cut at last in-window segment
                cut = start
                for k in range(start + 1, end):
                    if segs[k].end - segs[start].start <= max_s:
                        cut = k
                    else:
                        break
            out.append((start, cut))
            start = cut + 1
        out.append((start, end))
    return out


def _score_moment(segs: list[Segment], i: int, k: int,
                  target_s: float) -> tuple[float, float, list[str]]:
    """Rate a candidate moment. Returns (total, engagement, reasons).

    `engagement` counts only real hooks/questions/stories/intensity/specifics — it's what
    a moment must EARN to be worth clipping (boring stretches score ~0). `total` adds
    length/shape on top and is only used to rank the moments that already qualify."""
    text = " ".join(s.text.strip() for s in segs[i:k + 1]).strip()
    low = text.lower()
    dur = segs[k].end - segs[i].start
    words = low.split()
    wc = max(len(words), 1)
    engagement = 0.0
    reasons: list[str] = []

    opener = " ".join(words[:12])
    if any((" " + h) in (" " + opener) for h in _HOOK_OPENERS):
        engagement += 2.2
        reasons.append("strong hook")

    q = text.count("?")
    if q:
        engagement += min(q, 3) * 0.7
        reasons.append("raises a question" if q == 1 else f"{q} questions")

    if any(m in low for m in _STORY_MARKERS):
        engagement += 1.4
        reasons.append("personal story")

    intens = sum(low.count(w) for w in _INTENSIFIERS)
    if intens:
        dens = intens / (wc / 100.0)  # per-100-words
        engagement += min(0.6 + dens * 0.4, 2.0)
        reasons.append("vivid/high-energy")

    nums = len(_NUM_RE.findall(text))
    if nums:
        engagement += min(nums * 0.3, 1.2)
        reasons.append("concrete specifics")

    if any(c in low for c in _CURIOSITY):
        engagement += 0.7
        reasons.append("curiosity gap")

    # --- shaping (ranking only, does NOT qualify a boring moment) ---
    shape = 0.0
    if _is_sentence_end(segs[k].text):
        shape += 0.4
    if dur < 40:
        shape -= 1.5
    elif dur < 75:
        shape -= 0.4
    else:
        shape += 0.8 - min(abs(dur - target_s) / max(target_s, 1.0), 1.0) * 0.8

    return round(engagement + shape, 3), round(engagement, 3), reasons


def _seg_has_signal(text: str) -> bool:
    """Does this single transcript line carry an engagement cue? Used to trim filler off
    the edges of a moment so it starts/ends on the good part, not a boring lead-in."""
    low = text.lower()
    if "?" in text or _NUM_RE.search(text):
        return True
    opener = " " + " ".join(low.split()[:12])
    if any((" " + h) in opener for h in _HOOK_OPENERS):
        return True
    toks = set(low.split())
    if toks & _INTENSIFIERS:
        return True
    if any(m in low for m in _STORY_MARKERS) or any(c in low for c in _CURIOSITY):
        return True
    return False


def _tighten(segs: list[Segment], i: int, k: int, min_s: float) -> tuple[int, int]:
    """Pull the moment's edges in past leading/trailing filler, keeping >= min_s and a
    clean sentence ending. Fixes clips that would otherwise open in a boring stretch."""
    a, b = i, k
    while a < b and not _seg_has_signal(segs[a].text) and segs[b].end - segs[a + 1].start >= min_s:
        a += 1
    while b > a and not _seg_has_signal(segs[b].text) and segs[b - 1].end - segs[a].start >= min_s:
        b -= 1
    # make sure we end on a sentence boundary if trimming left us mid-thought
    while b < k and not _is_sentence_end(segs[b].text):
        b += 1
    return a, b


def _title_from(text: str) -> str:
    """A deterministic, non-AI label: the first sentence (trimmed). No hooks written."""
    first = re.split(r"(?<=[.?!])\s+", text.strip())[0] if text.strip() else ""
    first = first.strip().rstrip(".")
    return (first[:70] + "…") if len(first) > 72 else (first or "Moment")


def find_moments(segments, *, min_s: float = 45.0, max_s: float = 480.0,
                 target_s: float = 180.0, max_moments: int | None = 12,
                 min_engagement: float = 1.5, window: int = 6) -> list[Clip]:
    """Return the most engaging moments as clips, ranked then ordered by time.

    Boring stretches are dropped: a moment must EARN `min_engagement` from real signals
    (hook / question / story / intensity / specifics) to qualify — length alone never
    qualifies one. Qualifying moments are ranked by total score, capped at `max_moments`,
    with a small floor so a genuinely engaging short video still yields a clip or two."""
    segs = _coerce(segments)
    if not segs:
        return []

    boundaries = _topic_boundaries(segs, window)
    blocks = _build_blocks(segs, boundaries, min_s, max_s)

    scored = []
    for (i, k) in blocks:
        total, engagement, reasons = _score_moment(segs, i, k, target_s)
        scored.append((total, engagement, i, k, reasons))

    qualifying = [s for s in scored if s[1] >= min_engagement]
    qualifying.sort(key=lambda x: x[0], reverse=True)
    if not qualifying:  # nothing cleared the bar — hand back the single best, if any signal
        best = max(scored, key=lambda x: x[0]) if scored else None
        qualifying = [best] if best and best[1] > 0 else []
    if max_moments:
        qualifying = qualifying[:max_moments]

    qualifying.sort(key=lambda x: x[2])  # chronological for output
    clips = []
    for n, (total, engagement, i, k, reasons) in enumerate(qualifying):
        i, k = _tighten(segs, i, k, min_s)   # trim filler off the edges
        text = " ".join(s.text.strip() for s in segs[i:k + 1]).strip()
        reason = ", ".join(reasons) if reasons else "self-contained topic"
        clips.append(Clip(index=n, start=segs[i].start, end=segs[k].end,
                          reason=reason, text=text, title=_title_from(text),
                          score=total))
    return clips
