"""Launch the standalone Video Clipper app and open it in your browser.

    python scripts/clipper.py            # opens http://localhost:4318
    python scripts/clipper.py --port 5000
    CLIPPER_OUT=~/Movies/clips python scripts/clipper.py   # choose the output folder

Then just drag a video onto the page. That's it — no accounts, no other features.

Needs on this machine: ffmpeg (`brew install ffmpeg`) and a Whisper backend
(`pip install faster-whisper`). Without them the page still shows the clip plan and tells
you what to install.
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import threading
import time
import webbrowser


def main() -> None:
    ap = argparse.ArgumentParser(description="Standalone Video Clipper web app.")
    ap.add_argument("--port", type=int, default=4318)
    ap.add_argument("--no-open", action="store_true", help="don't auto-open the browser")
    args = ap.parse_args()

    import uvicorn
    from app.video import jobs

    url = f"http://localhost:{args.port}"
    print(f"\n  🎬  Video Clipper  →  {url}")
    print(f"      clips are saved to: {jobs.OUT_DIR}")
    print("      (drag a video onto the page · Ctrl+C to stop)\n")

    if not args.no_open:
        threading.Thread(
            target=lambda: (time.sleep(1.3), webbrowser.open(url)), daemon=True).start()

    uvicorn.run("app.video.webapp:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
