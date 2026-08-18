"""The clip-point brain: natural cuts, length bounds, no mid-sentence splits.

Pure Python — no ffmpeg, no Whisper. Transcripts are built synthetically so each
assertion targets one behavior of segment_transcript()/parsers.
"""
from app.video.segment import (DEFAULT_MAX_S, DEFAULT_MIN_S, hms, segment_transcript)
from app.video.transcribe import parse_srt, parse_vtt, parse_timestamp, parse_whisper_json


def _talk(sentences, seg_dur=5.0, gap=0.0, start=0.0):
    """Build evenly-spaced segments, one per sentence."""
    segs, t = [], start
    for s in sentences:
        segs.append({"start": t, "end": t + seg_dur, "text": s})
        t += seg_dur + gap
    return segs


def _durations(clips):
    return [c.duration for c in clips]


# --- length bounds ----------------------------------------------------------------

def test_clips_land_in_5_to_7_minute_window():
    # ~30 min of 5s sentences -> several clips, all inside [5,7] min (last may be shorter)
    segs = _talk([f"Sentence number {i}." for i in range(360)], seg_dur=5.0)
    clips = segment_transcript(segs)
    assert len(clips) >= 4
    for c in clips[:-1]:
        assert DEFAULT_MIN_S <= c.duration <= DEFAULT_MAX_S, _durations(clips)
    # clips are contiguous and ordered
    for a, b in zip(clips, clips[1:]):
        assert b.start >= a.end


def test_short_video_is_a_single_clip():
    segs = _talk([f"Point {i}." for i in range(12)], seg_dur=5.0)  # ~1 min
    clips = segment_transcript(segs)
    assert len(clips) == 1
    assert clips[0].start == segs[0]["start"]
    assert clips[0].end == segs[-1]["end"]


def test_empty_transcript_yields_no_clips():
    assert segment_transcript([]) == []


# --- natural boundaries -----------------------------------------------------------

def test_never_cuts_mid_sentence_when_avoidable():
    # Alternate: complete sentences and fragments (no terminal punctuation). Cuts should
    # only ever fall on the sentence-ending segments.
    sents = []
    for i in range(200):
        sents.append(f"Complete thought {i}." if i % 2 == 0 else f"trailing fragment {i}")
    segs = _talk(sents, seg_dur=4.0)
    clips = segment_transcript(segs)
    for c in clips[:-1]:
        # the last transcript word of each clip should end a sentence
        assert c.text.rstrip().endswith((".", "?", "!")), c.text[-40:]


def test_prefers_pause_and_topic_shift():
    # Build ~6 min where two sentence-ends are both valid, but one is followed by a long
    # pause + a topic marker. That one should win.
    segs = _talk([f"Filler sentence {i}." for i in range(84)], seg_dur=4.0)  # 5:36 so far
    # craft two candidate boundaries around the 5:40–6:00 mark
    # boundary A at ~5:40 (plain), boundary B at ~5:52 with a big gap + "So," opener
    t = segs[-1]["end"]
    segs.append({"start": t, "end": t + 4, "text": "A plain closing sentence."})
    t2 = t + 4
    # long 2.5s pause before a clear topic shift
    segs.append({"start": t2 + 2.5, "end": t2 + 2.5 + 4, "text": "So, let's move to the next part."})
    segs += _talk([f"More {i}." for i in range(80)], seg_dur=4.0, start=t2 + 2.5 + 4)
    clips = segment_transcript(segs)
    first = clips[0]
    # the first clip should end right before the topic-shift/pause line (i.e. include the
    # "plain closing sentence") — its reason should credit the natural seam
    assert "pause" in first.reason or "topic shift" in first.reason, first.reason


# --- tail handling ----------------------------------------------------------------

def test_short_tail_is_merged():
    # length chosen so a naive split would leave a ~30s orphan at the end
    segs = _talk([f"Line {i}." for i in range(150)], seg_dur=5.0)  # 12:30 total
    clips = segment_transcript(segs, min_tail_s=90)
    assert clips[-1].duration >= 90  # no tiny orphan
    # coverage is complete: last clip ends at the very end
    assert abs(clips[-1].end - segs[-1]["end"]) < 1e-6


def test_reason_is_recorded():
    segs = _talk([f"Sentence {i}." for i in range(120)], seg_dur=5.0)
    clips = segment_transcript(segs)
    assert all(c.reason for c in clips)


def test_hms_formatting():
    assert hms(0) == "00:00:00.000"
    assert hms(3661.5) == "01:01:01.500"


# --- transcript parsers -----------------------------------------------------------

def test_parse_timestamp_variants():
    assert parse_timestamp("01:02:03,500") == 3723.5
    assert parse_timestamp("00:00:05.250") == 5.25
    assert parse_timestamp("02:05.000") == 125.0  # MM:SS


def test_parse_srt():
    srt = ("1\n00:00:00,000 --> 00:00:04,000\nHello there.\n\n"
           "2\n00:00:04,000 --> 00:00:08,500\nSecond line here.\n")
    segs = parse_srt(srt)
    assert len(segs) == 2
    assert segs[0] == {"start": 0.0, "end": 4.0, "text": "Hello there."}
    assert segs[1]["end"] == 8.5


def test_parse_vtt_strips_tags():
    vtt = ("WEBVTT\n\n00:00:00.000 --> 00:00:03.000\n<v Derek>Welcome</v> back.\n\n"
           "00:00:03.000 --> 00:00:06.000\nSecond cue.\n")
    segs = parse_vtt(vtt)
    assert len(segs) == 2
    assert segs[0]["text"] == "Welcome back."


def test_parse_whisper_json_shapes():
    assert parse_whisper_json({"segments": [{"start": 0, "end": 1, "text": "hi"}]}) == \
        [{"start": 0.0, "end": 1.0, "text": "hi"}]
    assert parse_whisper_json([{"start": 2, "end": 3, "text": "yo"}])[0]["text"] == "yo"
