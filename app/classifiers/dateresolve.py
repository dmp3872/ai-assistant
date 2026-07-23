"""Resolve relative date phrases against the date an email was SENT, not "now".

A promo email sent on Jul 21 that says "ends tonight MST" ends on **Jul 21**. Read a
week later, "tonight" must not drift to the current day. Everything here anchors to a
reference datetime (the email's sent date) so stored/displayed end dates are absolute.

resolve_end_date("sale ends Sunday MST", reference=<Jul 19>) ->
    {"iso": "2026-07-19"... no: Sunday after Jul 19(Sat) = Jul 20}
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

_WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
             "friday": 4, "saturday": 5, "sunday": 6}
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}
_MONTH_ABBR = {m[:3]: i + 1 for m, i in ((k, v - 1) for k, v in _MONTHS.items())}

_TZ = re.compile(r"\b(PST|PDT|PT|MST|MDT|MT|CST|CDT|CT|EST|EDT|ET|UTC|GMT)\b")


def _label(d) -> str:
    return f"{d.strftime('%b')} {d.day}"  # "Jul 21" (portable, no %-d)


def find_tz(text: str) -> str | None:
    m = _TZ.search(text or "")
    return m.group(1) if m else None


def resolve_end_date(text: str, reference: datetime, tz_hint: str | None = None) -> dict | None:
    """Return {iso, label, tz, display} for the sale end date, or None if no end
    phrase is found. `reference` is the email's sent datetime (tz-aware)."""
    if not text:
        return None
    low = text.lower()
    ref = reference.date()
    tz = tz_hint or find_tz(text)
    end = None

    # 1) absolute "Month Day" (through/until/ends Jul 27, or bare "July 27")
    m = re.search(
        r"(?:through|thru|until|ends?|ending|expires?|valid\s+through)\s+(?:on\s+)?"
        r"([a-z]{3,9})\.?\s+(\d{1,2})", low)
    if not m:
        m = re.search(r"\b([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b", low)
    if m:
        mon = _MONTHS.get(m.group(1)) or _MONTH_ABBR.get(m.group(1)[:3])
        if mon:
            day = int(m.group(2))
            try:
                cand = datetime(ref.year, mon, day).date()
                if (ref - cand).days > 180:  # date already well past -> next year
                    cand = cand.replace(year=ref.year + 1)
                end = cand
            except ValueError:
                end = None

    # 2) "in N hours" / "N-hour" / "48 hours"
    if end is None:
        m = re.search(r"(?:in\s+)?(\d{1,3})\s*[- ]?\s*hours?", low)
        if m:
            end = (reference + timedelta(hours=int(m.group(1)))).date()

    # 3) tonight / today / final hours / ends at midnight -> the send date
    if end is None and re.search(
            r"\b(tonight|today|final hours?|last call|ends? at midnight|midnight tonight|"
            r"ends? (?:soon|now)|closes today)\b", low):
        end = ref

    # 4) tomorrow
    if end is None and "tomorrow" in low:
        end = ref + timedelta(days=1)

    # 5) "this weekend" -> upcoming Sunday
    if end is None and "weekend" in low:
        end = ref + timedelta(days=(6 - ref.weekday()) % 7)

    # 6) weekday name -> next occurrence on/after the send date
    if end is None:
        for name, wd in _WEEKDAYS.items():
            if re.search(rf"\b(?:ends?|through|until|by)?\s*{name}\b", low):
                end = ref + timedelta(days=(wd - ref.weekday()) % 7)
                break

    if end is None:
        return None
    disp = _label(end)
    if tz:
        disp = f"{disp}, 11:59pm {tz}"
    return {"iso": end.isoformat(), "label": _label(end), "tz": tz, "display": disp}
