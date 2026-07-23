"""Structured extraction of PeptidePrice promo fields, plus contradiction detection.

For items classified peptideprice_sales, pull vendor/discount/code/dates/etc into the
`sales` table. Then flag contradictions against prior promos from the same vendor
(e.g. "earlier said ends July 25, newest says July 27").
"""
from __future__ import annotations

import json

from app.db import get_session
from app.db.models import Sale
from app.drafting.prompts import SALES_SYSTEM
from app.models import NormalizedItem, SalesFields
from app.security import audit, get_secret
from app.settings import get_settings

_settings = get_settings()


def _client():
    import anthropic

    return anthropic.Anthropic(api_key=get_secret("anthropic_api_key", required=True))


def extract_sale(item: NormalizedItem) -> SalesFields | None:
    body = (item.body_clean or item.body or "")[:4000]
    try:
        resp = _client().messages.create(
            model=_settings.claude_model,
            max_tokens=600,
            system=SALES_SYSTEM,
            messages=[{"role": "user", "content": body}],
        )
        raw = resp.content[0].text
        start, end = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[start:end + 1]) if start >= 0 else {}
        fields = SalesFields(**{k: data.get(k) for k in SalesFields.model_fields
                                if data.get(k) is not None})
        audit("draft", source=item.source, kind="sales_extract", vendor=fields.vendor)
        return fields
    except Exception as exc:
        audit("error", source=item.source, stage="sales_extract", error=str(exc))
        return None


def find_contradiction(item_id: int, fields: SalesFields) -> int | None:
    """Return the id of an earlier sale from the same vendor whose end_date differs."""
    if not fields.vendor or not fields.end_date:
        return None
    with get_session() as s:
        prior = (
            s.query(Sale)
            .filter(Sale.vendor == fields.vendor, Sale.item_id != item_id)
            .order_by(Sale.id.desc())
            .first()
        )
        if prior and prior.end_date and prior.end_date != fields.end_date:
            return prior.id
    return None
