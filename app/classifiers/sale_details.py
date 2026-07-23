"""Deterministic extraction of promo fields (discount, code, free-shipping, END DATE)
straight from the email text. The end date is resolved to an ABSOLUTE calendar date
against the email's sent date (item.created_at), so "ends tonight" becomes the real day.

Runs with no API key, so the Sales tab populates on first run. The Claude extractor
(drafting/sales_extractor.py) can still enrich this, but dates come from here.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from app.classifiers import vendors
from app.classifiers.dateresolve import resolve_end_date, find_tz
from app.models import NormalizedItem

_CODE = re.compile(r"(?:use\s+code|with\s+(?:your\s+)?code|coupon\s*(?:code)?|promo\s*code|code)"
                   r"[:\s]+([A-Z0-9]{3,20})\b")
_FREESHIP = re.compile(r"free\s+shipping(?:\s+(?:over|on orders over|above)\s*\$?(\d+))?", re.I)


def _discount(text: str) -> str | None:
    low = text.lower()
    m = re.search(r"buy\s*(\d)\s*get\s*(\d)\s*free", low)
    if m:
        return f"Buy {m.group(1)} Get {m.group(2)} Free"
    if re.search(r"\bb(\d)g(\d)\b", low):
        m = re.search(r"\bb(\d)g(\d)\b", low)
        return f"Buy {m.group(1)} Get {m.group(2)} Free"
    m = re.search(r"(?:flat\s*)?(\d{1,2})\s*%\s*off", low) or re.search(r"(\d{1,2})\s*%", low)
    if m:
        return f"{m.group(1)}% off"
    save_m = re.search(r"\bsave\s+\$?(\d+)", low)
    if save_m:
        return f"Save ${save_m.group(1)}"
    return None


def extract(item: NormalizedItem) -> dict:
    text = f"{item.title or ''}\n{item.body_clean or item.body or ''}"
    reference = item.created_at or datetime.now(timezone.utc)

    vendor = vendors.match(handle=item.author_handle, author=item.author,
                           subject=item.title, snippet=item.body_clean or item.body)
    code_m = _CODE.search(text)
    ship_m = _FREESHIP.search(text)
    end = resolve_end_date(text, reference, tz_hint=find_tz(text))

    return {
        "vendor": vendor or item.author,
        "promo_name": (item.title or "").strip() or None,
        "discount": _discount(text),
        "coupon_code": code_m.group(1) if code_m else None,
        "free_shipping_threshold": (f"over ${ship_m.group(1)}" if ship_m and ship_m.group(1)
                                    else ("yes" if ship_m else None)),
        "end_date": end["label"] if end else None,     # absolute, e.g. "Jul 21"
        "end_tz": end["tz"] if end else None,
        "end_iso": end["iso"] if end else None,         # sortable YYYY-MM-DD
        "confidence": "high" if (end or code_m) else "medium",
    }
