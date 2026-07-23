# Database Schema

SQLite (single file at `data/radar.db`). SQLAlchemy models in `app/db/models.py` are
the source of truth; this doc explains intent. Upgrade path to Postgres is a
connection-string change. For encryption at rest, either keep the DB on a FileVault /
encrypted APFS volume or swap the driver for SQLCipher (`pysqlcipher3`).

## Tables

### `connectors`
Per-source cursor and health.
| column | type | notes |
|--------|------|-------|
| id | int pk | |
| name | text unique | gmail, calendar, telegram, skool, ... |
| cursor | text | opaque: Gmail historyId, Calendar syncToken, Telegram msg id, Skool timestamp |
| last_run_at | datetime | |
| last_success_at | datetime | |
| status | text | ok / degraded / error |
| last_error | text | |
| enabled | bool | |

### `items`
One row per normalized unit of activity from any source.
| column | type | notes |
|--------|------|-------|
| id | int pk | |
| source | text | connector name |
| source_id | text | native id (message id, comment id, event id) |
| thread_id | text | conversation/thread grouping, nullable |
| author | text | display name / from |
| author_handle | text | email / username, nullable |
| url | text | **direct link** back to the source item |
| created_at | datetime | when the source item was created |
| collected_at | datetime | when we ingested it |
| title | text | subject / short title, nullable |
| body_clean | text | sanitized, HTML-stripped, redacted text |
| body_hash | text | sha256 of normalized body for dedup |
| category | text | see categories below |
| priority | text | urgent / today / fyi |
| needs_response | bool | |
| injection_flag | bool | sanitizer detected an instruction-like payload |
| spam | bool | |
| handled | bool | user marked handled |
| snoozed_until | datetime | nullable |
| raw_json | text | original normalized payload (audit) |

Unique on `(source, source_id)` — the dedup + incremental guarantee.

### `drafts`
AI-suggested response for an item.
| column | type | notes |
|--------|------|-------|
| id | int pk | |
| item_id | int fk → items | |
| draft_text | text | copy-ready suggested response |
| confidence | text | high / medium / low |
| review_reason | text | why a human should check (e.g. "avoid implying authenticity") |
| sources_used | text (json) | retrieval hits that informed the draft |
| model | text | e.g. claude-opus-4-8 |
| created_at | datetime | |

### `sales`
Structured extraction for the PeptidePrice Sales tab.
| column | type | notes |
|--------|------|-------|
| id | int pk | |
| item_id | int fk → items | source email/message |
| vendor | text | |
| promo_name | text | |
| discount | text | |
| stacking_rules | text | |
| coupon_code | text | |
| start_date | date | nullable |
| end_date | datetime | with timezone note |
| end_tz | text | |
| exclusions | text | |
| free_shipping_threshold | text | |
| giveaway | text | |
| confidence | text | |
| contradicts_sale_id | int | nullable fk → sales (e.g. "earlier said ends 25th, now 27th") |

### `content_opportunities`
Recurring-question clusters for the Content Opportunities tab.
| column | type | notes |
|--------|------|-------|
| id | int pk | |
| question | text | canonical phrasing |
| occurrences | int | count this week |
| sources | text (json) | ["skool","tiktok","telegram"] |
| suggested_format | text | e.g. "TikTok + Skool post" |
| related_content | text (json) | existing posts that cover it |
| outline | text | suggested outline |
| first_seen | datetime | |
| last_seen | datetime | |

### `review_history`
How the assistant learns your voice.
| column | type | notes |
|--------|------|-------|
| id | int pk | |
| item_id | int fk → items | |
| draft_id | int fk → drafts | the AI suggestion |
| final_text | text | what you actually posted (paste-back) |
| edit_distance | int | rough measure of how much you changed |
| rejected | bool | you threw the draft away |
| feedback | text | free-text correction ("stop opening with 'Great question'") |
| created_at | datetime | |

Approved/edited responses here are re-embedded into the retrieval store as
style examples, closing the learning loop.

### `audit_log`
(Also mirrored to `logs/audit-*.jsonl`.)
| column | type | notes |
|--------|------|-------|
| id | int pk | |
| ts | datetime | |
| kind | text | collect / classify / draft / model_call / error / action |
| source | text | |
| detail | text (json) | |

## Categories (enum, see `app/classifiers/categories.py`)
`peptideprice_sales`, `community`, `vendor`, `financial_legal`, `personal`,
`newsletter_spam`, `no_action`, `calendar`.

## Retrieval namespaces (LanceDB, separate from SQLite)
`skool_posts`, `skool_comments`, `courses`, `tiktok_transcripts`,
`approved_email_responses`, `vendor_policies`, `disclaimers`, `peptideprice_ops`,
`personal_business` *(never used to draft public replies)*, `rejected_answers`.
