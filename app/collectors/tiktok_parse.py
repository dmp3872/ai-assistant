"""Pure parser for a TikTok creator profile page. Like Skool, TikTok server-renders
its data into a script tag (`SIGI_STATE` on older pages, `__UNIVERSAL_DATA_FOR_
REHYDRATION__` on newer ones). We parse that JSON — offline-testable, no browser.

Scope: your own posts (videos) + their engagement counts + real per-video links.
Per-comment pulling needs an authenticated session (ms_token/signatures) or the
Research API; this surfaces new videos and comment COUNTS so you can click through,
and TikTok notification emails (via Gmail) cover comment alerts.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

_SCRIPT_IDS = ["__UNIVERSAL_DATA_FOR_REHYDRATION__", "SIGI_STATE"]


def extract_rehydration(html: str) -> dict | None:
    for sid in _SCRIPT_IDS:
        m = re.search(rf'<script[^>]+id="{sid}"[^>]*>(.*?)</script>', html or "", re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except (ValueError, TypeError):
                continue
    return None


def _iter_videos(data: Any) -> list[dict]:
    """Find video-like dicts anywhere in the rehydration JSON (a video has an id,
    a text `desc`, and a `createTime`)."""
    found: dict[str, dict] = {}

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            if o.get("id") and isinstance(o.get("desc"), str) and (
                    o.get("createTime") or o.get("createTimeISO")):
                found[str(o["id"])] = o
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    return list(found.values())


def _ts(v) -> str | None:
    if v is None:
        return None
    try:
        return datetime.fromtimestamp(int(v), tz=timezone.utc).isoformat()
    except (ValueError, TypeError):
        try:
            return datetime.fromisoformat(str(v).replace("Z", "+00:00")).isoformat()
        except ValueError:
            return None


def parse_profile(html: str, username: str) -> list[dict]:
    """Return [{id, desc, url, create_time, comment_count, digg_count, play_count}]."""
    data = extract_rehydration(html)
    if not data:
        return []
    handle = username.lstrip("@")
    out: list[dict] = []
    for v in _iter_videos(data):
        vid = str(v["id"])
        st = v.get("stats") or v.get("statsV2") or {}
        out.append({
            "id": vid,
            "desc": v.get("desc", ""),
            "url": f"https://www.tiktok.com/@{handle}/video/{vid}",
            "create_time": _ts(v.get("createTime") or v.get("createTimeISO")),
            "comment_count": int(st.get("commentCount", 0) or 0),
            "digg_count": int(st.get("diggCount", 0) or 0),
            "play_count": int(st.get("playCount", 0) or 0),
        })
    return out
