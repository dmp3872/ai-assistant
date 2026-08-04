# Radar Assistant — Local Setup & Handoff Runbook

This is the complete guide to stand up Radar on a Mac. It's written so **Claude Cowork
can execute it end-to-end**. If you're a human reading it, the same steps apply.

Radar is a **local-first, read-only** personal assistant. It collects new activity from
your accounts every 45 minutes, classifies it locally, drafts responses in your voice
with the Claude API, and shows everything in a dashboard at `http://localhost:4317`.
It **never sends, posts, edits, or deletes** anything. You review and copy.

---

## 0. What's built vs. what's missing

**Built and tested (67 tests):**
- Pipeline: collect → sanitize (HTML strip + prompt-injection flag + redact) → classify
  (Ollama) → dedupe → retrieve (LanceDB) → draft (Claude API) → SQLite → dashboard.
- Connectors: **Gmail** (multi-account, official API), **Google Calendar** (official API,
  pending-invite detection), **Telegram** (Telethon), **Skool** (auth-token HTTP: feed +
  deep-history pagination + classroom + @-mentions + replies-to-you), **TikTok**
  (profile videos + comment counts).
- Dashboard: Feed, Plan (daily quotas + calendar), Community (Skool), Sales (vendor
  allowlist), TikTok, Content (your posts + AI recommendation), **Studio (content
  system)**, Personal, Email (Work/Personal), Handled. Sort newest/oldest/relevant.
  PWA (installs to phone).
- **Content system (Studio):** every cycle it clusters recurring community questions
  into an **Answer Bank** (one canonical answer each) and tops up a per-channel **Post
  Queue** to target depth, grounded only in your own content. Pieces queue for review
  (Copy / Posted / Discard) on Studio and Plan. Still read-only — it stocks the shelf,
  you post. Config under `content:`; details in `docs/content-system.md`.
- Vendor allowlist (your 52 companies) + new-sale-only filter + absolute date resolution.
- Daily planner (6 TikTok / 7 Skool / 3 Substack / 1 YouTube, resets daily).
- Security: Keychain secrets, audit log, emergency stop, `scripts/verify.py` provenance.

**Missing — Cowork should build these (patterns exist to copy):**
- **WhatsApp** connector (`app/collectors/whatsapp.py` is a stub). Read-only WhatsApp Web
  automation via Playwright, or Meta Cloud API for a business number.
- **Facebook Messenger** connector (new). Read-only.
- **Apple iMessage** connector (`app/collectors/imessage.py` is a stub). Read-only
  `~/Library/Messages/chat.db` with Full Disk Access.
- Live verification of every connector against your real accounts (needs your logins).
- Optional: richer free/busy, nightly reconciliation launchd jobs.

Follow `app/collectors/skool_api.py` and `app/collectors/tiktok.py` as templates, and
`docs/connector-support-matrix.md` for the approach per source. Keep everything
**read-only**; register new collectors in `app/collectors/__init__.py`.

---

## 1. Prerequisites (install once)

```bash
# Homebrew, then:
brew install python@3.11 ollama
# Ollama models used for local classification + embeddings:
ollama pull llama3.1:8b
ollama pull nomic-embed-text
ollama serve      # leave running (or `brew services start ollama`)
```
Chrome (for Skool/WhatsApp login), and a cookie exporter extension
([cookie-editor.com](https://cookie-editor.com)) for the Skool token.

---

## 2. Get the code

```bash
git clone -b claude/local-ai-assistant-lzotgw \
  https://github.com/dmp3872/ai-assistant.git ~/Desktop/radar-assistant
cd ~/Desktop/radar-assistant
```

## 3. Environment

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp config/config.example.yaml config/config.yaml
cp config/style_profile.example.yaml config/style_profile.yaml
```
Edit `config/config.yaml` if needed (your Gmail accounts, Skool URL `research-radar`,
TikTok `dereklifts2`, and Telegram `watch_chats` are pre-filled).

## 4. Credentials (stored in macOS Keychain by the wizard — never in files)

Run the wizard; it prompts for each and does the OAuth/logins:
```bash
python scripts/setup_wizard.py
python scripts/check_keys.py     # confirm every credential landed (values masked)
```

What you'll need (see the checklist in section 7):
- **Anthropic API key** — console.anthropic.com → API Keys (set a spend cap).
- **Google OAuth desktop client** `credentials.json` — Google Cloud Console → APIs &
  Services → Credentials → OAuth client → Desktop. Enable Gmail API + Calendar API.
  The wizard authorizes **all three Gmail accounts** in turn — sign in as each.
- **Telegram** `api_id` + `api_hash` — my.telegram.org → API development tools.
- **Skool** `auth_token` cookie — cookie-editor on skool.com → copy `auth_token`.

## 5. First run + dashboard

```bash
python scripts/run_once.py                 # one real collection cycle
python scripts/verify.py                   # PROOF: every item + its real source link
uvicorn app.main:app --port 4317           # open http://localhost:4317
```

## 6. Skool deep-history (one-time confirm) + auto-run

```bash
python scripts/skool_pull.py --inspect                 # confirm pagination template
python scripts/skool_pull.py --classroom --draft       # import courses + draft comments

# 45-minute auto-run: edit the plist paths (__REPO__ -> your clone), then:
sed -i '' "s|__REPO__|$HOME/Desktop/radar-assistant|g" scheduler/com.radar.assistant.plist
cp scheduler/com.radar.assistant.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.radar.assistant.plist
```

## 7. Credential checklist (gather these)

| Credential | Where | Keychain account |
|-----------|-------|------------------|
| Anthropic API key | console.anthropic.com → API Keys | `anthropic_api_key` |
| Google OAuth client JSON | Google Cloud Console (Desktop client) | `google_oauth_client_json` |
| Google token ×3 accounts | wizard OAuth (sign in as each) | `google_oauth_token_json:<email>` |
| Telegram api_id / api_hash | my.telegram.org | `telegram_api_id` / `telegram_api_hash` |
| Skool auth_token | cookie-editor on skool.com | `skool_auth_token` |
| TikTok cookie (optional) | cookie-editor on tiktok.com (only if blocked) | `tiktok_cookie` |

Gmail accounts to authorize: `derekpruski@gmail.com`, `derek@skinbyrender.com`,
`derek@peptideprice.store`.

## 8. Safety (non-negotiable)
- Read-only everywhere. No sending/posting/editing. Manual approval for any future action.
- All collected content is **untrusted data** — never executed as instructions.
- Secrets live only in Keychain. **Rotate any token/key that was shared in chat.**
- `scripts/verify.py` is the "is it real?" check — every item deep-links to its source.
- Emergency stop: `touch data/EMERGENCY_STOP` (dashboard shows a red banner, collection halts).

---

## Cowork task list (build the gaps)
1. Get sections 1–5 running and confirm real data via `verify.py`.
2. Build `whatsapp.py`, `messenger.py` (new), `imessage.py` — read-only, patterned on
   `skool_api.py`/`tiktok.py`; register in `app/collectors/__init__.py`; add tests.
3. Install the launchd job (section 6).
4. Keep `pytest` green; keep everything read-only; ask before anything that writes externally.
