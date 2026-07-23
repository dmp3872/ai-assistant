"""LanceDB-backed retrieval over YOUR historical content, split into namespaces.

Security-critical rule: `search_public()` may only touch namespaces allowed for public
drafting (per config `retrieval.public_namespaces`). Personal/financial namespaces are
never reachable from a public-reply draft. This is the enforcement point for the
"never expose one source's private data to another" control.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.retrieval.embeddings import embed, embed_dim
from app.settings import get_settings

_settings = get_settings()


class RetrievalStore:
    def __init__(self) -> None:
        import lancedb

        self.db = lancedb.connect(_settings.config["retrieval"]["db_path"])
        self._dim = embed_dim()

    def _table(self, namespace: str):
        import pyarrow as pa  # bundled with lancedb

        if namespace in self.db.table_names():
            return self.db.open_table(namespace)
        schema = pa.schema([
            pa.field("vector", pa.list_(pa.float32(), self._dim)),
            pa.field("text", pa.string()),
            pa.field("source", pa.string()),
            pa.field("url", pa.string()),
            pa.field("ref_id", pa.string()),
        ])
        return self.db.create_table(namespace, schema=schema)

    def add(self, namespace: str, text: str, *, source: str = "", url: str = "",
            ref_id: str = "") -> None:
        if not text.strip():
            return
        tbl = self._table(namespace)
        tbl.add([{
            "vector": embed(text[:2000]),
            "text": text,
            "source": source,
            "url": url,
            "ref_id": ref_id,
        }])

    def search(self, namespace: str, query: str, k: int = 4) -> list[dict[str, Any]]:
        if namespace not in self.db.table_names():
            return []
        tbl = self.db.open_table(namespace)
        rows = tbl.search(embed(query)).limit(k).to_list()
        return [{"text": r["text"], "source": r["source"], "url": r["url"]} for r in rows]

    def search_public(self, query: str, k: int = 6) -> list[dict[str, Any]]:
        """Retrieve across ONLY the public-drafting namespaces. Personal/financial
        indexes are structurally excluded here."""
        allowed = _settings.config["retrieval"]["public_namespaces"]
        hits: list[dict[str, Any]] = []
        per = max(1, k // max(1, len(allowed)))
        for ns in allowed:
            hits.extend(self.search(ns, query, k=per))
        return hits[:k]


@lru_cache(maxsize=1)
def get_store() -> RetrievalStore:
    return RetrievalStore()
