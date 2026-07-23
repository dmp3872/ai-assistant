"""Pull your real Skool data with your session token, find posts you haven't replied
to, import classroom content, and draft a comment for each — in your voice.

RUN THIS ON YOUR MAC. A cloud sandbox can't reach skool.com (network policy blocks it);
your Mac has no such block.

  # first time: store your Skool auth_token (from cookie-editor -> auth_token) in Keychain
  python scripts/skool_pull.py --token "<auth_token>" --save

  # thereafter (token read from Keychain):
  python scripts/skool_pull.py                      # list your communities + unanswered posts
  python scripts/skool_pull.py --group peptideprice # pick a community by slug
  python scripts/skool_pull.py --classroom          # also import all classroom lessons -> retrieval
  python scripts/skool_pull.py --draft              # generate a copy-ready comment per unanswered post

The token is a credential — it is stored in the macOS Keychain, never in the repo.
"""

from __future__ import annotations

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse

from app.collectors import skool_parse as sp
from app.collectors.skool import SkoolCollector
from app.models import NormalizedItem
from app.security import sanitize, set_secret


def _unanswered(collector, recs):
    posts = [r for r in recs if r["kind"] == "post"]
    comments = [r for r in recs if r["kind"] == "comment"]
    answered = {c["parent_id"] for c in comments if collector._is_me(c["author"], None)}
    return [p for p in posts
            if not collector._is_me(p["author"], None) and p["id"] not in answered]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", help="Skool auth_token (else read from Keychain)")
    ap.add_argument("--save", action="store_true", help="store --token in the Keychain")
    ap.add_argument("--group", help="community slug (else your first group)")
    ap.add_argument("--classroom", action="store_true", help="import classroom -> retrieval")
    ap.add_argument("--draft", action="store_true", help="generate a comment per unanswered post")
    ap.add_argument("--inspect", action="store_true",
                    help="print pagination diagnostics (buildId, cursor keys) and exit")
    ap.add_argument("--pages", type=int, default=None, help="max feed pages for deep pull")
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()

    if args.token and args.save:
        set_secret("skool_auth_token", args.token)
        print("✓ stored skool_auth_token in Keychain")

    collector = SkoolCollector()
    if args.token:
        collector.token = args.token
        collector.use_token = True
    if not collector.use_token:
        print("No Skool token. Pass --token '<auth_token>' (from cookie-editor).")
        return

    if not collector.health_check():
        print("Token did not authenticate. Re-export a fresh auth_token from Skool.")
        return

    groups = collector.discover_groups()
    print(f"\nCommunities on this token: {len(groups)}")
    for g in groups:
        print(f"   • {g['name']}  ({g['slug']})")

    if args.group:
        match = next((g for g in groups if g["slug"] == args.group), None)
        if match:
            collector.community_url = match["url"]
            collector.classroom_url = f"{match['url']}/classroom"
    url = collector._resolve_community_url()
    print(f"\nReading feed: {url}")

    if args.inspect:
        from app.collectors import skool_api
        info = skool_api.inspect_feed(url, collector.token)
        print("\nPagination diagnostics (use to confirm/override skool.feed_page_template):")
        for k, v in info.items():
            print(f"   {k}: {v}")
        print("\nIf candidate_page2_url returns JSON with more posts in your browser,")
        print("the default template works. If not, copy the real request from the")
        print("Network tab into config skool.feed_page_template.")
        return

    if args.pages is not None:
        collector.max_feed_pages = args.pages

    if args.classroom:
        from app.security import sanitize as _san
        from app.retrieval import ingest_skool
        lessons = collector.import_classroom()
        for it in lessons:
            it.body_clean, _ = _san(it.body or "")
        counts = ingest_skool(lessons)
        print(f"Classroom imported -> {counts}")

    recs = collector.deep_feed()  # all pages (token path)
    n_posts = len([r for r in recs if r["kind"] == "post"])

    # highest signal: anything that @-mentions you or replies on your own post
    mentions, replies = [], []
    seen: set = set()
    for r in recs:
        if r["id"] in seen:
            continue
        if collector._mentions_me(r):
            mentions.append(r); seen.add(r["id"])
        elif (r["kind"] == "comment" and collector._is_me(r.get("parent_author"), None)
              and not collector._is_me(r.get("author"), None)):
            replies.append(r); seen.add(r["id"])

    def _draft_for(rec):
        if not args.draft:
            return
        item = NormalizedItem(source="skool", source_id=rec["id"], author=rec["author"],
                              url=rec["url"], title=rec.get("title") or "Skool",
                              body=rec.get("body") or "", category="community",
                              needs_response=True)
        item.body_clean, _ = sanitize(item.body)
        from app.drafting import draft_response
        d = draft_response(item)
        if d:
            print("  ── DRAFT COMMENT (%s) ──\n  %s" %
                  (d["confidence"], d["draft_text"].replace("\n", "\n  ")))
        else:
            print("  (draft skipped — set ANTHROPIC_API_KEY / run setup_wizard)")

    print(f"\n@ MENTIONS & DIRECT TAGS: {len(mentions)}\n" + "=" * 48)
    for r in mentions:
        print(f"\n▸ {r['title']}\n  by {r['author']} · {r['url']}\n  {(r['body'] or '')[:200]}")
        _draft_for(r)

    print(f"\nNEW REPLIES ON YOUR POSTS: {len(replies)}\n" + "=" * 48)
    for r in replies:
        print(f"\n▸ {r['author']} replied · {r['url']}\n  {(r['body'] or '')[:200]}")
        _draft_for(r)

    unanswered = _unanswered(collector, recs)[: args.limit]
    print(f"\nScanned {n_posts} posts across all pages · "
          f"posts you haven't replied to: {len(unanswered)}\n" + "-" * 48)
    for p in unanswered:
        print(f"\n▸ {p['title']}\n  by {p['author']} · {p['url']}")
        print(f"  {(p['body'] or '')[:200]}")
        if args.draft:
            item = NormalizedItem(source="skool", source_id=p["id"], author=p["author"],
                                  url=p["url"], title=p["title"], body=p["body"] or "",
                                  category="community", needs_response=True)
            item.body_clean, _ = sanitize(item.body)
            from app.drafting import draft_response
            d = draft_response(item)
            if d:
                print(f"\n  ── DRAFT COMMENT ({d['confidence']}) ──\n  " +
                      d["draft_text"].replace("\n", "\n  "))
                if d.get("review_reason"):
                    print(f"  (review: {d['review_reason']})")
            else:
                print("  (draft skipped — set ANTHROPIC_API_KEY / run setup_wizard)")
    print("\nDone. Nothing was posted — copy any draft into Skool yourself.")


if __name__ == "__main__":
    main()
