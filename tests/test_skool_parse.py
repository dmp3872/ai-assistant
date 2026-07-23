"""Offline tests for the Skool parsers using representative __NEXT_DATA__ fixtures
and a DOM fallback fixture. These pin down extraction without touching a live site.
If Skool changes its JSON shape, update the *_KEYS lists in skool_parse.py and these
fixtures together.
"""
import json

from app.collectors import skool_parse as sp


def _next_data_html(payload: dict) -> str:
    blob = json.dumps(payload)
    return f'<html><body><script id="__NEXT_DATA__" type="application/json">{blob}</script></body></html>'


FEED = _next_data_html({"props": {"pageProps": {"feed": {"posts": [
    {"id": "p1", "name": "How labs test Cerebrolysin",
     "metadata": {"content": "Here is how LC-MS works...", "slug": "how-labs-test"},
     "user": {"metadata": {"name": "Derek Pruski"}},
     "createdAt": "2026-01-02T10:00:00Z",
     "comments": [
         {"id": "c1", "content": "Does this prove authenticity?",
          "user": {"metadata": {"name": "John Smith"}}, "createdAt": "2026-01-02T11:00:00Z"},
         {"id": "c2", "content": "No, it shows presence, not authenticity.",
          "user": {"metadata": {"name": "Derek Pruski"}}, "createdAt": "2026-01-02T12:00:00Z"},
     ]},
    {"id": "p2", "name": "Member question", "metadata": {"content": "Where do I buy X?"},
     "user": {"metadata": {"name": "Jane Doe"}}, "createdAt": "2026-01-03T09:00:00Z",
     "comments": []},
]}}}})

COMMUNITY = "https://www.skool.com/peptides"


def test_parse_feed_extracts_posts_and_comments():
    recs = sp.parse_feed(FEED, COMMUNITY)
    kinds = [(r["kind"], r["author"]) for r in recs]
    assert ("post", "Derek Pruski") in kinds
    assert ("post", "Jane Doe") in kinds
    assert ("comment", "John Smith") in kinds
    assert ("comment", "Derek Pruski") in kinds
    assert len(recs) == 4


def test_parse_feed_builds_post_url_from_slug():
    post = next(r for r in sp.parse_feed(FEED, COMMUNITY) if r["id"] == "p1")
    assert post["url"] == "https://www.skool.com/peptides/how-labs-test"


def test_parse_feed_comment_links_to_parent():
    c = next(r for r in sp.parse_feed(FEED, COMMUNITY) if r["kind"] == "comment"
             and r["author"] == "John Smith")
    assert c["parent_id"] == "p1"


def test_parse_classroom_index():
    html = _next_data_html({"props": {"pageProps": {"courses": [
        {"id": "course1", "name": "Peptide Basics", "__typename": "Course",
         "slug": "peptide-basics", "modules": []},
        {"id": "course2", "name": "Advanced Testing", "type": "course",
         "slug": "advanced-testing", "lessons": []},
    ]}}})
    courses = sp.parse_classroom_index(html, COMMUNITY)
    titles = {c["title"] for c in courses}
    assert {"Peptide Basics", "Advanced Testing"} <= titles
    assert any(c["url"].endswith("/classroom/peptide-basics") for c in courses)


def test_parse_course_lists_lessons():
    html = _next_data_html({"props": {"pageProps": {"course": {
        "id": "course1", "name": "Peptide Basics", "lessons": [
            {"id": "l1", "name": "Intro", "__typename": "Lesson", "content": "hi"},
            {"id": "l2", "name": "LC-MS 101", "type": "lesson",
             "metadata": {"content": "long"}},
        ]}}}})
    lessons = sp.parse_course(html, "https://www.skool.com/peptides/classroom/peptide-basics")
    ids = {l["id"] for l in lessons}
    assert ids == {"l1", "l2"}
    assert all("md=" in l["url"] for l in lessons)


def test_parse_lesson_body():
    html = _next_data_html({"props": {"pageProps": {"lesson": {
        "id": "l2", "name": "LC-MS 101", "__typename": "Lesson",
        "metadata": {"content": "LC-MS separates compounds by mass to charge ratio."}}}}})
    lesson = sp.parse_lesson(html, "l2")
    assert lesson["title"] == "LC-MS 101"
    assert "LC-MS separates" in lesson["body"]


def test_parse_feed_dom_fallback_when_no_next_data():
    html = (
        '<div class="post-card"><a href="/peptides/some-post">x</a>'
        '<div class="post-content">Body text here</div>'
        '<span class="post-author">Derek</span>'
        '<time datetime="2026-01-01T00:00:00Z"></time></div>'
    )
    recs = sp.parse_feed(html, COMMUNITY)
    assert len(recs) == 1
    assert recs[0]["author"] == "Derek"
    assert "Body text" in recs[0]["body"]
