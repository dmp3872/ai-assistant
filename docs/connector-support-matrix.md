# Connector Support Matrix

Honest state of every connector: how it reads, whether it's live in this repo, how
fragile it is, and what *you* must provide. "Live" means real code wired to a real
API/automation; it still needs your credentials and a real macOS environment to run.

| Source | Method | Phase | State in repo | Fragility | You must provide |
|--------|--------|-------|---------------|-----------|------------------|
| **Gmail** | Official Gmail API (OAuth, `gmail.readonly`) | 1 | Live | Low | Google Cloud OAuth client, consent |
| **Google Calendar** | Official Calendar API (`calendar.readonly`) | 1 | Live | Low | Same Google OAuth client |
| **Telegram** | Official client API via Telethon (your user account) | 1 | Live | Low | `api_id` + `api_hash` from my.telegram.org, phone login |
| **Skool** | Playwright on your authenticated Chrome profile | 1 | Live (automation is inherently brittle) | **High** | Logged-in Chrome profile; admin OK (you have it) |
| **Apple Messages** | Read local `chat.db` (Full Disk Access) | 2 | Stub + design | Medium (breaks on macOS updates) | Full Disk Access grant |
| **WhatsApp** | Playwright on WhatsApp Web session | 2 | Stub + design | **High** | Authenticated WhatsApp Web |
| **TikTok** | TikTok Studio via Playwright + notification emails | 3 | Stub + design | **High** | Logged-in creator account |

## Notes per connector

### Gmail / Calendar
Cleanest connectors. Official REST APIs, incremental via `historyId` (Gmail) and
`syncToken` (Calendar), read-only scopes. One Google Cloud project + OAuth desktop
client covers both. The setup wizard runs the OAuth flow and stores the refresh token
in Keychain.

### Telegram
Telegram *officially* supports user-authorized apps via `api_id`/`api_hash`. Telethon
logs in as **your** account and reads DMs, chosen groups, mentions, and replies. We do
**not** ingest every large group — you pick which chats to watch in config. Session
string is stored in Keychain.

### Skool — read this carefully
There is **no stable official Skool API.** But Skool serves reads via **Next.js SSR**,
so an **authenticated HTTPS GET** (sending your `auth_token` session cookie) returns the
page with all data embedded in `__NEXT_DATA__` — no browser required. This is the
primary path (`app/collectors/skool_api.py`); Playwright on your logged-in profile is
the fallback when no token is stored.

**Token:** export your `auth_token` cookie once (e.g. with cookie-editor.com) and store
it via the setup wizard — it lives in the macOS Keychain, never in the repo. It's a
credential; Skool's WAF can rotate it, so re-export if requests start failing. Pull with:
`python scripts/skool_pull.py --draft` (lists posts you haven't answered + drafts a
comment for each). **Note:** a cloud sandbox blocks `skool.com` at the network layer —
this runs on your Mac.

Historical/incremental collection then works the same way:
- One **initial historical import** of your posts, comments, **and full classroom**
  (every course → every lesson → lesson text).
- **Incremental** collection every cycle (new posts/comments/mentions since cursor).
- A slower **overnight reconciliation** scan to catch anything missed.
- We do **not** crawl the whole community every 45 minutes.

You said the Skool admins are fine with reading your own community via your account as
long as we don't stress their systems. The collector honors that: gentle pacing,
incremental only, no writes.

**Parsing strategy (why this is more robust than raw selectors).** Skool is a Next.js
app, so the collector prefers the `__NEXT_DATA__` JSON blob embedded in each page over
brittle CSS. The browser only navigates/scrolls/clicks; all extraction lives in the
pure, offline-tested module `app/collectors/skool_parse.py` and matches on field
*shapes* (an id + content + author) rather than fixed paths, with a CSS/DOM fallback.
When Skool changes upstream you usually adjust a couple of alias lists (`*_KEYS`) and
URL templates in one file — the fixtures in `tests/test_skool_parse.py` tell you when
they need updating.

**Voice retrieval.** Imported content is routed by authorship (config
`skool.author_name` / `author_handles`): your posts → `skool_posts`, your comments →
`skool_comments`, all lessons → `courses`. Other members' posts are not your writing
and are skipped for voice. Long text is chunked (`app/retrieval/chunk.py`) before
embedding so retrieved snippets carry their lesson/post context. Run and verify with:

```bash
python scripts/import_skool.py --debug          # see what parsed + who's tagged as you
python scripts/import_skool.py                  # feed history + classroom, then ingest
python scripts/import_skool.py --classroom-only # re-pull just courses/lessons
```

Verify two things once against your community (both centralized, one-line tweaks): the
`__NEXT_DATA__` field aliases and the post/lesson URL templates in `skool_parse.py`.

### Apple Messages (Phase 2)
iMessage history is in a local SQLite DB (`~/Library/Messages/chat.db`). We open it
**read-only**, copy new rows into our own normalized DB, track the last processed
`ROWID`, and never touch the original. Requires Full Disk Access. The `attributedBody`
BLOB needs careful decoding (Apple's typedstream). Attachments ignored initially.

### WhatsApp (Phase 2)
Hardest connector. Meta's Cloud API targets *business* numbers, not your personal
Messenger account. Practical path: read-only Playwright automation of WhatsApp Web on
your authenticated profile. Fragile; never sends.

### TikTok (Phase 3)
TikTok's official comment access lives behind the Research API scope, not a normal
creator integration. So Phase 3 starts with notification emails + TikTok Studio
browser automation for *your own* posts and comments, with direct links. Secondary
connector — expect breakage on UI changes.
