"""@-mention detection, replies-on-your-posts, and forced needs-response."""
import json

from app.collectors import skool_api, skool_parse as sp
from app.collectors.skool import SkoolCollector

MY_ID = "439eb61bf9e743fbaecbc6b8deca8b7f"


def _rec(**kw):
    base = {"kind": "comment", "id": "c1", "author": "Someone", "body": "",
            "parent_author": None, "mentions": []}
    base.update(kw)
    return base


def test_mentions_user_by_id():
    r = _rec(mentions=[MY_ID])
    assert sp.mentions_user(r, "Derek Pruski", ["derek"], MY_ID) is True
    assert sp.mentions_user(r, "Derek Pruski", ["derek"], "other-id") is False


def test_mentions_user_by_name_field():
    r = _rec(mentions=[{"metadata": {"name": "Derek Pruski"}}])
    assert sp.mentions_user(r, "Derek Pruski", [], None) is True


def test_mentions_user_by_at_text():
    assert sp.mentions_user(_rec(body="hey @derek pruski what do you think"),
                            "Derek Pruski", [], None) is True
    assert sp.mentions_user(_rec(body="hey @derek any thoughts"), None, ["derek"], None) is True
    assert sp.mentions_user(_rec(body="no mention here"), "Derek Pruski", ["derek"], None) is False


def test_decode_user_id_from_jwt():
    # header.payload.sig with payload {"user_id": MY_ID}
    import base64
    payload = base64.urlsafe_b64encode(json.dumps({"user_id": MY_ID}).encode()).decode().rstrip("=")
    token = f"h.{payload}.s"
    assert skool_api.decode_user_id(token) == MY_ID


def test_collector_flags_mention_and_reply(monkeypatch):
    payload = {"props": {"pageProps": {"posts": [
        {"id": "p1", "name": "My post", "metadata": {"content": "hi", "slug": "p1"},
         "user": {"metadata": {"name": "Derek Pruski"}},
         "comments": [{"id": "c1", "content": "nice one",
                       "user": {"metadata": {"name": "Fan A"}}}]},
        {"id": "p2", "name": "Question",
         "metadata": {"content": "hey @derek pruski help", "slug": "p2"},
         "user": {"metadata": {"name": "Fan B"}}, "comments": []},
    ]}}}
    feed = '<script id="__NEXT_DATA__">' + json.dumps(payload) + "</script>"
    monkeypatch.setattr(skool_api, "get_html", lambda url, token=None: feed)
    c = SkoolCollector(); c.token = "X"; c.use_token = True
    c.author_name = "derek pruski"; c.user_id = MY_ID; c.community_url = "https://www.skool.com/research-radar"
    items, _ = c.fetch_new(None)
    by_id = {i.source_id: i for i in items}
    # comment c1 is a reply on Derek's post p1 -> on_my_post
    assert by_id["p1:c:c1"].raw["on_my_post"] is True
    # post p2 @-mentions Derek -> mentions_me
    assert by_id["p2"].raw["mentions_me"] is True
