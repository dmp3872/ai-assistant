"""Pure parsers for Skool pages. NO browser here — these take HTML strings and return
plain dicts, so they are fully unit-testable offline (see tests/test_skool_parse.py).

Strategy, in priority order:
  1. `__NEXT_DATA__` JSON. Skool is a Next.js app and embeds page props as JSON in a
     <script id="__NEXT_DATA__"> tag. Parsing that is FAR more stable than CSS
     selectors, which Skool changes often. We walk the JSON defensively — matching on
     field *shapes* (an id + some content + an author) rather than fixed paths — so a
     key rename upstream usually doesn't break us.
  2. CSS/DOM fallback (SELECTORS below) for pages that render content client-side and
     don't embed it in __NEXT_DATA__.

Two things to verify ONCE against your community on first import (both centralized
here so it's a one-line tweak): the field aliases in the *_KEYS lists, and the URL
templates. `scripts/import_skool.py --debug` dumps what was discovered to help.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable

from bs4 import BeautifulSoup

# --- CSS fallback selectors (used only when __NEXT_DATA__ has no content) ----------
SELECTORS = {
    "feed_post": "[data-testid='post'], div.post-card, div[class*='PostItem']",
    "post_link": "a[href*='/']",
    "post_author": "[data-testid='post-author'], .post-author, a[href*='/@']",
    "post_time": "time, [datetime]",
    "post_body": "[data-testid='post-content'], .post-content, div[class*='PostContent']",
    "comment": "[data-testid='comment'], .comment, div[class*='Comment']",
    "course_card": "a[href*='/classroom/']",
    "lesson_link": "a[href*='?md='], a[href*='/classroom/']",
    "lesson_title": "h1, [data-testid='lesson-title'], div[class*='Title']",
    "lesson_body": "[data-testid='lesson-content'], div[class*='Content'], article",
}

# --- field aliases for the JSON walker (verify once against your community) ---------
CONTENT_KEYS = ["content", "body", "text", "post", "description", "markdown"]
TITLE_KEYS = ["name", "title", "label", "headline"]
AUTHOR_CONTAINER_KEYS = ["user", "author", "createdBy", "owner", "member", "poster"]
AUTHOR_NAME_KEYS = ["name", "displayName", "fullName", "firstName"]
COMMENT_KEYS = ["comments", "replies", "children"]
SLUG_KEYS = ["slug", "permalink", "handle"]
TIME_KEYS = ["createdAt", "created_at", "publishedAt", "updatedAt", "timestamp"]

_NEXT_DATA_RE = re.compile(
    r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.DOTALL
)


# ------------------------------------------------------------------ helpers
def extract_next_data(html: str) -> dict | None:
    m = _NEXT_DATA_RE.search(html or "")
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except (ValueError, TypeError):
        return None


def _first_str(d: dict, keys: Iterable[str]) -> str | None:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _content_of(d: dict) -> str | None:
    direct = _first_str(d, CONTENT_KEYS)
    if direct:
        return direct
    md = d.get("metadata")
    if isinstance(md, dict):
        return _first_str(md, CONTENT_KEYS)
    return None


def _title_of(d: dict) -> str | None:
    t = _first_str(d, TITLE_KEYS)
    if t:
        return t
    md = d.get("metadata")
    if isinstance(md, dict):
        return _first_str(md, TITLE_KEYS)
    return None


def _author_of(d: dict) -> str | None:
    for k in AUTHOR_CONTAINER_KEYS:
        u = d.get(k)
        if isinstance(u, dict):
            name = _first_str(u, AUTHOR_NAME_KEYS)
            if name:
                return name
            md = u.get("metadata")
            if isinstance(md, dict):
                name = _first_str(md, AUTHOR_NAME_KEYS)
                if name:
                    return name
        elif isinstance(u, str) and u.strip():
            return u.strip()
    return None


def _time_of(d: dict) -> str | None:
    t = _first_str(d, TIME_KEYS)
    if t:
        return t
    md = d.get("metadata")
    if isinstance(md, dict):
        return _first_str(md, TIME_KEYS)
    return None


def _looks_like_post(d: dict) -> bool:
    return bool(d.get("id")) and bool(_content_of(d)) and bool(_author_of(d))


def _comments_of(post: dict) -> list[dict]:
    for k in COMMENT_KEYS:
        v = post.get(k)
        if isinstance(v, list):
            return [c for c in v if isinstance(c, dict) and _content_of(c)]
    return []


def _iter_posts(data: Any) -> list[dict]:
    """Find post-like dicts anywhere in the JSON, without descending into their
    comment lists (so comments aren't mis-collected as top-level posts)."""
    found: list[dict] = []

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            if _looks_like_post(o):
                found.append(o)
                for k, v in o.items():
                    if k in COMMENT_KEYS:
                        continue
                    walk(v)
            else:
                for v in o.values():
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    return found


# ------------------------------------------------------------------ URL builders
def post_url(community_url: str, post: dict) -> str:
    slug = _first_str(post, SLUG_KEYS)
    md = post.get("metadata") if isinstance(post.get("metadata"), dict) else {}
    slug = slug or _first_str(md, SLUG_KEYS)
    base = community_url.rstrip("/")
    if slug:
        return f"{base}/{slug}" if not slug.startswith("http") else slug
    return f"{base}?p={post.get('id')}"


def lesson_url(course_url: str, lesson_id: str | None) -> str:
    if not lesson_id:
        return course_url
    sep = "&" if "?" in course_url else "?"
    return f"{course_url}{sep}md={lesson_id}"


# ------------------------------------------------------------------ public parsers
def parse_feed(html: str, community_url: str) -> list[dict]:
    """Return a flat list of {kind, id, title, author, body, url, created_at} for
    posts AND their comments. Prefers __NEXT_DATA__, falls back to DOM."""
    data = extract_next_data(html)
    if data:
        out: list[dict] = []
        for post in _iter_posts(data):
            pid = str(post.get("id"))
            purl = post_url(community_url, post)
            out.append({
                "kind": "post",
                "id": pid,
                "title": _title_of(post) or "Skool post",
                "author": _author_of(post),
                "body": _content_of(post) or "",
                "url": purl,
                "created_at": _time_of(post),
                "parent_id": None,
            })
            for c in _comments_of(post):
                out.append({
                    "kind": "comment",
                    "id": f"{pid}:c:{c.get('id')}",
                    "title": None,
                    "author": _author_of(c),
                    "body": _content_of(c) or "",
                    "url": purl,
                    "created_at": _time_of(c),
                    "parent_id": pid,
                })
        if out:
            return out
    return _parse_feed_dom(html, community_url)


def _parse_feed_dom(html: str, community_url: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "lxml")
    out: list[dict] = []
    for el in soup.select(SELECTORS["feed_post"]):
        link = el.select_one(SELECTORS["post_link"])
        body = el.select_one(SELECTORS["post_body"])
        author = el.select_one(SELECTORS["post_author"])
        time_el = el.select_one(SELECTORS["post_time"])
        href = link.get("href") if link else None
        out.append({
            "kind": "post",
            "id": href or (body.get_text(strip=True)[:40] if body else None),
            "title": "Skool post",
            "author": author.get_text(strip=True) if author else None,
            "body": body.get_text(" ", strip=True) if body else "",
            "url": _abs(href) or community_url,
            "created_at": time_el.get("datetime") if time_el else None,
            "parent_id": None,
        })
    return [o for o in out if o["id"]]


def parse_classroom_index(html: str, community_url: str) -> list[dict]:
    """Return [{id, title, url}] for each course in the classroom."""
    data = extract_next_data(html)
    courses: list[dict] = []
    seen: set[str] = set()
    if data:
        for node in _iter_course_nodes(data):
            cid = str(node.get("id"))
            if cid in seen:
                continue
            seen.add(cid)
            slug = _first_str(node, SLUG_KEYS) or cid
            courses.append({
                "id": cid,
                "title": _title_of(node) or "Course",
                "url": f"{community_url.rstrip('/')}/classroom/{slug}",
            })
        if courses:
            return courses
    # DOM fallback
    soup = BeautifulSoup(html or "", "lxml")
    for a in soup.select(SELECTORS["course_card"]):
        href = a.get("href")
        if not href or "/classroom/" not in href:
            continue
        url = _abs(href)
        if url in seen:
            continue
        seen.add(url)
        courses.append({"id": href.rstrip("/").split("/")[-1],
                        "title": a.get_text(" ", strip=True) or "Course", "url": url})
    return courses


def _iter_course_nodes(data: Any) -> list[dict]:
    """Course-like: has id + a title + a 'classroom'/'course'/'modules'/'lessons' hint."""
    found: list[dict] = []
    hint = re.compile(r"course|classroom|module|lesson|curriculum", re.I)

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            has_title = bool(_title_of(o)) and bool(o.get("id"))
            typ = str(o.get("type", "")) + " " + str(o.get("__typename", ""))
            if has_title and (hint.search(typ) or any(k in o for k in ("modules", "lessons", "sets"))):
                found.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    return found


def parse_course(html: str, course_url: str) -> list[dict]:
    """Return [{id, title, url}] for lessons within one course page."""
    data = extract_next_data(html)
    lessons: list[dict] = []
    seen: set[str] = set()
    if data:
        for node in _iter_lesson_nodes(data):
            lid = str(node.get("id"))
            if lid in seen:
                continue
            seen.add(lid)
            lessons.append({
                "id": lid,
                "title": _title_of(node) or "Lesson",
                "url": lesson_url(course_url, lid),
            })
        if lessons:
            return lessons
    soup = BeautifulSoup(html or "", "lxml")
    for a in soup.select(SELECTORS["lesson_link"]):
        href = a.get("href") or ""
        m = re.search(r"md=([\w-]+)", href)
        lid = m.group(1) if m else href.rstrip("/").split("/")[-1]
        if not lid or lid in seen:
            continue
        seen.add(lid)
        lessons.append({"id": lid, "title": a.get_text(" ", strip=True) or "Lesson",
                        "url": lesson_url(course_url, lid)})
    return lessons


def _iter_lesson_nodes(data: Any) -> list[dict]:
    found: list[dict] = []
    hint = re.compile(r"lesson|module|content|video|set", re.I)

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            typ = str(o.get("type", "")) + " " + str(o.get("__typename", ""))
            if o.get("id") and _title_of(o) and hint.search(typ):
                found.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    return found


def parse_lesson(html: str, lesson_id: str | None = None) -> dict:
    """Return {id, title, body} for a single lesson page."""
    data = extract_next_data(html)
    if data:
        for node in _iter_lesson_nodes(data):
            body = _content_of(node)
            if body:
                return {"id": str(node.get("id")), "title": _title_of(node) or "Lesson",
                        "body": body}
    soup = BeautifulSoup(html or "", "lxml")
    title_el = soup.select_one(SELECTORS["lesson_title"])
    body_el = soup.select_one(SELECTORS["lesson_body"])
    return {
        "id": lesson_id,
        "title": title_el.get_text(" ", strip=True) if title_el else "Lesson",
        "body": body_el.get_text("\n", strip=True) if body_el else "",
    }


def _abs(href: str | None) -> str | None:
    if not href:
        return None
    if href.startswith("http"):
        return href
    return "https://www.skool.com" + href
