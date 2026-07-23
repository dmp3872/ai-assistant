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
There is **no stable official Skool API.** Third-party APIs have existed and been
suspended; endpoint availability is inconsistent. So we drive your **already-logged-in
browser** with Playwright:
- One **initial historical import** of your posts, comments, and course text.
- **Incremental** collection every cycle (new posts/comments/mentions since cursor).
- A slower **overnight reconciliation** scan to catch anything missed.
- We do **not** crawl the whole community every 45 minutes.

You said the Skool admins are fine with reading your own community via your account as
long as we don't stress their systems. The collector honors that: gentle pacing,
incremental only, no writes. Selectors *will* break when Skool ships UI changes — the
health check catches this and the dashboard flags it. Treat Skool as maintenance-heavy.

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
