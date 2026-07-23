"""The shared contract every collector emits and the pipeline consumes.

A collector's only job is to turn a raw source object into a NormalizedItem.
Everything downstream (sanitize, classify, retrieve, draft) speaks this language.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class NormalizedItem(BaseModel):
    """One unit of activity from any source, before enrichment."""

    source: str                        # connector name: gmail, calendar, telegram, skool
    source_id: str                     # native id — unique within a source
    thread_id: Optional[str] = None
    author: Optional[str] = None       # display name
    author_handle: Optional[str] = None  # email / @username
    url: Optional[str] = None          # direct link back to the item
    created_at: Optional[datetime] = None
    title: Optional[str] = None        # subject / short title
    body: str = ""                     # RAW body as collected (sanitized later)
    raw: dict[str, Any] = Field(default_factory=dict)  # original payload for audit

    # --- enrichment filled in by the pipeline, not the collector ---
    body_clean: Optional[str] = None
    body_hash: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    needs_response: bool = False
    injection_flag: bool = False
    spam: bool = False

    def compute_hash(self) -> str:
        basis = (self.body_clean or self.body or "").strip().lower()
        # collapse whitespace so trivial reformatting doesn't dodge dedup
        basis = " ".join(basis.split())
        return hashlib.sha256(f"{self.source}|{basis}".encode()).hexdigest()


class SalesFields(BaseModel):
    """Structured extraction for a PeptidePrice promo. Produced by the drafter."""

    vendor: Optional[str] = None
    promo_name: Optional[str] = None
    discount: Optional[str] = None
    stacking_rules: Optional[str] = None
    coupon_code: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    end_tz: Optional[str] = None
    exclusions: Optional[str] = None
    free_shipping_threshold: Optional[str] = None
    giveaway: Optional[str] = None
    confidence: str = "low"
