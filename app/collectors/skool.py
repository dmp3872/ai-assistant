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
from app.collectors import skool_api
from app.collectors.base import BaseCollector
from app.models import NormalizedItem
from app.security import get_secret
from app.settings import get_settings

# Re-exported so scripts/health checks can reference the DOM fallback selectors.
SELECTORS = sp.SELECTORS


class SkoolCollector(BaseCollector):
    name = "skool"

    def __init__(self) -> None:
        self.cfg = get_settings().connector("skool")
        self.community_url = (self.cfg.get("community_url") or "").rstrip("/")
        self.classroom_url = self.cfg.get("classroom_url") or f"{self.community_url}/classroom"
        self.pace_ms = int(self.cfg.get("pace_ms_between_requests", 1500))
        self.profile = self.cfg.get("chrome_profile_path")
        self.feed_scrolls = int(self.cfg.get("historical_feed_scrolls", 40))
        self.max_courses = int(self.cfg.get("max_courses", 100))
        self.max_lessons_per_course = int(self.cfg.get("max_lessons_per_course", 200))
        self.max_feed_pages = int(self.cfg.get("max_feed_pages", 20))
        self.feed_template = self.cfg.get("feed_page_template") or None
        # who "you" are, for voice-namespace routing
        self.author_name = (self.cfg.get("author_name") or "").strip().lower()
        self.author_handles = {h.strip().lower().lstrip("@")
                               for h in (self.cfg.get("author_handles") or []) if h}
        # PRIMARY: authenticated HTTP with your Skool session token (no browser).
        # FALLBACK: Playwright on your logged-in profile (if no token stored).
        self.token = get_secret("skool_auth_token")
        self.use_token = bool(self.token)
        # your Skool user_id, so @-mentions (which reference user ids) match you
        self.user_id = self.cfg.get("author_user_id") or skool_api.decode_user_id(self.token)

    # --- page fetch: token HTTP (primary) or Playwright (fallback) --------
    def _fetch_html(self, url: str) -> str:
        """Return a Skool page's HTML. Uses your session token over plain HTTPS when
        available (no browser); otherwise drives your logged-in Chrome profile."""
        self._pace(self.pace_ms)
        if self.use_token:
            return skool_api.get_html(url, self.token)
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        context = pw.chromium.launch_persistent_context(
            user_data_dir=self.profile, headless=True,
            args=["--disable-blink-features=AutomationControlled"])
        try:
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            self._pace(self.pace_ms)
            return page.content()
        finally:
            context.close(); pw.stop()

    def _resolve_community_url(self) -> str:
        """If community_url is unset/placeholder and we have a token, auto-discover
        the user's first group."""
        if self.community_url and "your-community" not in self.community_url:
            return self.community_url
        if self.use_token:
            groups = skool_api.discover_groups(self.token)
            if groups:
                self.community_url = groups[0]["url"]
                self.classroom_url = f"{self.community_url}/classroom"
        return self.community_url

    def health_check(self) -> bool:
        try:
            if self.use_token:
                return skool_api.check_auth(self.token)
            return bool(sp.parse_feed(self._fetch_html(self.community_url), self.community_url))
        except Exception:
            return False

    def discover_groups(self) -> list[dict]:
        """List the communities this token can see (name, slug, url)."""
        return skool_api.discover_groups(self.token) if self.use_token else []

    # --- incremental feed collection (every cycle) -----------------------
    def fetch_new(self, cursor: str | None):
        since = float(cursor) if cursor else 0.0
        newest = since
        items: list[NormalizedItem] = []
        url = self._resolve_community_url()
        for rec in sp.parse_feed(self._fetch_html(url), url):
            dt, ts = self._to_dt(rec.get("created_at"))
            if ts and ts <= since:
                continue
            newest = max(newest, ts)
            items.append(self._normalize(rec, dt))
        return items, str(newest)

    # --- one-time historical import (feed + comments + classroom) ---------
    def historical_import(self) -> list[NormalizedItem]:
        collected: list[NormalizedItem] = []
        url = self._resolve_community_url()
        # Deep feed history: paginate through Skool's data endpoint (token path);
        # Playwright fallback gets the first SSR page only.
        if self.use_token:
            recs = skool_api.paginate_feed(url, self.token, template=self.feed_template,
                                           max_pages=self.max_feed_pages,
                                           pace_s=self.pace_ms / 1000.0)
        else:
            recs = sp.parse_feed(self._fetch_html(url), url)
        for rec in recs:
            dt, _ = self._to_dt(rec.get("created_at"))
            collected.append(self._normalize(rec, dt))
        collected.extend(self._import_classroom())
        return collected

    def deep_feed(self) -> list[dict]:
        """All feed records across pages (token path). Used by scripts/skool_pull."""
        url = self._resolve_community_url()
        if self.use_token:
            return skool_api.paginate_feed(url, self.token, template=self.feed_template,
                                           max_pages=self.max_feed_pages,
                                           pace_s=self.pace_ms / 1000.0)
        return sp.parse_feed(self._fetch_html(url), url)

    def import_classroom(self) -> list[NormalizedItem]:
        """Public entry to (re)import just the classroom, without the feed."""
        self._resolve_community_url()
        return self._import_classroom()

    def _import_classroom(self) -> list[NormalizedItem]:
        lessons_out: list[NormalizedItem] = []
        courses = sp.parse_classroom_index(self._fetch_html(self.classroom_url), self.community_url)
        for course in courses[: self.max_courses]:
            try:
                lessons = sp.parse_course(self._fetch_html(course["url"]), course["url"])
            except Exception:
                continue
            for lesson in lessons[: self.max_lessons_per_course]:
                try:
                    parsed = sp.parse_lesson(self._fetch_html(lesson["url"]), lesson.get("id"))
                except Exception:
                    continue
                if not (parsed.get("body") or "").strip():
                    continue
                lessons_out.append(self._normalize_lesson(course, lesson, parsed))
        return lessons_out

    # --- normalization ---------------------------------------------------
    def _mentions_me(self, rec: dict) -> bool:
        return sp.mentions_user(rec, self.author_name, self.author_handles, self.user_id)

    def _normalize(self, rec: dict, dt: datetime | None) -> NormalizedItem:
        kind = rec.get("kind", "post")
        mentions_me = self._mentions_me(rec)
        # a new comment on YOUR post, by someone else -> you likely want to reply
        on_my_post = (kind == "comment"
                      and self._is_me(rec.get("parent_author"), None)
                      and not self._is_me(rec.get("author"), None))
        title = rec.get("title") or ("Skool comment" if kind == "comment" else "Skool post")
        if mentions_me:
            title = f"@you · {title}"
        elif on_my_post:
            title = f"reply on your post · {title}"
        return NormalizedItem(
            source=self.name,
            source_id=str(rec["id"]),
            thread_id=rec.get("parent_id"),
            author=rec.get("author"),
            url=rec.get("url"),
            created_at=dt,
            title=title,
            body=rec.get("body", ""),
            raw={"kind": kind,
                 "authored_by_me": self._is_me(rec.get("author"), rec.get("author_handle")),
                 "mentions_me": mentions_me,
                 "on_my_post": on_my_post},
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
