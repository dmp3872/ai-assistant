"""Skool collector — Playwright over your authenticated browser session.

There is no stable official Skool API, so we drive a logged-in browser. Read-only.
This module handles ONLY navigation/scrolling/clicking and hands raw page HTML to the
pure parsers in skool_parse.py (which prefer Skool's __NEXT_DATA__ JSON over brittle
CSS). That split keeps the fragile DOM knowledge in one testable place.

Behavior contract:
  * READ-ONLY. Navigates and scrapes; never posts, comments, or reacts.
  * INCREMENTAL feed collection every cycle (new posts/comments since the cursor).
  * A one-time historical_import(): your full feed history + comments, PLUS the
    classroom (every course -> every lesson -> lesson text) for voice retrieval.
  * GENTLE pacing (config `pace_ms_between_requests`).
  * Authorship tagging: items you wrote are flagged authored_by_me so ingestion can
    route them into your voice namespaces (skool_posts / skool_comments); lessons go
    to the `courses` namespace.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.collectors import skool_parse as sp
from app.collectors.base import BaseCollector
from app.models import NormalizedItem
from app.settings import get_settings

# Re-exported so scripts/health checks can reference the DOM fallback selectors.
SELECTORS = sp.SELECTORS


class SkoolCollector(BaseCollector):
    name = "skool"

    def __init__(self) -> None:
        self.cfg = get_settings().connector("skool")
        self.community_url = self.cfg["community_url"].rstrip("/")
        self.classroom_url = self.cfg.get("classroom_url") or f"{self.community_url}/classroom"
        self.pace_ms = int(self.cfg.get("pace_ms_between_requests", 1500))
        self.profile = self.cfg.get("chrome_profile_path")
        self.feed_scrolls = int(self.cfg.get("historical_feed_scrolls", 40))
        self.max_courses = int(self.cfg.get("max_courses", 100))
        self.max_lessons_per_course = int(self.cfg.get("max_lessons_per_course", 200))
        # who "you" are, for voice-namespace routing
        self.author_name = (self.cfg.get("author_name") or "").strip().lower()
        self.author_handles = {h.strip().lower().lstrip("@")
                               for h in (self.cfg.get("author_handles") or []) if h}

    # --- browser session -------------------------------------------------
    def _launch(self):
        """Open a persistent context on your logged-in Chrome profile (a copy of it,
        set in config, so we never fight the live browser for the profile lock)."""
        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        context = pw.chromium.launch_persistent_context(
            user_data_dir=self.profile,
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.new_page()
        return pw, context, page

    def _goto(self, page, url: str):
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        self._pace(self.pace_ms)

    def health_check(self) -> bool:
        try:
            pw, context, page = self._launch()
            try:
                self._goto(page, self.community_url)
                return bool(sp.parse_feed(page.content(), self.community_url))
            finally:
                context.close(); pw.stop()
        except Exception:
            return False

    # --- incremental feed collection (every cycle) -----------------------
    def fetch_new(self, cursor: str | None):
        since = float(cursor) if cursor else 0.0
        newest = since
        items: list[NormalizedItem] = []

        pw, context, page = self._launch()
        try:
            self._goto(page, self.community_url)
            for rec in sp.parse_feed(page.content(), self.community_url):
                dt, ts = self._to_dt(rec.get("created_at"))
                if ts and ts <= since:
                    continue
                newest = max(newest, ts)
                items.append(self._normalize(rec, dt))
        finally:
            context.close(); pw.stop()
        return items, str(newest)

    # --- one-time historical import (feed + comments + classroom) ---------
    def historical_import(self) -> list[NormalizedItem]:
        collected: list[NormalizedItem] = []
        pw, context, page = self._launch()
        try:
            # 1) Feed history: scroll to load older posts, then parse everything once.
            self._goto(page, self.community_url)
            for _ in range(self.feed_scrolls):
                page.mouse.wheel(0, 5000)
                self._pace(self.pace_ms)
            for rec in sp.parse_feed(page.content(), self.community_url):
                dt, _ = self._to_dt(rec.get("created_at"))
                collected.append(self._normalize(rec, dt))

            # 2) Classroom: every course -> every lesson -> lesson text.
            collected.extend(self._import_classroom(page))
        finally:
            context.close(); pw.stop()
        return collected

    def import_classroom(self) -> list[NormalizedItem]:
        """Public entry to (re)import just the classroom, without the feed."""
        pw, context, page = self._launch()
        try:
            return self._import_classroom(page)
        finally:
            context.close(); pw.stop()

    def _import_classroom(self, page) -> list[NormalizedItem]:
        lessons_out: list[NormalizedItem] = []
        self._goto(page, self.classroom_url)
        courses = sp.parse_classroom_index(page.content(), self.community_url)
        for course in courses[: self.max_courses]:
            try:
                self._goto(page, course["url"])
            except Exception:
                continue
            lessons = sp.parse_course(page.content(), course["url"])
            for lesson in lessons[: self.max_lessons_per_course]:
                try:
                    self._goto(page, lesson["url"])
                    parsed = sp.parse_lesson(page.content(), lesson.get("id"))
                except Exception:
                    continue
                body = parsed.get("body") or ""
                if not body.strip():
                    continue
                lessons_out.append(self._normalize_lesson(course, lesson, parsed))
        return lessons_out

    # --- normalization ---------------------------------------------------
    def _normalize(self, rec: dict, dt: datetime | None) -> NormalizedItem:
        kind = rec.get("kind", "post")
        return NormalizedItem(
            source=self.name,
            source_id=str(rec["id"]),
            thread_id=rec.get("parent_id"),
            author=rec.get("author"),
            url=rec.get("url"),
            created_at=dt,
            title=rec.get("title") or ("Skool comment" if kind == "comment" else "Skool post"),
            body=rec.get("body", ""),
            raw={"kind": kind, "authored_by_me": self._is_me(rec.get("author"),
                                                             rec.get("author_handle"))},
        )

    def _normalize_lesson(self, course: dict, lesson: dict, parsed: dict) -> NormalizedItem:
        return NormalizedItem(
            source=self.name,
            source_id=f"lesson:{course['id']}:{lesson['id']}",
            author=self.cfg.get("author_name"),
            url=lesson["url"],
            title=f"{course.get('title', 'Course')} — {parsed.get('title', 'Lesson')}",
            body=parsed.get("body", ""),
            # lessons are your course material: always voice/knowledge, always ingested
            raw={"kind": "lesson", "authored_by_me": True,
                 "course": course.get("title"), "course_id": course["id"]},
        )

    # --- helpers ---------------------------------------------------------
    def _is_me(self, author: str | None, handle: str | None) -> bool:
        if author and self.author_name and author.strip().lower() == self.author_name:
            return True
        if handle and handle.strip().lower().lstrip("@") in self.author_handles:
            return True
        return False

    @staticmethod
    def _to_dt(value) -> tuple[datetime | None, float]:
        """Accept ISO-8601 strings or epoch (sec/ms). Return (datetime, unix_ts)."""
        if value is None or value == "":
            return None, 0.0
        # numeric epoch
        try:
            num = float(value)
            if num > 1e12:  # milliseconds
                num /= 1000.0
            dt = datetime.fromtimestamp(num, tz=timezone.utc)
            return dt, dt.timestamp()
        except (ValueError, TypeError):
            pass
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt, dt.timestamp()
        except ValueError:
            return None, 0.0
