"""Vendor allowlist + matcher. Sales are surfaced ONLY for these companies.

Loads config/vendors.yaml. match(item) returns the canonical vendor name if the
email's sender domain or author/subject text matches an allowlisted vendor, else None.
Domain match wins (most reliable); name/alias text match is the fallback.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent.parent.parent
_VENDORS_YAML = _ROOT / "config" / "vendors.yaml"


@lru_cache(maxsize=1)
def _load() -> list[dict]:
    if not _VENDORS_YAML.exists():
        return []
    data = yaml.safe_load(_VENDORS_YAML.read_text()) or {}
    out = []
    for v in data.get("vendors", []):
        name = v["name"]
        aliases = [name] + list(v.get("aliases", []) or [])
        domains = [d.lower() for d in (v.get("domains", []) or [])]
        # word-boundary regexes for name/alias text matching
        patterns = [re.compile(rf"\b{re.escape(a)}\b", re.I) for a in aliases]
        out.append({"name": name, "domains": domains, "patterns": patterns,
                    "hidden": bool(v.get("hidden", False))})
    return out


def vendor_names() -> list[str]:
    return [v["name"] for v in _load()]


def _domain_of(handle: str | None) -> str:
    if not handle:
        return ""
    handle = handle.lower()
    return handle.split("@")[-1] if "@" in handle else handle


def match(*, handle: str | None = None, author: str | None = None,
          subject: str | None = None, snippet: str | None = None) -> str | None:
    """Return the canonical vendor name if this email is from/about an allowlisted
    vendor, else None. Domain match first, then name/alias text match."""
    dom = _domain_of(handle)
    vendors = _load()
    if dom:
        for v in vendors:
            for vd in v["domains"]:
                # vd may be a full address (felixchemllc@gmail.com) or a domain
                if vd == (handle or "").lower() or (("@" not in vd) and dom.endswith(vd)):
                    return v["name"]
    text = " ".join(filter(None, [author, subject, snippet]))
    if text:
        for v in vendors:
            if any(p.search(text) for p in v["patterns"]):
                return v["name"]
    return None
