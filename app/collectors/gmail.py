"""Gmail collector — official Gmail API, read-only scope.

Auth: OAuth desktop client. The client JSON and the resulting token JSON are stored
in the Keychain (the setup wizard runs the consent flow). Incremental collection uses
the config `query` (e.g. "newer_than:2d"); a history-id upgrade is noted below.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime

from app.collectors.base import BaseCollector, CollectorError
from app.models import NormalizedItem
from app.security import get_secret, set_secret
from app.settings import get_settings

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def _token_key(account: str | None) -> str:
    """Keychain account for a Gmail account's OAuth token. The legacy single-account
    key (google_oauth_token_json) is used when no per-account list is configured."""
    return "google_oauth_token_json" if not account else f"google_oauth_token_json:{account}"


def _build_service(account: str | None):
    """Build an authorized, read-only Gmail service for one account from Keychain."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    key = _token_key(account)
    token_json = get_secret(key, required=True)
    creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        set_secret(key, creds.to_json())  # persist rotated token
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


class GmailCollector(BaseCollector):
    name = "gmail"

    def __init__(self) -> None:
        self.cfg = get_settings().connector("gmail")
        # Multiple inboxes: one OAuth token per account in Keychain. Empty list =
        # legacy single account (token under the plain key).
        self.accounts: list[str | None] = list(self.cfg.get("accounts") or []) or [None]

    def health_check(self) -> bool:
        for account in self.accounts:
            try:
                _build_service(account).users().getProfile(userId="me").execute()
                return True  # at least one account authenticates
            except Exception:
                continue
        return False

    def fetch_new(self, cursor: str | None):
        query = self.cfg.get("query", "newer_than:2d")
        max_results = int(self.cfg.get("max_results", 150))
        # cursor is a json map {account: max_internalDate_ms}
        cursors = json.loads(cursor) if cursor else {}
        new_cursors = dict(cursors)
        items: list[NormalizedItem] = []

        for account in self.accounts:
            key = account or "default"
            try:
                service = _build_service(account)
            except Exception as exc:
                from app.security import audit
                audit("error", source="gmail", account=key, error=str(exc))
                continue
            last_ms = int(cursors.get(key, 0))
            resp = service.users().messages().list(
                userId="me", q=query, maxResults=max_results).execute()
            new_max = last_ms
            for m in resp.get("messages", []):
                msg = service.users().messages().get(
                    userId="me", id=m["id"], format="full").execute()
                internal = int(msg.get("internalDate", "0"))
                if internal <= last_ms:
                    continue
                new_max = max(new_max, internal)
                items.append(self._normalize(msg, internal, account))
            new_cursors[key] = new_max

        return items, json.dumps(new_cursors)

    def _normalize(self, msg: dict, internal_ms: int, account: str | None) -> NormalizedItem:
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        name, addr = parseaddr(headers.get("from", ""))
        created = datetime.fromtimestamp(internal_ms / 1000, tz=timezone.utc)
        body = self._extract_body(msg["payload"])
        # authuser deep-link opens the RIGHT inbox even with multiple accounts signed in
        if account:
            url = f"https://mail.google.com/mail/?authuser={account}#inbox/{msg['id']}"
        else:
            url = f"https://mail.google.com/mail/u/0/#inbox/{msg['id']}"
        # source_id namespaced by account so the same message id across inboxes is unique
        sid = f"{account}:{msg['id']}" if account else msg["id"]
        return NormalizedItem(
            source=self.name,
            source_id=sid,
            thread_id=msg.get("threadId"),
            author=name or addr,
            author_handle=addr,
            url=url,
            created_at=created,
            title=headers.get("subject"),
            body=body,
            raw={"snippet": msg.get("snippet"), "labelIds": msg.get("labelIds", []),
                 "account": account or "default"},
        )

    @staticmethod
    def _extract_body(payload: dict) -> str:
        """Prefer text/plain; fall back to first text/html part (sanitized later)."""
        def walk(part) -> str:
            mime = part.get("mimeType", "")
            data = part.get("body", {}).get("data")
            if mime == "text/plain" and data:
                return base64.urlsafe_b64decode(data).decode("utf-8", "replace")
            for sub in part.get("parts", []) or []:
                found = walk(sub)
                if found:
                    return found
            if mime == "text/html" and data:
                return base64.urlsafe_b64decode(data).decode("utf-8", "replace")
            return ""

        return walk(payload)


# NOTE: for very high volume, switch the cursor to Gmail's historyId and use
# users.history.list for true delta sync. The internalDate cursor above is simpler
# and robust for a personal mailbox with a "newer_than" query.
