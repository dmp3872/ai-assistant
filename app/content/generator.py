"""The generation brain — Claude writes posts and canonical answers in Derek's voice.

Mirrors app/drafting/claude_drafter: retrieval supplies grounding from PUBLIC namespaces
only (never personal/financial), the API key comes from Keychain, and any failure —
missing key, network, bad JSON — degrades to None instead of breaking the cycle.
"""
from __future__ import annotations

import json

from app.content.prompts import build_answer_prompt, build_post_prompt
from app.retrieval import get_store
from app.security import audit, get_secret
from app.settings import get_settings

_settings = get_settings()


def _client():
    import anthropic

    return anthropic.Anthropic(api_key=get_secret("anthropic_api_key", required=True))


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    return {}


def _snippets(query: str, k: int = 6) -> list[dict]:
    try:
        return get_store().search_public(query, k=k)
    except Exception:
        return []


def generate_answer(question: str) -> dict | None:
    """Draft a canonical, reusable answer for a recurring community question.
    Returns {title, body, confidence, review_reason, sources_used, model} or None."""
    snippets = _snippets(question, k=int(
        _settings.config.get("drafting", {}).get("max_context_snippets", 6)))
    system, user = build_answer_prompt(question[:1000], snippets)
    try:
        resp = _client().messages.create(
            model=_settings.claude_model, max_tokens=900,
            system=system, messages=[{"role": "user", "content": user}])
        data = _parse_json(resp.content[0].text)
        if not data.get("body"):
            return None
        audit("draft", subtype="content_answer", title=data.get("title"),
              confidence=data.get("confidence"))
        return {
            "title": (data.get("title") or question)[:280],
            "body": data.get("body", "").strip(),
            "confidence": data.get("confidence", "low"),
            "review_reason": data.get("review_reason", ""),
            "sources_used": data.get("sources_used", []),
            "model": _settings.claude_model,
        }
    except Exception as exc:
        audit("error", stage="generate_answer", error=str(exc))
        return None


def generate_post(channel: str, seed: str, avoid_titles: list[str] | None = None) -> dict | None:
    """Draft one copy-ready post for `channel`, grounded in your content around `seed`.
    Returns {title, hook, body, cta, angle, tags, confidence, review_reason, model} or None."""
    snippets = _snippets(seed, k=6)
    if not snippets:
        # Nothing of yours to ground on yet — refuse rather than invent.
        return None
    system, user = build_post_prompt(channel, seed[:1000], snippets, avoid_titles)
    try:
        resp = _client().messages.create(
            model=_settings.claude_model, max_tokens=1000,
            system=system, messages=[{"role": "user", "content": user}])
        data = _parse_json(resp.content[0].text)
        if not data.get("body"):
            return None
        audit("draft", subtype="content_post", channel=channel, title=data.get("title"),
              confidence=data.get("confidence"))
        return {
            "title": (data.get("title") or "").strip()[:280],
            "hook": (data.get("hook") or "").strip(),
            "body": data.get("body", "").strip(),
            "cta": (data.get("cta") or "").strip(),
            "angle": (data.get("angle") or "").strip(),
            "tags": data.get("tags", []),
            "confidence": data.get("confidence", "low"),
            "review_reason": data.get("review_reason", ""),
            "sources_used": [s.get("url", "") for s in snippets if s.get("url")][:6],
            "model": _settings.claude_model,
        }
    except Exception as exc:
        audit("error", stage="generate_post", channel=channel, error=str(exc))
        return None
