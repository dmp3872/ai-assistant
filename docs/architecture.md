# Architecture

## Principles

1. **Local-first.** All state lives on your MacBook. The only network calls out are
   to the official APIs you connect (Google, Telegram, etc.) and to the Anthropic API
   for drafting. No third-party server holds your data.
2. **Read-only by default.** Collectors never mutate a source. The dashboard is the
   only place actions happen, and in Phase 1 the only "action" is copying text.
3. **Separation of collection and action.** The collector process only reads. Any
   future outbound action is a *separate*, explicitly-invoked process (Phase 4).
4. **Untrusted content.** Every email body, comment, message, and calendar note is
   treated as hostile data, never as instructions. See `threat-model.md`.
5. **Deterministic scheduling.** `launchd` fires the pipeline. There is no
   long-running chat holding the system together.
6. **Incremental.** Every connector persists a cursor and pulls only what is new.

## Process model

```
┌─────────────────────────────────────────────────────────────────┐
│ launchd  (com.radar.assistant.plist, StartInterval=2700s)        │
└───────────────┬─────────────────────────────────────────────────┘
                │ spawns
                ▼
        python -m app.scheduler.run_cycle
                │  (holds a file lock; exits when done)
                │
   ┌────────────┼─────────────────────────────────────────────┐
   ▼            ▼                     ▼                          ▼
collectors → sanitize → classify(Ollama) → retrieve(LanceDB) → draft(Claude API)
   │                                                              │
   └────────────────────────► SQLite (items, drafts, audit) ◄────┘
                                       │
                                       ▼
              FastAPI dashboard (uvicorn, always-on, :4317)
                  reads SQLite, renders tabs, serves drafts
```

The **dashboard** (uvicorn) and the **pipeline** (`run_cycle`) are two separate
processes that share only the SQLite database. The dashboard never triggers
collection; `launchd` does. This keeps the always-on surface (the web server) free of
credentials and side effects.

## Data flow for one item

```
raw source object
  → Collector.normalize()  ──►  NormalizedItem (pydantic)
  → security.sanitize()    ──►  cleaned text + injection flags
  → classifiers.classify() ──►  category, priority, needs_response, spam?
  → dedupe.is_duplicate()  ──►  drop or keep (content hash + fuzzy)
  → retrieval.search()     ──►  top-k of YOUR past content (only if needs_response)
  → drafting.draft()       ──►  suggested_response + confidence + sources_used
  → db: upsert Item + Draft
```

Ollama runs first and cheaply on everything. The Claude API runs **only** on items
that pass classification as needing a response, and receives only the minimum context
(the sanitized item + retrieved snippets), never a raw dump of an inbox or community.

## Component map

| Package | Responsibility |
|---------|----------------|
| `app/collectors` | One module per source. `BaseCollector` handles cursors, health, retries. |
| `app/security` | Sanitization, secrets (Keychain), redaction, audit log. |
| `app/classifiers` | Ollama-backed category/priority/spam, plus dedup. |
| `app/retrieval` | LanceDB vector store, embeddings, historical ingest. |
| `app/drafting` | Claude API drafting, structured sales extraction, prompts. |
| `app/scheduler` | `run_cycle` orchestrator + file lock. |
| `app/dashboard` | FastAPI routes + static single-page UI. |
| `app/db` | SQLAlchemy models + session. |
| `app/models` | Shared pydantic contracts (`NormalizedItem`, etc.). |

## Why these technologies

- **Python** — the messaging, Google, Telegram, browser-automation, and AI ecosystems
  are all strongest here.
- **FastAPI + static JS** — the dashboard is a read model over SQLite; it does not
  need a heavy SPA build step. (A Next.js frontend is an easy later swap.)
- **SQLite** — single-file, zero-ops, encrypt-at-rest friendly. Upgrade path to
  Postgres via SQLAlchemy if you ever outgrow it.
- **LanceDB** — embedded vector store, no Docker needed, good on Apple Silicon.
- **Playwright** — only where an official API can't give read access (Skool, TikTok).
- **Ollama** — private, free first-pass filtering so cloud tokens are spent only where
  they add value.
- **Claude API (key, not subscription)** — an unattended job needs its own key, spend
  controls, rate limits, and a defined retention policy. A chat subscription is the
  wrong tool for a backend.

## Scheduling detail

`launchd` `StartInterval` of `2700` seconds (45 min). `run_cycle` acquires an
exclusive file lock (`data/.run.lock`); if a previous run is still going, the new one
exits immediately rather than double-collecting. Nightly and weekly jobs (index
refresh, backups, health report) are separate `launchd` entries — see
`implementation-plan.md`.
