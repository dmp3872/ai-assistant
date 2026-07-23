"""Run a single collection cycle by hand (what launchd runs every 45 min).

    python scripts/run_once.py             # all enabled connectors
    python scripts/run_once.py --only skool  # just one, for selector debugging
"""

from __future__ import annotations

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import json

from app.scheduler.run_cycle import run_cycle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="run a single connector by name", default=None)
    args = parser.parse_args()

    if args.only:
        # Debug path: run one collector and print normalized items without persisting.
        from app.collectors import _import
        from app.settings import get_settings

        get_settings()  # ensure config loaded
        cls_map = {
            "gmail": "GmailCollector", "calendar": "CalendarCollector",
            "telegram": "TelegramCollector", "skool": "SkoolCollector",
        }
        collector = _import(args.only, cls_map[args.only])()
        items = collector.run()
        print(f"{len(items)} items from {args.only}:")
        for it in items[:10]:
            print(f"  - {it.created_at} | {it.author} | {(it.title or '')[:60]}")
        return

    print(json.dumps(run_cycle(), indent=2))


if __name__ == "__main__":
    main()
