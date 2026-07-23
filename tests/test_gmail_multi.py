"""Multiple Gmail inboxes: per-account tokens, namespaced ids, per-account cursors,
authuser deep-links. The Google client is faked (no network)."""
import json

from app.collectors import gmail
from app.collectors.gmail import GmailCollector


class _E:
    def __init__(self, v): self.v = v
    def execute(self): return self.v


class _Messages:
    def __init__(self, msgs): self.msgs = msgs
    def list(self, userId, q, maxResults): return _E({"messages": [{"id": m["id"]} for m in self.msgs]})
    def get(self, userId, id, format): return _E(next(m for m in self.msgs if m["id"] == id))


class _Users:
    def __init__(self, msgs): self._m = _Messages(msgs)
    def messages(self): return self._m
    def getProfile(self, userId): return _E({"emailAddress": "x"})


class FakeService:
    def __init__(self, msgs): self._u = _Users(msgs)
    def users(self): return self._u


def _msg(mid, subject, sender, internal="1753000000000"):
    return {"id": mid, "threadId": "t" + mid, "internalDate": internal,
            "snippet": subject, "labelIds": ["INBOX"],
            "payload": {"mimeType": "text/plain",
                        "headers": [{"name": "From", "value": sender},
                                    {"name": "Subject", "value": subject}],
                        "body": {}}}


def test_multi_account_collection(monkeypatch):
    data = {
        "derekpruski@gmail.com": [_msg("a1", "personal note", "friend@x.com")],
        "derek@peptideprice.store": [_msg("b1", "vendor sale", "sales@ezpeptides.com")],
        "derek@skinbyrender.com": [_msg("c1", "salon booking", "book@salon.com")],
    }
    monkeypatch.setattr(gmail, "_build_service", lambda account: FakeService(data.get(account, [])))

    c = GmailCollector()  # 3 accounts from config
    assert set(c.accounts) == set(data.keys())
    items, cursor = c.fetch_new(None)

    ids = {it.source_id for it in items}
    assert ids == {"derekpruski@gmail.com:a1", "derek@peptideprice.store:b1",
                   "derek@skinbyrender.com:c1"}
    # each item deep-links to its OWN inbox via authuser
    peptide = next(it for it in items if it.source_id.startswith("derek@peptideprice.store"))
    assert "authuser=derek@peptideprice.store" in peptide.url
    assert peptide.raw["account"] == "derek@peptideprice.store"
    # per-account cursors persisted
    cur = json.loads(cursor)
    assert set(cur.keys()) == set(data.keys())


def test_incremental_skips_already_seen(monkeypatch):
    data = {"derekpruski@gmail.com": [_msg("a1", "s", "x@y.com", internal="1753000000000")],
            "derek@peptideprice.store": [], "derek@skinbyrender.com": []}
    monkeypatch.setattr(gmail, "_build_service", lambda account: FakeService(data.get(account, [])))
    c = GmailCollector()
    _, cursor = c.fetch_new(None)
    items2, _ = c.fetch_new(cursor)  # same data, higher cursor -> nothing new
    assert items2 == []
