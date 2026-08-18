"""Video clipper: point at a long video, get natural 5–7 minute clips automatically.

Pipeline: transcript (Whisper or a file) -> segment_transcript() finds natural cut
points -> ffmpeg cuts the clips. See docs/video-clipper.md and scripts/clip_video.py.
"""
from app.video.segment import Clip, Segment, segment_transcript

__all__ = ["Clip", "Segment", "segment_transcript"]
