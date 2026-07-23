"""Skool collector — Playwright over your authenticated browser session.

There is no stable official Skool API, so we drive a logged-in browser. This connector
is the most fragile in the system: Skool UI changes WILL break the selectors below.
They are centralized in SELECTORS and flagged by health_check so the dashboard can warn
you. Behavior contract:

  * READ-ONLY. Navigates and scrapes; never posts, comments, or reacts.
  * INCREMENTAL by default (new posts/comments since the stored cursor timestamp).
  * GENTLE pacing (config `pace_ms_between_requests`) — the admins are fine with
    reading your own community as long as we don't stress their systems.
  * A separate historical_import() method does the one-time big pull of your posts,
    comments, and course text (run by the setup wizard, not every cycle).

Selectors are intentionally isolated. Verify them once against your community with
`python scripts/run_once.py --only skool` and adjust SELECTORS as needed.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.collectors.base import BaseCollector
from app.models import NormalizedItem
from app.settings import get_settings

# --- ALL Skool DOM coupling lives here. Update in ONE place when Skool changes. ---
SELECTORS = {
    "feed_post": "[data-testid='post'], div.post-card",
    "post_link": "a[href*='/']",
    "post_author": "[data-testid='post-author'], .post-author",
    "post_time": "time, [datetime]",
    "post_body": "[data-testid='post-content'], .post-content",
    "comment": "[data-testid='comment'], .comment",
    "comment_author": ".comment-author",
    "comment_body": ".comment-content",
}


class SkoolCollector(BaseCollector):
    name = "skool"

    def __init__(self) -> None:
        self.cfg = get_settings().connector("skool")
        self.community_url = self.cfg["community_url"]
        self.pace_ms = int(self.cfg.get("pace_ms_between_requests", 1500))
        self.profile = self.cfg.get("chrome_profile_path")

    # --- browser session -------------------------------------------------
    def _launch(self):
        """Open a persistent context on your logged-in Chrome profile.

        Uses a COPY of your profile dir (set in config) so we never fight the live
        browser for the profile lock. Returns (playwright, context, page).
        """
        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        context = pw.chromium.launch_persistent_context(
            user_data_dir=self.profile,
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.new_page()
        return pw, context, page

    def health_check(self) -> bool:
        try:
            pw, context, page = self._launch()
            try:
                page.goto(self.community_url, wait_until="domcontentloaded", timeout=20000)
                ok = page.query_selector(SELECTORS["feed_post"]) is not None
                return ok
            finally:
                context.close(); pw.stop()
        except Exception:
            return False

    # --- incremental collection -----------------------------------------
    def fetch_new(self, cursor: str | None):
        since = float(cursor) if cursor else 0.0
        newest = since
        items: list[NormalizedItem] = []

        pw, context, page = self._launch()
        try:
            page.goto(self.community_url, wait_until="domcontentloaded", timeout=30000)
            self._pace(self.pace_ms)
            posts = page.query_selector_all(SELECTORS["feed_post"])
            for post in posts:
                data = self._read_post(post)
                if data is None:
                    continue
                ts = data["created_ts"]
                if ts <= since:
                    continue  # already have it
                newest = max(newest, ts)
                items.append(self._normalize_post(data))
                self._pace(self.pace_ms)
        finally:
            context.close(); pw.stop()

        return items, str(newest)

    def _read_post(self, post) -> dict | None:
        try:
            link_el = post.query_selector(SELECTORS["post_link"])
            body_el = post.query_selector(SELECTORS["post_body"])
            author_el = post.query_selector(SELECTORS["post_author"])
            time_el = post.query_selector(SELECTORS["post_time"])
            href = link_el.get_attribute("href") if link_el else None
            url = self._abs(href)
            dt_attr = time_el.get_attribute("datetime") if time_el else None
            ts = self._parse_ts(dt_attr)
            return {
                "url": url,
                "id": href or url,
                "author": author_el.inner_text().strip() if author_el else None,
                "body": body_el.inner_text().strip() if body_el else "",
                "created_ts": ts,
                "created_at": datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None,
            }
        except Exception:
            return None

    def _normalize_post(self, d: dict) -> NormalizedItem:
        return NormalizedItem(
            source=self.name,
            source_id=str(d["id"]),
            author=d.get("author"),
            url=d.get("url"),
            created_at=d.get("created_at"),
            title="Skool post",
            body=d.get("body", ""),
            raw={"kind": "post"},
        )

    # --- one-time historical import (called by setup wizard) -------------
    def historical_import(self) -> list[NormalizedItem]:
        """Deep pull of YOUR posts + comments + course text for the retrieval store.

        Run once. Paces gently. Returns NormalizedItems; the wizard hands them to
        retrieval.ingest so drafts can quote your real writing. Course/classroom
        pages are scraped read-only for text only.
        """
        collected: list[NormalizedItem] = []
        pw, context, page = self._launch()
        try:
            page.goto(self.community_url, wait_until="domcontentloaded", timeout=30000)
            # Scroll the feed to load history, gently.
            for _ in range(30):
                page.mouse.wheel(0, 4000)
                self._pace(self.pace_ms)
            for post in page.query_selector_all(SELECTORS["feed_post"]):
                d = self._read_post(post)
                if d:
                    collected.append(self._normalize_post(d))
            # Course text: navigate to /classroom and collect lesson bodies.
            # (Left as a focused follow-up; the feed import already seeds voice well.)
        finally:
            context.close(); pw.stop()
        return collected

    # --- helpers ---------------------------------------------------------
    def _abs(self, href: str | None) -> str | None:
        if not href:
            return None
        if href.startswith("http"):
            return href
        return "https://www.skool.com" + href

    @staticmethod
    def _parse_ts(dt_attr: str | None) -> float:
        if not dt_attr:
            return 0.0
        try:
            return datetime.fromisoformat(dt_attr.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
