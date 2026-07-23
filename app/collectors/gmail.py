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


def _build_service():
    """Build an authorized, read-only Gmail service from Keychain-stored creds."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    token_json = get_secret("google_oauth_token_json", required=True)
    creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        set_secret("google_oauth_token_json", creds.to_json())  # persist rotated token
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


class GmailCollector(BaseCollector):
    name = "gmail"

    def __init__(self) -> None:
        self.cfg = get_settings().connector("gmail")

    def health_check(self) -> bool:
        try:
            _build_service().users().getProfile(userId="me").execute()
            return True
        except Exception:
            return False

    def fetch_new(self, cursor: str | None):
        service = _build_service()
        query = self.cfg.get("query", "newer_than:2d")
        max_results = int(self.cfg.get("max_results", 100))

        # Cursor here is the max internalDate we've already seen (ms since epoch).
        last_ms = int(cursor) if cursor else 0

        resp = service.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()
        ids = [m["id"] for m in resp.get("messages", [])]

        items: list[NormalizedItem] = []
        new_max = last_ms
        for mid in ids:
            msg = service.users().messages().get(
                userId="me", id=mid, format="full"
            ).execute()
            internal = int(msg.get("internalDate", "0"))
            if internal <= last_ms:
                continue  # already collected on a prior run
            new_max = max(new_max, internal)
            items.append(self._normalize(msg, internal))

        return items, str(new_max)

    def _normalize(self, msg: dict, internal_ms: int) -> NormalizedItem:
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        name, addr = parseaddr(headers.get("from", ""))
        created = datetime.fromtimestamp(internal_ms / 1000, tz=timezone.utc)
        body = self._extract_body(msg["payload"])
        return NormalizedItem(
            source=self.name,
            source_id=msg["id"],
            thread_id=msg.get("threadId"),
            author=name or addr,
            author_handle=addr,
            url=f"https://mail.google.com/mail/u/0/#inbox/{msg['id']}",
            created_at=created,
            title=headers.get("subject"),
            body=body,
            raw={"snippet": msg.get("snippet"), "labelIds": msg.get("labelIds", [])},
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
