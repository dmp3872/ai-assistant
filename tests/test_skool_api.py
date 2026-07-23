"""Token-path Skool: group discovery + unanswered-post detection (offline, the only
part a sandbox can't do live is the network fetch, which we stub)."""
import json

from app.collectors import skool_api, skool_parse as sp
from app.collectors.skool import SkoolCollector


def _nd(payload):
    return f'<script id="__NEXT_DATA__">{json.dumps(payload)}</script>'


HOME = _nd({"props": {"pageProps": {"groups": [
    {"id": "g1", "name": "Peptide Price Insiders", "slug": "peptideprice",
     "__typename": "Group", "memberCount": 1240}]}}})
FEED = _nd({"props": {"pageProps": {"posts": [
    {"id": "p1", "name": "Ipamorelin vs CJC?", "metadata": {"content": "thoughts?", "slug": "ipa"},
     "user": {"metadata": {"name": "Jamie R"}}, "createdAt": "2026-07-23T09:00:00Z", "comments": []},
    {"id": "p2", "name": "BPC log", "metadata": {"content": "notes", "slug": "bpc"},
     "user": {"metadata": {"name": "Chris T"}}, "createdAt": "2026-07-22T18:00:00Z",
     "comments": [{"id": "c1", "content": "keep us posted",
                   "user": {"metadata": {"name": "Derek Pruski"}}}]}]}}})


def test_parse_groups():
    groups = sp.parse_groups(HOME)
    assert groups == [{"name": "Peptide Price Insiders", "slug": "peptideprice",
                       "url": "https://www.skool.com/peptideprice"}]


def test_group_discovery_and_resolve(monkeypatch):
    monkeypatch.setattr(skool_api, "get_html", lambda url, token=None: HOME)
    c = SkoolCollector(); c.token = "X"; c.use_token = True
    c.community_url = ""  # force auto-discovery from the token
    assert c.discover_groups()[0]["slug"] == "peptideprice"
    assert c._resolve_community_url() == "https://www.skool.com/peptideprice"


def test_unanswered_detection(monkeypatch):
    monkeypatch.setattr(skool_api, "get_html",
                        lambda url, token=None: HOME if url.rstrip("/").endswith(".com") else FEED)
    c = SkoolCollector(); c.token = "X"; c.use_token = True; c.author_name = "derek pruski"
    url = c._resolve_community_url()
    recs = sp.parse_feed(c._fetch_html(url), url)
    posts = [r for r in recs if r["kind"] == "post"]
    comments = [r for r in recs if r["kind"] == "comment"]
    answered = {cm["parent_id"] for cm in comments if c._is_me(cm["author"], None)}
    unanswered = [p for p in posts if not c._is_me(p["author"], None) and p["id"] not in answered]
    assert len(unanswered) == 1 and unanswered[0]["id"] == "p1"


def _post(pid, name="P"):
    return {"id": pid, "name": name, "metadata": {"content": "c", "slug": pid},
            "user": {"metadata": {"name": "Someone"}}, "createdAt": "2026-07-20T00:00:00Z",
            "comments": []}


def test_extract_build_id_and_cursor():
    html = _nd({"buildId": "abc123", "props": {"pageProps": {
        "posts": [_post("p1")], "hasNextPage": True, "nextCursor": "cur2"}}})
    assert sp.extract_build_id(html) == "abc123"
    hint = sp.extract_page_cursor(html)
    assert hint["cursor"] == "cur2" and hint["has_next"] is True
    assert "nextCursor" in hint["keys_seen"]


def test_paginate_feed_walks_pages_and_dedups(monkeypatch):
    page1 = _nd({"buildId": "b1", "props": {"pageProps": {
        "posts": [_post("p1"), _post("p2")], "hasNextPage": True, "nextCursor": "c2"}}})
    page2 = {"pageProps": {"posts": [_post("p2"), _post("p3")],  # p2 dup
                           "hasNextPage": True, "nextCursor": "c3"}}
    page3 = {"pageProps": {"posts": [_post("p4")], "hasNextPage": False}}
    monkeypatch.setattr(skool_api, "get_html", lambda url, token=None: page1)
    seq = iter([page2, page3, {"pageProps": {"posts": []}}])
    monkeypatch.setattr(skool_api, "get_json", lambda url, token=None: next(seq))

    recs = skool_api.paginate_feed("https://www.skool.com/research-radar", "X", max_pages=10)
    ids = sorted({r["id"] for r in recs if r["kind"] == "post"})
    assert ids == ["p1", "p2", "p3", "p4"]  # deduped p2, stopped at has_next False


def test_paginate_feed_first_page_only_without_buildid(monkeypatch):
    monkeypatch.setattr(skool_api, "get_html",
                        lambda url, token=None: _nd({"props": {"pageProps": {"posts": [_post("p1")]}}}))
    recs = skool_api.paginate_feed("https://www.skool.com/research-radar", "X")
    assert len([r for r in recs if r["kind"] == "post"]) == 1  # no buildId -> graceful


def test_fetch_new_via_token(monkeypatch):
    monkeypatch.setattr(skool_api, "get_html", lambda url, token=None: FEED)
    c = SkoolCollector(); c.token = "X"; c.use_token = True
    c.community_url = "https://www.skool.com/peptideprice"
    items, cursor = c.fetch_new(None)
    # 2 posts + 1 comment = 3 normalized items
    assert len(items) == 3
    assert all(i.source == "skool" for i in items)
