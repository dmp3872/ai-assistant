"""Authenticated HTTP access to Skool using your session token — no browser needed.

Skool serves reads via Next.js SSR, so a plain authenticated GET returns the page with
all data embedded in __NEXT_DATA__, which app.collectors.skool_parse already parses.
That makes this far lighter and more robust than driving a real browser.

The token is your Skool `auth_token` cookie (a JWT). Export it once with a cookie tool
(e.g. cookie-editor) and store it via the setup wizard — it lives in the macOS
Keychain, never in the repo. Token guidance:
  * It is a credential. Treat it like a password.
  * Skool's WAF can rotate/expire cookies; if requests start 401'ing, re-export it.
  * All requests here are READ-ONLY GETs, paced gently.
"""
from __future__ import annotations

import httpx

from app.security import get_secret

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def have_token() -> bool:
    return bool(get_secret("skool_auth_token"))


def _client(token: str) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": _UA, "Accept": "text/html,application/xhtml+xml",
                 "Accept-Language": "en-US,en;q=0.9"},
        cookies={"auth_token": token},
        follow_redirects=True, timeout=30,
    )


def get_html(url: str, token: str | None = None) -> str:
    """Authenticated GET returning page HTML (with __NEXT_DATA__). Read-only."""
    token = token or get_secret("skool_auth_token", required=True)
    with _client(token) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.text


def check_auth(token: str | None = None) -> bool:
    """True if the token authenticates (home page loads and isn't the logged-out page)."""
    try:
        html = get_html("https://www.skool.com/", token)
        # logged-in SSR embeds the user id; logged-out redirects to a marketing page
        return "__NEXT_DATA__" in html and ("user_id" in html or "\"user\"" in html)
    except Exception:
        return False


def discover_groups(token: str | None = None) -> list[dict]:
    """Return the communities this token belongs to: [{name, slug, url}]."""
    from app.collectors.skool_parse import parse_groups

    return parse_groups(get_html("https://www.skool.com/", token))
