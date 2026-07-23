"""Relative phrases resolve against the email's SEND date, not 'now'."""
from datetime import datetime, timezone

from app.classifiers.dateresolve import resolve_end_date
from app.classifiers.sale_details import extract
from app.models import NormalizedItem

# real send dates from the inbox
JUL19 = datetime(2026, 7, 19, 12, 38, tzinfo=timezone.utc)  # a Sunday
JUL21 = datetime(2026, 7, 21, 3, 29, tzinfo=timezone.utc)   # a Tuesday
JUL23 = datetime(2026, 7, 23, 4, 9, tzinfo=timezone.utc)    # a Thursday


def test_tonight_anchors_to_send_date():
    r = resolve_end_date("extend the sale until tonight midnight MST", JUL19)
    assert r["iso"] == "2026-07-19"
    assert r["label"] == "Jul 19"
    assert r["tz"] == "MST"
    assert "Jul 19" in r["display"] and "MST" in r["display"]


def test_tonight_from_a_different_day():
    # same phrase, sent two days later -> different absolute date
    assert resolve_end_date("ends tonight", JUL21)["iso"] == "2026-07-21"


def test_weekday_next_occurrence():
    # "through Sunday" sent Tue Jul 21 -> Sun Jul 26
    assert resolve_end_date("live now through Sunday, July 26", JUL21)["iso"] == "2026-07-26"
    # bare weekday sent Sunday resolves to that same Sunday
    assert resolve_end_date("ends Sunday", JUL19)["iso"] == "2026-07-19"


def test_absolute_month_day():
    r = resolve_end_date("49% off through July 31", JUL23)
    assert r["iso"] == "2026-07-31" and r["label"] == "Jul 31"


def test_month_day_rolls_to_next_year_when_past():
    # sent late Dec, "ends Jan 3" -> next year
    dec = datetime(2026, 12, 28, tzinfo=timezone.utc)
    assert resolve_end_date("sale ends January 3", dec)["iso"] == "2027-01-03"


def test_in_n_hours():
    assert resolve_end_date("48 hours. then prices go back up", JUL19)["iso"] == "2026-07-21"


def test_no_phrase_returns_none():
    assert resolve_end_date("just a normal newsletter", JUL23) is None


def test_extract_resolves_against_created_at():
    it = NormalizedItem(source="gmail", source_id="p1", author_handle="affiliates@peptira.com",
                        title="45% off sale EXTENDED",
                        body="35% Sitewide plus 10% with your code. Extended until tonight midnight MST!")
    it.body_clean = it.body
    it.created_at = JUL19
    d = extract(it)
    assert d["vendor"] == "Peptira"
    assert d["discount"] == "45% off" or d["discount"] == "35% off"  # first % match
    assert d["end_date"] == "Jul 19"
    assert d["end_tz"] == "MST"
    assert d["end_iso"] == "2026-07-19"


def test_extract_pulls_code_and_bogo():
    it = NormalizedItem(source="gmail", source_id="i1", author_handle="support@instantpeptides.com",
                        title="Buy 3 Get 1 Free is live",
                        body="Buy 3 Get 1 Free live now through Sunday, July 26. Share your code PEPTIDEPRICE")
    it.body_clean = it.body
    it.created_at = JUL21
    d = extract(it)
    assert d["discount"] == "Buy 3 Get 1 Free"
    assert d["coupon_code"] == "PEPTIDEPRICE"
    assert d["end_iso"] == "2026-07-26"
