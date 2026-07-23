"""Deterministic Gmail routing: decide what's a NEW SALE, what's noise, and split
real correspondence into work vs personal.

The Sales feed must contain ONLY new sales going live from allowlisted vendors — never
cart nudges, commission/referral notices, order/shipping confirmations, review requests,
or non-vendor marketing. This module encodes those rules so the result is predictable
and unit-tested (Ollama still handles the fuzzy stuff for non-Gmail sources).
"""
from __future__ import annotations

import re

from app.classifiers import vendors
from app.models import NormalizedItem

# --- a new sale going live ---
_SALE = re.compile(
    r"\b(\d{1,2}\s*%|% off|percent off|sale|discount|coupon|promo code|"
    r"\bcode\b|bogo|buy\s*\d\s*get\s*\d?|flash|save\s*\$?\d+|deal|now live|is live|"
    r"goes live|sitewide|site-wide|extended|final hours|ends tonight|last call|"
    r"launch|new releases?|new drops?|drops? to|build-a-kit|giveaway|crypto)\b", re.I)

# bulk-marketing sender shape (used only for NON-allowlisted senders)
_BULK_SENDER = re.compile(
    r"^(no-?reply|notifications?|news|hello|info|email|mailer|marketing|promo|deals|"
    r"offers|insiderdeals)@|@(em|e|send|mail|email|news|hello|marketing|mkt)\.", re.I)

# --- affiliate income / referral notices (NOT a sale to post) ---
_COMMISSION = re.compile(
    r"\b(referral sale|new referral|commission earned|unpaid commission|"
    r"new order from your referral|helped .* make a sale|made a sale|"
    r"referral order|order total|you earned|commission\b)\b", re.I)

# --- cart / browse / transactional / review noise ---
_NOISE = re.compile(
    r"\b(cart|misses you|second look|catch your eye|still got items|"
    r"thanks for visiting|abandoned|order completed|order confirmation|"
    r"has shipped|shipping confirmation|tracking (number|code)|"
    r"leave (your |a )?review|review our|rate your|your order is)\b", re.I)

# --- work / personal correspondence signals ---
_WORK = re.compile(
    r"\b(affiliate|partner|commission|invoice|accountant|tax|contract|vendor|"
    r"wholesale|payout|w-?9|1099|zoom recap|referral|order|shipment|"
    r"peptideprice|content hook|weekly recap|business)\b", re.I)
_PERSONAL = re.compile(
    r"\b(reacted to your profile|match|liked you|birthday|family|dinner|"
    r"friend|your ride|reservation|appointment reminder)\b", re.I)


def _text(item: NormalizedItem) -> str:
    return f"{item.title or ''} {item.body_clean or item.body or ''}"


def is_new_sale(text: str) -> bool:
    return bool(_SALE.search(text)) and not _COMMISSION.search(text) and not _NOISE.search(text)


def is_commission(text: str) -> bool:
    return bool(_COMMISSION.search(text))


def is_noise(text: str) -> bool:
    return bool(_NOISE.search(text))


def classify_gmail(item: NormalizedItem) -> dict:
    """Return {category, spam, needs_response} for a Gmail item using the allowlist
    + new-sale rules. Categories: peptideprice_sales, email_work, email_personal,
    content, financial_legal, newsletter_spam."""
    text = _text(item)
    handle = item.author_handle
    vendor = vendors.match(handle=handle, author=item.author,
                           subject=item.title, snippet=item.body_clean or item.body)

    # your own PeptidePrice roundups -> Content
    if handle and "peptideprice.store" in handle.lower() and "derek" in handle.lower():
        return {"category": "content", "spam": False, "needs_response": False}

    # financial / legal is sensitive -> Personal tab, kept separate
    if re.search(r"\b(accountant|attorney|lawyer|irs|tax return|bank statement|invoice due)\b", text, re.I):
        return {"category": "financial_legal", "spam": False, "needs_response": True}

    if vendor:
        if is_commission(text):
            # affiliate income notice — useful business record, not a sale to post
            return {"category": "email_work", "spam": False, "needs_response": False}
        if is_noise(text):
            return {"category": "newsletter_spam", "spam": True, "needs_response": False}
        if is_new_sale(text):
            return {"category": "peptideprice_sales", "spam": False, "needs_response": False}
        # vendor correspondence that isn't a sale (partner update, content hooks)
        return {"category": "email_work", "spam": False, "needs_response": False}

    # non-vendor
    if is_noise(text):
        return {"category": "newsletter_spam", "spam": True, "needs_response": False}
    if _WORK.search(text):
        return {"category": "email_work", "spam": False, "needs_response": False}
    if _PERSONAL.search(text):
        return {"category": "email_personal", "spam": False, "needs_response": False}
    # bulk-marketing sender or a sale pitch from a non-allowlisted sender -> filtered
    if (handle and _BULK_SENDER.search(handle)) or _SALE.search(text):
        return {"category": "newsletter_spam", "spam": True, "needs_response": False}
    return {"category": "email_personal", "spam": False, "needs_response": False}
