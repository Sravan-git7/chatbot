"""Phase 8E - page-chunk retriever (second retrieval stage, constrained by the page identity chosen by the card router).

The first stage (card router, Phase 7) picks a card; Phase 7C turns it into an effective ``(guide_id, page_id)``; this module then
searches ONLY the chunks of that page. Two modes:

* ``retrieve_in_page(query, guide_id, page_id)`` - production mode. A Chroma ``where`` filter restricts the search to the page, and a
  post-check verifies every returned chunk really belongs to it; any leakage raises ``LeakageError`` (a bug, never silently dropped).
* ``retrieve_corpus(query)`` - NO identity constraint, used only by the evaluation to measure how a direct page-chunk search would do
  against the card-first design (an ablation). It is never reachable from the answer pipeline.

Every hit keeps the citation metadata (chunk_id, guide_id, page_id, source_url, title, heading_path, content_hash). Similarity is
``1 - cosine distance`` (the collection is cosine). No threshold is applied here.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_page_collection as BP  # noqa: E402


class LeakageError(RuntimeError):
    """A chunk outside the identity-constrained page was returned. Never swallowed."""


@dataclass(frozen=True)
class ChunkHit:
    rank: int
    chunk_id: str
    guide_id: str
    page_id: str
    source_url: str
    title: str
    heading_path: tuple
    section_title: str
    chunk_index: int
    chunk_count: int
    content_hash: str
    text: str
    distance: float
    similarity: float
    metadata: Dict[str, Any] = field(default_factory=dict, compare=False)

    def to_dict(self, with_text: bool = True) -> Dict[str, Any]:
        d = {"rank": self.rank, "chunk_id": self.chunk_id, "guide_id": self.guide_id, "page_id": self.page_id, "source_url": self.source_url,
             "title": self.title, "heading_path": list(self.heading_path), "section_title": self.section_title, "chunk_index": self.chunk_index,
             "chunk_count": self.chunk_count, "content_hash": self.content_hash, "distance": round(self.distance, 6), "similarity": round(self.similarity, 4)}
        if with_text:
            d["text"] = self.text
        return d


def _hit(rank: int, doc: str, md: Dict[str, Any], dist: float) -> ChunkHit:
    return ChunkHit(rank=rank, chunk_id=md["chunk_id"], guide_id=md["guide_id"], page_id=md["page_id"], source_url=md["source_url"], title=md["title"],
                    heading_path=tuple(json.loads(md.get("heading_path_json") or "[]")), section_title=md.get("section_title", ""),
                    chunk_index=int(md["chunk_index"]), chunk_count=int(md["chunk_count"]), content_hash=md["content_hash"], text=doc,
                    distance=float(dist), similarity=1.0 - float(dist), metadata=dict(md))


class PageRetriever:
    def __init__(self, collection: Any, embed: Callable[[Sequence[str]], List[List[float]]]):
        self.collection = collection
        self.embed = embed

    @classmethod
    def from_store(cls, vector_dir: Path = BP.PAGE_VECTOR_DIR, collection: str = BP.PAGE_COLLECTION, embed: Optional[Callable] = None) -> "PageRetriever":
        import chromadb
        from chromadb.config import Settings
        BP.guard_names(collection, vector_dir)
        if not Path(vector_dir).is_dir():
            raise FileNotFoundError(f"page vector store {vector_dir} not found: run scripts/build_page_collection.py")
        client = chromadb.PersistentClient(path=str(vector_dir), settings=Settings(anonymized_telemetry=False))
        col = client.get_collection(collection)
        return cls(col, embed or BP.load_embedder()[0])

    def count(self) -> int:
        return int(self.collection.count())

    def _query(self, query: str, top_k: int, where: Optional[Dict[str, Any]], query_embedding: Optional[Any] = None) -> List[ChunkHit]:
        if not str(query or "").strip():
            return []
        if query_embedding is not None:
            if isinstance(query_embedding, (list, tuple)) and query_embedding and isinstance(query_embedding[0], (list, tuple)):
                q_embs = query_embedding
            elif hasattr(query_embedding, "ndim") and query_embedding.ndim == 2:
                q_embs = query_embedding
            else:
                q_embs = [query_embedding]
        else:
            q_embs = self.embed([query])
        kw: Dict[str, Any] = {"query_embeddings": q_embs, "n_results": max(1, int(top_k)), "include": ["documents", "metadatas", "distances"]}
        if where:
            kw["where"] = where
        res = self.collection.query(**kw)
        docs, mds, dists = res["documents"][0], res["metadatas"][0], res["distances"][0]
        return [_hit(i + 1, d, m, x) for i, (d, m, x) in enumerate(zip(docs, mds, dists))]

    def retrieve_in_page(self, query: str, guide_id: str, page_id: str, top_k: int = 5, query_embedding: Optional[Any] = None) -> List[ChunkHit]:
        if not guide_id or not page_id:
            raise ValueError("guide_id and page_id are required for identity-constrained retrieval")
        hits = self._query(query, top_k, {"$and": [{"guide_id": guide_id}, {"page_id": page_id}]}, query_embedding=query_embedding)
        bad = [h.chunk_id for h in hits if h.guide_id != guide_id or h.page_id != page_id]
        if bad:
            raise LeakageError(f"chunks outside {guide_id}/{page_id}: {bad}")
        return hits

    def retrieve_corpus(self, query: str, top_k: int = 5) -> List[ChunkHit]:
        """Unconstrained search over all pages - evaluation ablation only."""
        return self._query(query, top_k, None)

    def page_chunks(self, guide_id: str, page_id: str) -> List[ChunkHit]:
        """All chunks of one page in document order (used for context neighbours and the lexical gate)."""
        res = self.collection.get(where={"$and": [{"guide_id": guide_id}, {"page_id": page_id}]}, include=["documents", "metadatas"])
        hits = [_hit(0, d, m, 1.0) for d, m in zip(res["documents"], res["metadatas"])]
        return sorted(hits, key=lambda h: h.chunk_index)

    def has_page(self, guide_id: str, page_id: str) -> bool:
        res = self.collection.get(where={"$and": [{"guide_id": guide_id}, {"page_id": page_id}]}, limit=1, include=[])
        return bool(res["ids"])
