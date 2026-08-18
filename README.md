# Radar Assistant

A **local-first** personal assistant that runs on your MacBook. Every 45 minutes it
pulls new activity from your accounts (Gmail, Google Calendar, Telegram, Skool, and
more), classifies it locally, drafts responses in your voice using the Claude API,
and surfaces everything in a local dashboard at `http://localhost:4317`.

It **never** sends, posts, replies, deletes, or edits anything. It reads, it drafts,
you review and copy. That is the whole design.

---

## Why this shape (and not a chatbot)

You already have Claude Cowork, the Claude app, ChatGPT, and Perplexity. **None of
them should be the always-running assistant.** They are conversational surfaces, not
schedulers. An unattended job that reads your most sensitive data every 45 minutes
needs deterministic scheduling, persistent state, per-connector cursors, dedup, audit
logs, and hard security boundaries. That is an *application*, not a chat session.

So the roles are:

| Tool | Role |
|------|------|
| **Claude Code** | Builds and maintains *this* application |
| **Claude API** (key) | Writes drafts in your voice, produces summaries |
| **Ollama** (local) | Private first-pass classification, dedup, spam filtering |
| **Claude Cowork / app** | Manual, interactive one-offs — not the backend |
| **ChatGPT / Perplexity** | Secondary drafting / external research — not the backend |

Full reasoning in [`docs/architecture.md`](docs/architecture.md).

---

## What it does every 45 minutes

```
launchd fires (every 45 min)
  → acquire lock (no overlapping runs)
  → check connector health
  → pull ONLY items created since last successful cursor
  → sanitize untrusted content (strip HTML/scripts/hidden text, neutralize injection)
  → classify + dedupe locally (Ollama)
  → retrieve your relevant past content (LanceDB)
  → draft a response in your voice (Claude API)
  → store items + drafts + source links (SQLite)
  → update the dashboard
  → one macOS notification: "digest ready"
```

It writes nothing back to any source. Ever. (Phase 4 adds *drafts* inside your own
tools, still gated behind manual approval.)

---

## Dashboard tabs

1. **Priority Inbox** — executive overview across all sources
2. **PeptidePrice Sales** — structured vendor promo extraction (dates, codes, exclusions)
3. **Community** — Skool questions/comments/mentions with copy-ready drafts
4. **Studio** — the content system: a stocked shelf of ready-to-post posts + a Q&A
   answer bank (see below)
5. **Plan** — daily content quotas, each slot backed by a real queued draft to copy
6. **Personal / Admin** — accountant, lawyer, calendar, employees (kept separate)
7. **Review History** — your drafts vs. what you actually posted → learns your style

---

## The content system (Studio)

The reply drafter is *reactive* — it waits for a question. **Studio is proactive**: it
keeps you from ever staring at a blank page. Every 45-minute cycle it:

- **Clusters recurring questions** from your Skool community into an **Answer Bank** and
  drafts one canonical, reusable answer per question — so a reply always exists.
- **Tops up a Post Queue** per channel (Skool / TikTok / Substack / YouTube) to a target
  depth with fresh posts, grounded **only** in your own imported content (classroom,
  past posts) via the public retrieval namespaces — never personal/financial data.

Everything queues for **your** review in Studio and on the Plan tab: edit inline, one-tap
**Copy**, then **Posted** (which learns from what you actually posted) or **Discard**.
Generation is capped per cycle to protect your Anthropic spend, and dedup keys make a
full shelf a near no-op on the next run.

**It still never posts anything for you.** Same hard boundary as the rest of Radar — it
stocks the shelf; you pick and post. Details and tuning in
[`docs/content-system.md`](docs/content-system.md).

---

## Auto video clipper

Point it at a long video; get natural **5–7 minute clips** back — no timeline editing:

```bash
python scripts/clip_video.py ~/Desktop/podcast.mp4
```

It transcribes the audio (Whisper), scans the transcript for natural break points near the
6-minute mark (sentence ends, pauses, topic shifts), and cuts clips there with ffmpeg —
never mid-sentence, never touching the original. Clips are auto-titled (when your API key
is set) and land in a folder with a `clips.json` manifest. Needs `ffmpeg` and a Whisper
backend on your Mac (or pass a transcript with `--transcript`). Full guide:
[`docs/video-clipper.md`](docs/video-clipper.md).

---

## Quick start (on your Mac)

```bash
git clone https://github.com/dmp3872/ai-assistant.git radar-assistant
cd radar-assistant
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

# interactive setup: stores secrets in macOS Keychain, does OAuth, seeds config
python scripts/setup_wizard.py

# one-off run to confirm connectors work
python scripts/run_once.py

# start the dashboard
uvicorn app.main:app --port 4317
# open http://localhost:4317

# install the 45-minute scheduler
cp scheduler/com.radar.assistant.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.radar.assistant.plist
```

See [`docs/implementation-plan.md`](docs/implementation-plan.md) for the phased build
order and exactly which connectors are live vs. stubbed today.

---

## Status of this repository

This is **Phase 1** scaffolding: full architecture, database, security, pipeline,
dashboard, and the Gmail / Calendar / Telegram / Skool collectors wired to real APIs.
Some connectors require **your** credentials and a real macOS environment to run —
those spots are marked clearly and the setup wizard walks you through them. Apple
Messages, WhatsApp, and TikTok are Phase 2/3 and ship as documented stubs.

See [`docs/connector-support-matrix.md`](docs/connector-support-matrix.md) for the
honest per-connector state, effort, and fragility.
