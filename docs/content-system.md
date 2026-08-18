# The Content System (Studio)

Radar's reply drafter answers questions **as they arrive**. The content system is the
other half: it makes sure you always have *something to reply with* and *something to
post*, so running the Research Radar community never depends on you having a spare hour
to write. It's the "content backlog engine" — a stocked shelf that refills itself.

Like everything in Radar it is **read-only to the outside world**. It generates and
queues; it never posts, DMs, or edits anything on Skool or any channel. You copy and
post. That boundary is not negotiable — see [`threat-model.md`](threat-model.md).

---

## Two products, one engine

### 1. Answer Bank — always have a reply
Recurring questions are the highest-leverage content you own: answer once, reuse forever.

- **Cluster** — `app/content/opportunities.py` scans your Skool community questions and
  groups paraphrases of the same question together (greedy Jaccard overlap on significant
  tokens — no embeddings/Ollama needed, so it's deterministic and testable). Each cluster
  is a `ContentOpportunity` row with an occurrence count.
- **Answer** — for each open opportunity without an answer, `generator.generate_answer()`
  drafts one canonical, reusable answer in your voice, grounded in your public content.
  It's stored as a `ContentPiece(kind="answer")` and linked back to the opportunity.

### 2. Post Queue — always have something to post
- `generator.generate_post()` drafts a copy-ready post for a channel, grounded in your
  content around a **seed topic**. Seeds come from (in priority order): open recurring
  questions → your configured evergreen `seed_topics` → your classroom material.
- `engine._replenish_posts()` tops each channel up to its target depth, skipping any
  topic already on the shelf (dedup key = `channel:post:<topic-signature>`).

All pieces are stored in the `content_pieces` table and move through a simple workflow:

```
queued ─▶ approved ─▶ posted      (posted stamps posted_at + saves what you actually posted)
   └────────────────▶ discarded
```

Only **you** move a piece — from the **Studio** tab or the **Plan** tab.

---

## The cycle hook

`app/scheduler/run_cycle.py` calls `content.engine.replenish()` at the end of every
collection cycle, fully guarded (a generation hiccup never fails the collection run).
`replenish()`:

1. Re-clusters questions (`refresh_opportunities`).
2. Computes which channels are **below** target and whether any opportunity still needs
   an answer. **If nothing is below target and every question is answered, it returns
   `{"status": "full"}` and spends zero API calls.**
3. Otherwise drafts up to `max_answers_per_cycle` answers and `max_posts_per_cycle`
   posts. The shelf fills over a few cycles rather than all at once.

Because generation degrades to `None` without an Anthropic key (and posts refuse to
generate without grounding content), the engine is safe to leave on before you've
finished setup — it simply produces nothing until it can.

---

## Configuration (`config/config.yaml` → `content:`)

```yaml
content:
  enabled: true
  queue_targets: { skool: 10, tiktok: 6, substack: 3, youtube: 1 }
  max_posts_per_cycle: 5          # per-cycle spend caps
  max_answers_per_cycle: 3
  min_question_occurrences: 1     # 1 = every distinct question gets a ready answer
  seed_topics: []                 # optional evergreen topics to guarantee posts early
```

- **Want a bigger backlog?** Raise `queue_targets`.
- **Watching spend?** Lower the per-cycle caps; the shelf just fills more gradually.
- **Only want *repeated* questions in the Answer Bank?** Set `min_question_occurrences: 2`.

---

## Using it

**Studio tab**
- Header shows queue depth per channel; buttons generate on demand (with an optional
  topic seed) or "Top up all".
- **Post queue** grouped by channel and **Answer bank** below it — each card is editable;
  Copy / Posted / Discard.
- **Recurring questions (no answer yet)** — "Draft answer" turns one into a bank entry.

**Plan tab**
- Each Skool/TikTok/etc. quota slot is now backed by a real queued draft: 📝 title +
  Copy / Posted, so the daily quota is concrete work, not a blank "write a post".

**Marking Posted** saves the exact text you posted (`edited_text`) — the same signal the
reply drafter already uses to learn your voice over time.

---

## Where it lives

| File | Role |
|------|------|
| `app/content/opportunities.py` | Cluster community questions → `ContentOpportunity` |
| `app/content/generator.py` | Claude-backed post/answer generation (graceful degrade) |
| `app/content/prompts.py` | Voice + safety prompt builders (untrusted content fenced) |
| `app/content/queue.py` | `content_pieces` CRUD, depth accounting, pull-for-day |
| `app/content/engine.py` | `replenish()` orchestrator (targets, caps, no-op-when-full) |
| `app/db/models.py` | `ContentPiece` + extended `ContentOpportunity` |
| `app/dashboard/routes.py` | `/content/*` API |
| `tests/test_content.py` | Clustering, queue, replenish (generation stubbed) |

## Safety notes

- Post/answer generation retrieves through `search_public()` **only** — the same control
  that stops a community reply from leaking personal or financial context.
- The seed for a post and any member question are wrapped with `wrap_untrusted()` and
  treated as data; instructions inside them are ignored, never executed.
- Nothing here contacts a source to write. The only writes are to our own SQLite.
