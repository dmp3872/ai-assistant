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


def test_fetch_new_via_token(monkeypatch):
    monkeypatch.setattr(skool_api, "get_html", lambda url, token=None: FEED)
    c = SkoolCollector(); c.token = "X"; c.use_token = True
    c.community_url = "https://www.skool.com/peptideprice"
    items, cursor = c.fetch_new(None)
    # 2 posts + 1 comment = 3 normalized items
    assert len(items) == 3
    assert all(i.source == "skool" for i in items)
