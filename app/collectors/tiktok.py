"""TikTok collector — your own creator profile via authenticated HTTP.

TikTok server-renders profile data into a script tag, so a GET of your profile page
returns your recent videos + engagement counts, parsed by tiktok_parse (no browser).
Read-only. TikTok bot-protects aggressively; if public fetches get blocked, store your
`tiktok_cookie` (exported like the Skool token) in the Keychain and it's sent with
requests. Per-comment pulling needs the Research API / an authenticated session — v1
surfaces new videos + comment counts with real links; comment alerts come via TikTok
notification emails (Gmail).

A cloud sandbox blocks tiktok.com at the network layer; this runs on your Mac.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.collectors import tiktok_parse as tp
from app.collectors.base import BaseCollector
from app.models import NormalizedItem
from app.security import get_secret
from app.settings import get_settings

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


class TikTokCollector(BaseCollector):
    name = "tiktok"

    def __init__(self) -> None:
        self.cfg = get_settings().connector("tiktok")
        self.username = (self.cfg.get("username") or "").lstrip("@")
        if not self.username:
            raise RuntimeError("tiktok.username not set in config")
        self.cookie = get_secret("tiktok_cookie")  # optional

    def _fetch_html(self) -> str:
        headers = {"User-Agent": _UA, "Accept": "text/html", "Accept-Language": "en-US,en;q=0.9"}
        cookies = {}
        if self.cookie:
            # accept either a raw cookie header string or just an sid; passed through
            cookies = {"tt-target-idc": "useast2a"}  # harmless hint; real auth via header
            headers["Cookie"] = self.cookie
        with httpx.Client(headers=headers, cookies=cookies, follow_redirects=True,
                          timeout=30) as c:
            r = c.get(f"https://www.tiktok.com/@{self.username}")
            r.raise_for_status()
            return r.text

    def health_check(self) -> bool:
        try:
            return bool(tp.parse_profile(self._fetch_html(), self.username))
        except Exception:
            return False

    def fetch_new(self, cursor: str | None):
        since = float(cursor) if cursor else 0.0
        newest = since
        items: list[NormalizedItem] = []
        for v in tp.parse_profile(self._fetch_html(), self.username):
            ts = self._epoch(v.get("create_time"))
            if ts and ts <= since:
                continue
            newest = max(newest, ts)
            items.append(self._normalize(v))
        return items, str(newest)

    def _normalize(self, v: dict) -> NormalizedItem:
        dt = None
        if v.get("create_time"):
            try:
                dt = datetime.fromisoformat(v["create_time"])
            except ValueError:
                dt = None
        desc = v.get("desc", "") or "(no caption)"
        body = (f"{desc}\n\n💬 {v['comment_count']} comments · ❤ {v['digg_count']} · "
                f"▶ {v['play_count']} plays")
        return NormalizedItem(
            source=self.name,
            source_id=str(v["id"]),
            author=f"@{self.username}",
            url=v["url"],
            created_at=dt,
            title=f"New TikTok · {desc[:60]}",
            body=body,
            raw={"kind": "video", "comment_count": v["comment_count"]},
        )

    @staticmethod
    def _epoch(iso: str | None) -> float:
        if not iso:
            return 0.0
        try:
            return datetime.fromisoformat(iso).timestamp()
        except ValueError:
            return 0.0
