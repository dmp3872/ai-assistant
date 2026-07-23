"""Google Calendar collector — official API, read-only scope.

Uses Calendar's syncToken for true incremental sync. Surfaces new invitations,
changed times, and cancellations. It never edits events.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.collectors.base import BaseCollector
from app.models import NormalizedItem
from app.security import get_secret, set_secret
from app.settings import get_settings

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def _build_service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    token_json = get_secret("google_oauth_token_json", required=True)
    # Reuse the same Google token as Gmail; it must include both scopes.
    creds = Credentials.from_authorized_user_info(
        json.loads(token_json),
        ["https://www.googleapis.com/auth/gmail.readonly", *SCOPES],
    )
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        set_secret("google_oauth_token_json", creds.to_json())
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


class CalendarCollector(BaseCollector):
    name = "calendar"

    def __init__(self) -> None:
        self.cfg = get_settings().connector("calendar")

    def health_check(self) -> bool:
        try:
            _build_service().calendarList().list(maxResults=1).execute()
            return True
        except Exception:
            return False

    def fetch_new(self, cursor: str | None):
        service = _build_service()
        cal_ids = self.cfg.get("calendar_ids", ["primary"])
        horizon_hours = int(self.cfg.get("horizon_hours", 168))

        # cursor is a json map {calendar_id: syncToken}
        tokens = json.loads(cursor) if cursor else {}
        new_tokens = dict(tokens)
        items: list[NormalizedItem] = []

        for cal_id in cal_ids:
            params = {"calendarId": cal_id, "singleEvents": True, "maxResults": 250}
            token = tokens.get(cal_id)
            if token:
                params["syncToken"] = token
            else:
                now = datetime.now(timezone.utc)
                params["timeMin"] = now.isoformat()
                params["timeMax"] = (now + timedelta(hours=horizon_hours)).isoformat()

            try:
                page = service.events().list(**params).execute()
            except Exception:
                # A 410 means the syncToken expired; drop it to do a full re-sync.
                params.pop("syncToken", None)
                now = datetime.now(timezone.utc)
                params["timeMin"] = now.isoformat()
                page = service.events().list(**params).execute()

            for ev in page.get("items", []):
                items.append(self._normalize(cal_id, ev))
            if page.get("nextSyncToken"):
                new_tokens[cal_id] = page["nextSyncToken"]

        return items, json.dumps(new_tokens)

    def _normalize(self, cal_id: str, ev: dict) -> NormalizedItem:
        status = ev.get("status")  # confirmed / cancelled
        start = (ev.get("start", {}) or {}).get("dateTime") or (ev.get("start", {}) or {}).get("date")
        created = ev.get("updated")
        when = self._parse(created)
        title = ev.get("summary") or "(no title)"
        if status == "cancelled":
            title = f"[CANCELLED] {title}"
        body_lines = [
            f"Start: {start}",
            f"Status: {status}",
            f"Location: {ev.get('location', '')}",
            f"Organizer: {(ev.get('organizer') or {}).get('email', '')}",
            f"Attendees: {', '.join(a.get('email','') for a in ev.get('attendees', []))}",
            "",
            ev.get("description", ""),
        ]
        return NormalizedItem(
            source=self.name,
            source_id=f"{cal_id}:{ev.get('id')}:{ev.get('updated','')}",
            author=(ev.get("organizer") or {}).get("displayName"),
            author_handle=(ev.get("organizer") or {}).get("email"),
            url=ev.get("htmlLink"),
            created_at=when,
            title=title,
            body="\n".join(body_lines),
            raw={"status": status, "start": start},
        )

    @staticmethod
    def _parse(ts: str | None):
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
