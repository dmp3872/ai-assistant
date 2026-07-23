"""Doctor: report which credentials are configured, WITHOUT printing their values.

Run on your Mac after the setup wizard to confirm everything landed:
    python scripts/check_keys.py
"""
from __future__ import annotations

import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow `python scripts/x.py`

from app.security import get_secret
from app.settings import ROOT

def _checks():
    from app.settings import get_settings
    checks = [("anthropic_api_key", "Claude API (drafting)", "console.anthropic.com -> API Keys")]
    accounts = get_settings().connector("gmail").get("accounts") or [None]
    for a in accounts:
        key = "google_oauth_token_json" if not a else f"google_oauth_token_json:{a}"
        checks.append((key, f"Gmail: {a or 'default'}", "setup_wizard.py -> Google OAuth"))
    checks += [
        ("telegram_api_id", "Telegram api_id", "my.telegram.org"),
        ("telegram_api_hash", "Telegram api_hash", "my.telegram.org"),
        ("telegram_session", "Telegram login", "setup_wizard.py -> Telegram"),
        ("skool_auth_token", "Skool session", "cookie-editor -> auth_token"),
        ("tiktok_cookie", "TikTok (optional)", "cookie-editor -> if public fetch blocked"),
    ]
    return checks


def _mask(v: str) -> str:
    if len(v) <= 8:
        return "•" * len(v)
    return f"{v[:4]}…{v[-4:]} ({len(v)} chars)"


def _skool_token_info(tok: str) -> str:
    try:
        p = tok.split(".")[1]
        p += "=" * (-len(p) % 4)
        data = json.loads(base64.urlsafe_b64decode(p))
        exp = data.get("exp")
        if exp:
            when = datetime.fromtimestamp(exp, tz=timezone.utc).date()
            days = (datetime.fromtimestamp(exp, tz=timezone.utc) - datetime.now(timezone.utc)).days
            return f"expires {when} (in {days} days)"
    except Exception:
        pass
    return ""


def main() -> None:
    print("Radar credential check\n" + "=" * 40)
    missing = []
    for account, label, where in _checks():
        val = get_secret(account)
        if val:
            extra = f" · {_skool_token_info(val)}" if account == "skool_auth_token" else ""
            print(f"  ✓ {label:22} {_mask(val)}{extra}")
        else:
            missing.append((label, where))
            print(f"  ✗ {label:22} MISSING  ->  {where}")

    cfg = (ROOT / "config" / "config.yaml")
    print(f"\n  {'✓' if cfg.exists() else '✗'} config/config.yaml "
          f"{'present' if cfg.exists() else 'not created (copy config.example.yaml)'}")

    if missing:
        print(f"\n{len(missing)} credential(s) missing. Run: python scripts/setup_wizard.py")
    else:
        print("\nAll set. Try: python scripts/run_once.py")


if __name__ == "__main__":
    main()
