"""Interactive setup wizard (run on your Mac).

Stores secrets in the macOS Keychain, runs Google OAuth, logs into Telegram, and can
kick off the one-time Skool historical import. It never prints secrets and never writes
them to disk. Safe to re-run; it only prompts for what's missing.
"""
from __future__ import annotations

import json
import sys
from getpass import getpass

from app.db import init_db
from app.security import get_secret, set_secret

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]


def _prompt_secret(account: str, label: str, hidden: bool = True) -> None:
    if get_secret(account):
        print(f"  ✓ {label} already stored.")
        return
    val = getpass(f"  Enter {label}: ") if hidden else input(f"  Enter {label}: ")
    if val.strip():
        set_secret(account, val.strip())
        print(f"  ✓ stored {label} in Keychain.")


def setup_anthropic() -> None:
    print("\n[1/4] Claude API key (drafting brain)")
    _prompt_secret("anthropic_api_key", "Anthropic API key")


def setup_google() -> None:
    print("\n[2/4] Google (Gmail + Calendar, read-only)")
    if get_secret("google_oauth_token_json"):
        print("  ✓ Google already authorized.")
        return
    print("  Paste the contents of your OAuth *desktop client* credentials.json.")
    print("  (Google Cloud Console → APIs & Services → Credentials → OAuth client → Desktop)")
    raw = input("  credentials.json contents: ").strip()
    if not raw:
        print("  skipped.")
        return
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("  google-auth-oauthlib not installed; run pip install -r requirements.txt")
        return
    flow = InstalledAppFlow.from_client_config(json.loads(raw), GOOGLE_SCOPES)
    creds = flow.run_local_server(port=0)  # opens your browser for consent
    set_secret("google_oauth_client_json", raw)
    set_secret("google_oauth_token_json", creds.to_json())
    print("  ✓ Google authorized and token stored in Keychain.")


def setup_telegram() -> None:
    print("\n[3/4] Telegram (your user account, read-only)")
    if get_secret("telegram_session"):
        print("  ✓ Telegram already logged in.")
        return
    _prompt_secret("telegram_api_id", "Telegram api_id (from my.telegram.org)", hidden=False)
    _prompt_secret("telegram_api_hash", "Telegram api_hash")
    api_id = get_secret("telegram_api_id")
    api_hash = get_secret("telegram_api_hash")
    if not (api_id and api_hash):
        print("  skipped.")
        return
    try:
        from telethon.sync import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        print("  telethon not installed; run pip install -r requirements.txt")
        return
    with TelegramClient(StringSession(), int(api_id), api_hash) as client:
        client.start()  # prompts for phone + login code interactively
        set_secret("telegram_session", client.session.save())
    print("  ✓ Telegram session stored in Keychain.")


def setup_skool() -> None:
    print("\n[4/4] Skool import — feed history + classroom (optional, one-time)")
    print("  Tip: set skool.author_name in config so your posts/comments route into")
    print("  your voice namespaces. Run `python scripts/import_skool.py --debug` first")
    print("  to eyeball that authorship + fields parsed correctly.")
    ans = input("  Run the full Skool import now? [y/N]: ").strip().lower()
    if ans != "y":
        print("  skipped — run `python scripts/import_skool.py` anytime.")
        return
    try:
        from app.collectors.skool import SkoolCollector
        from app.retrieval import ingest_skool
        from app.security import sanitize

        items = SkoolCollector().historical_import()
        for it in items:
            it.body_clean, _ = sanitize(it.body or "")
        counts = ingest_skool(items)
        print(f"  ✓ imported {len(items)} items -> chunks {counts}")
    except Exception as exc:
        print(f"  ! Skool import failed (verify config/profile): {exc}")


def main() -> None:
    print("Radar Assistant — setup wizard")
    init_db()
    setup_anthropic()
    setup_google()
    setup_telegram()
    setup_skool()
    print("\nDone. Next: `python scripts/run_once.py` then `uvicorn app.main:app --port 4317`.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
