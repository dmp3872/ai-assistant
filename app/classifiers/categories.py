"""Category enum and category -> dashboard-tab mapping."""
from __future__ import annotations

from app.settings import get_settings

CATEGORIES = [
    "peptideprice_sales",
    "community",
    "vendor",
    "financial_legal",
    "personal",
    "calendar",
    "newsletter_spam",
    "no_action",
]

PRIORITIES = ["urgent", "today", "fyi"]


def tab_for_category(category: str | None) -> str:
    tabs = (get_settings().config.get("classification", {}) or {}).get("tabs", {})
    return tabs.get(category or "no_action", "hidden")
