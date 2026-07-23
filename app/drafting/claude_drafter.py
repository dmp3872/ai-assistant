"""Draft responses in Derek's voice using the Claude API.

Called ONLY for items the classifier marked needs_response. Retrieval supplies the
context; the API key comes from Keychain. Output is a copy-ready draft plus confidence,
a review reason, and the sources it leaned on.
"""
from __future__ import annotations

import json

from app.drafting.prompts import build_draft_prompt
from app.models import NormalizedItem
from app.retrieval import get_store
from app.security import audit, get_secret
from app.settings import get_settings

_settings = get_settings()


def _client():
    import anthropic

    return anthropic.Anthropic(api_key=get_secret("anthropic_api_key", required=True))


def draft_response(item: NormalizedItem) -> dict | None:
    """Return {draft_text, confidence, review_reason, sources_used} or None."""
    dcfg = _settings.config.get("drafting", {})
    if not dcfg.get("enabled", True):
        return None
    if item.category not in dcfg.get("draft_categories", ["community", "vendor"]):
        return None

    query = f"{item.title or ''}\n{item.body_clean or item.body or ''}"[:1500]
    snippets = get_store().search_public(
        query, k=int(dcfg.get("max_context_snippets", 6))
    )

    system, user = build_draft_prompt(
        item.title or "", (item.body_clean or item.body or "")[:4000], snippets
    )

    try:
        client = _client()
        resp = client.messages.create(
            model=_settings.claude_model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = resp.content[0].text
        data = _parse_json(text)
        audit("draft", source=item.source, item=item.source_id,
              model=_settings.claude_model, confidence=data.get("confidence"))
        return {
            "draft_text": data.get("draft", "").strip(),
            "confidence": data.get("confidence", "low"),
            "review_reason": data.get("review_reason", ""),
            "sources_used": json.dumps(data.get("sources_used", [])),
            "model": _settings.claude_model,
        }
    except Exception as exc:  # never break the pipeline on a draft failure
        audit("error", source=item.source, stage="draft", error=str(exc))
        return None


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start:end + 1])
    return {"draft": text, "confidence": "low", "review_reason": "unparsed", "sources_used": []}
