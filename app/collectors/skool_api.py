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


def get_json(url: str, token: str | None = None) -> dict:
    """Authenticated GET of a JSON endpoint (e.g. Skool's _next/data feed pages)."""
    token = token or get_secret("skool_auth_token", required=True)
    with _client(token) as c:
        r = c.get(url, headers={"Accept": "application/json"})
        r.raise_for_status()
        return r.json()


def discover_groups(token: str | None = None) -> list[dict]:
    """Return the communities this token belongs to: [{name, slug, url}]."""
    from app.collectors.skool_parse import parse_groups

    return parse_groups(get_html("https://www.skool.com/", token))


# Default Next.js data-endpoint template for deep feed history. Skool gives no public
# API, so the exact cursor/param names vary per community — confirm yours once with
# `scripts/skool_pull.py --inspect` and override skool.feed_page_template in config.
DEFAULT_FEED_TEMPLATE = "{origin}/_next/data/{buildId}/{slug}.json?group={slug}&p={page}"


def paginate_feed(group_url: str, token: str | None = None, *, template: str | None = None,
                  max_pages: int = 20, pace_s: float = 0.0) -> list[dict]:
    """Deep feed pull: page 1 from SSR HTML, then follow the data endpoint until it
    runs dry (no fresh posts / has_next False) or max_pages. Dedups by post id.

    Returns the same record shape as parse_feed. If no buildId/template is available,
    gracefully returns just the first page rather than failing.
    """
    import time
    from app.collectors import skool_parse as sp

    token = token or get_secret("skool_auth_token", required=True)
    origin = "https://www.skool.com"
    slug = group_url.rstrip("/").split("/")[-1]
    template = template or DEFAULT_FEED_TEMPLATE

    html = get_html(group_url, token)
    records = sp.parse_feed(html, group_url)
    seen = {r["id"] for r in records}
    build_id = sp.extract_build_id(html)
    cursor = sp.extract_page_cursor(html).get("cursor")

    if not build_id:
        return records  # can't build data URLs without the Next.js buildId

    page = 2
    while page <= max_pages:
        url = template.format(origin=origin, buildId=build_id, slug=slug, page=page,
                              cursor=cursor if cursor is not None else "")
        try:
            data = get_json(url, token)
        except Exception:
            break  # endpoint shape differs for this community -> stop cleanly
        recs = sp.feed_records_from_data(data, group_url)
        fresh = [r for r in recs if r["id"] not in seen]
        if not fresh:
            break  # dry
        for r in fresh:
            seen.add(r["id"])
        records.extend(fresh)
        hint = sp.extract_page_cursor(data)
        cursor = hint.get("cursor")
        if hint.get("has_next") is False:
            break
        page += 1
        if pace_s:
            time.sleep(pace_s)
    return records


def inspect_feed(group_url: str, token: str | None = None) -> dict:
    """Diagnostics for tuning pagination against a real community: buildId, the
    pagination keys present in the SSR data, and the candidate first data URL."""
    from app.collectors import skool_parse as sp

    html = get_html(group_url, token)
    build_id = sp.extract_build_id(html)
    hint = sp.extract_page_cursor(html)
    slug = group_url.rstrip("/").split("/")[-1]
    candidate = DEFAULT_FEED_TEMPLATE.format(origin="https://www.skool.com",
                                             buildId=build_id or "<buildId>", slug=slug,
                                             page=2, cursor=hint.get("cursor") or "")
    return {"build_id": build_id, "pagination_keys_seen": hint["keys_seen"],
            "cursor_value": hint.get("cursor"), "has_next": hint.get("has_next"),
            "candidate_page2_url": candidate, "first_page_posts":
            len([r for r in sp.parse_feed(html, group_url) if r["kind"] == "post"])}
