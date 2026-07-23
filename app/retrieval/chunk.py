"""Chunk long text into overlapping passages for embedding.

Lessons and long posts embed poorly as one giant vector — retrieval gets sharper when
we split on paragraph/sentence boundaries into ~900-char passages with light overlap so
context isn't cut mid-thought.
"""
from __future__ import annotations

import re

_PARA = re.compile(r"\n\s*\n")
_SENT = re.compile(r"(?<=[.!?])\s+")


def chunk_text(text: str, max_chars: int = 900, overlap: int = 120) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    # Build units at paragraph granularity, hard-splitting any oversized paragraph.
    units: list[str] = []
    for para in _PARA.split(text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            units.append(para)
        else:
            units.extend(_split_long(para, max_chars))

    # Greedily pack units into chunks, carrying a small overlap tail between them.
    chunks: list[str] = []
    cur = ""
    for u in units:
        if cur and len(cur) + len(u) + 1 > max_chars:
            chunks.append(cur.strip())
            tail = cur[-overlap:] if overlap else ""
            cur = (tail + " " + u).strip()
        else:
            cur = (cur + "\n" + u).strip() if cur else u
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


def _split_long(para: str, max_chars: int) -> list[str]:
    out: list[str] = []
    cur = ""
    for sent in _SENT.split(para):
        if cur and len(cur) + len(sent) + 1 > max_chars:
            out.append(cur.strip())
            cur = sent
        else:
            cur = (cur + " " + sent).strip() if cur else sent
    if cur.strip():
        out.append(cur.strip())
    # last resort: a single sentence longer than max_chars
    final: list[str] = []
    for c in out:
        if len(c) <= max_chars:
            final.append(c)
        else:
            final.extend(c[i:i + max_chars] for i in range(0, len(c), max_chars))
    return final
