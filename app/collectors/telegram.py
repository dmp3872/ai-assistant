"""Telegram collector — official client API via Telethon (your user account).

Reads only the chats you list in config (`watch_chats`) plus mentions/replies.
We do NOT indiscriminately ingest every large group. Read-only: no messages sent.

Telethon is async; we drive it synchronously from the pipeline with a private loop.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from app.collectors.base import BaseCollector
from app.models import NormalizedItem
from app.security import get_secret
from app.settings import get_settings


class TelegramCollector(BaseCollector):
    name = "telegram"

    def __init__(self) -> None:
        self.cfg = get_settings().connector("telegram")

    def health_check(self) -> bool:
        return bool(get_secret("telegram_session"))

    def fetch_new(self, cursor: str | None):
        return asyncio.run(self._fetch_async(cursor))

    async def _fetch_async(self, cursor: str | None):
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        api_id = int(get_secret("telegram_api_id", required=True))
        api_hash = get_secret("telegram_api_hash", required=True)
        session = get_secret("telegram_session", required=True)

        # cursor is a json map {chat_key: last_message_id}
        seen = json.loads(cursor) if cursor else {}
        new_seen = dict(seen)
        items: list[NormalizedItem] = []

        watch = self.cfg.get("watch_chats", []) or []
        async with TelegramClient(StringSession(session), api_id, api_hash) as client:
            me = await client.get_me()
            for chat in watch:
                key = str(chat)
                min_id = int(seen.get(key, 0))
                last_id = min_id
                async for msg in client.iter_messages(chat, min_id=min_id, limit=200):
                    if not msg.message:
                        continue
                    last_id = max(last_id, msg.id)
                    mentioned = bool(getattr(msg, "mentioned", False))
                    is_reply_to_me = await self._is_reply_to_me(client, msg, me.id)
                    items.append(self._normalize(chat, msg, mentioned or is_reply_to_me))
                new_seen[key] = last_id

        return items, json.dumps(new_seen)

    @staticmethod
    async def _is_reply_to_me(client, msg, my_id: int) -> bool:
        if not msg.reply_to_msg_id:
            return False
        try:
            parent = await msg.get_reply_message()
            return bool(parent and parent.sender_id == my_id)
        except Exception:
            return False

    def _normalize(self, chat, msg, is_for_me: bool) -> NormalizedItem:
        sender = getattr(msg, "sender", None)
        author = None
        handle = None
        if sender is not None:
            author = " ".join(filter(None, [getattr(sender, "first_name", None),
                                            getattr(sender, "last_name", None)])) or None
            handle = getattr(sender, "username", None)
        created = msg.date.astimezone(timezone.utc) if msg.date else None
        return NormalizedItem(
            source=self.name,
            source_id=f"{chat}:{msg.id}",
            thread_id=str(chat),
            author=author,
            author_handle=handle,
            url=None,  # public deep links only exist for public chats; left None otherwise
            created_at=created,
            title=f"Telegram ({'mention/reply' if is_for_me else 'chat'}): {chat}",
            body=msg.message or "",
            raw={"mentioned": is_for_me},
        )
