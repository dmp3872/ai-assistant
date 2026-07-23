"""Embeddings. Prefers Ollama's embed model (fully local); falls back to
sentence-transformers. Both keep everything on your machine.
"""
from __future__ import annotations

from functools import lru_cache

import httpx

from app.settings import get_settings

_settings = get_settings()


def _ollama_embed(text: str) -> list[float] | None:
    try:
        r = httpx.post(
            f"{_settings.ollama_host}/api/embeddings",
            json={"model": _settings.ollama_embed_model, "prompt": text},
            timeout=60,
        )
        r.raise_for_status()
        return r.json().get("embedding")
    except Exception:
        return None


@lru_cache(maxsize=1)
def _st_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer("all-MiniLM-L6-v2")


def embed(text: str) -> list[float]:
    vec = _ollama_embed(text)
    if vec:
        return vec
    return _st_model().encode(text, normalize_embeddings=True).tolist()


def embed_dim() -> int:
    return len(embed("dimension probe"))
