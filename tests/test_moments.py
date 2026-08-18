"""The moment finder: select engaging bits, drop the boring stretches."""
from app.video.moments import find_moments


def _mk(lines, dur=4.0):
    segs, t = [], 0.0
    for txt, gap in lines:
        segs.append({"start": t, "end": t + dur, "text": txt})
        t += dur + gap
    return segs


BORING = ("We should probably discuss the schedule for next week at some point.", 0.0)
ENGAGING = [
    ("So here's the biggest mistake people make, and it's honestly insane.", 1.6),
    ("When I first started I wasted 2,000 dollars on a total disaster.", 0.0),
    ("Why? Because nobody tells you the one secret that changes everything.", 0.0),
    ("The lab results came back only 40 percent pure, which is crazy dangerous.", 0.0),
    ("That's the secret nobody talks about, and it changed everything for me.", 0.0),
]


def test_selects_engaging_and_drops_boring():
    segs = _mk([BORING] * 40 + ENGAGING + [BORING] * 40)
    clips = find_moments(segs)
    assert 1 <= len(clips) <= 3                       # not a wall-to-wall slice
    top = clips[0]
    assert top.score and top.score >= 2.0
    # the moment starts on the engaging line, not in the boring lead-in
    assert "boring" not in top.title.lower()
    assert top.title.lower().startswith("so here")
    assert "hook" in top.reason or "story" in top.reason or "question" in top.reason


def test_all_boring_yields_nothing():
    clips = find_moments(_mk([BORING] * 80))
    assert clips == []                                # nothing engaging → no clips


def test_max_moments_caps_output():
    # several engaging blocks separated by boring filler
    blocks = []
    for _ in range(6):
        blocks += ENGAGING + [BORING] * 15
    clips = find_moments(_mk(blocks), max_moments=3)
    assert len(clips) <= 3


def test_moments_are_chronological_and_scored():
    segs = _mk([BORING] * 20 + ENGAGING + [BORING] * 20 + ENGAGING + [BORING] * 20)
    clips = find_moments(segs)
    starts = [c.start for c in clips]
    assert starts == sorted(starts)                   # output ordered by time
    assert all(c.score is not None for c in clips)
    assert all(c.reason for c in clips)


def test_empty_input():
    assert find_moments([]) == []
