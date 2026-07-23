# Implementation Plan

## Phase 1 — useful immediately (this repo)
Gmail, Calendar, Telegram, Skool, PeptidePrice sales extraction, local dashboard,
manual copy/paste drafts, historical Skool import, retrieval, Claude drafting,
45-minute scheduler, Ollama classification, security core.

**What's live in code here:** the full pipeline, DB, security, dashboard, drafting,
retrieval, classification, and the four Phase-1 collectors wired to their real
APIs/automation. What each collector still needs from you is in
`connector-support-matrix.md`, and the setup wizard walks you through it.

## Phase 2 — personal communications
Apple Messages (`chat.db` read-only), WhatsApp Web (Playwright), contact matching
across channels, cross-channel conversation summaries, meeting-request detection.

## Phase 3 — content intelligence
TikTok comments (Studio automation + notification emails), recurring-question
detection at scale, content recommendations, draft TikTok scripts, weekly community
report, vendor promotion calendar.

## Phase 4 — controlled actions (weeks after testing)
Create Gmail *drafts* (not sends), draft Skool replies inside the dashboard, propose
(not apply) calendar changes, queue posts for approval. **No fully autonomous posting**
for community, health, or vendor communication — ever, by policy.

## Scheduled jobs

| Cadence | Job | launchd file |
|---------|-----|--------------|
| Every 45 min | `app.scheduler.run_cycle` | `com.radar.assistant.plist` |
| Nightly | reconcile missed items, refresh indexes | `com.radar.nightly.plist` (Phase 2) |
| Weekly | encrypted DB backup + connector health report | `com.radar.weekly.plist` (Phase 2) |
| Monthly | review rejected drafts, update style examples | manual / Phase 3 |

## Build checklist for Phase 1

- [x] Design docs (this set)
- [x] DB models + schema
- [x] Shared `NormalizedItem` contract
- [x] Security: sanitize / redact / injection flags / Keychain / audit
- [x] `BaseCollector` (cursors, health, retry, rate limit)
- [x] Gmail, Calendar, Telegram, Skool collectors
- [x] Ollama classifier + dedup
- [x] LanceDB retrieval store + historical ingest
- [x] Claude drafter + structured sales extractor + prompts
- [x] `run_cycle` orchestrator + file lock + emergency stop
- [x] FastAPI dashboard with six tabs
- [x] launchd plist, setup wizard, init_db, run_once
- [x] Tests for sanitize / dedup / pipeline
- [ ] **You:** run setup wizard on your Mac, connect accounts, tune config
- [ ] **You:** run historical Skool import, verify selectors
- [ ] **You:** install launchd job

## Acceptance for Phase 1 (on your Mac)
1. `run_once.py` collects new Gmail/Calendar/Telegram/Skool items into SQLite.
2. Dashboard shows them in the right tabs with working source links.
3. At least one Skool question produces a copy-ready draft in your voice.
4. A vendor promo email is parsed into structured `sales` fields.
5. launchd fires the cycle every 45 min and you get one macOS notification.
6. Nothing is ever sent/posted/edited on any source.
