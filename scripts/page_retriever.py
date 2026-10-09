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
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_page_collection as BP  # noqa: E402

MAX_PAGE_CHUNKS_CACHE = 64


class LeakageError(RuntimeError):
    """A chunk outside the identity-constrained page was returned. Never swallowed."""


class PageStoreUnavailable(RuntimeError):
    """The configured page collection is missing, empty, or incompatible with cosine retrieval."""


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
        self._chunk_by_id: Optional[Dict[str, Tuple[str, Dict[str, Any], Tuple[str, ...]]]] = None
        self._chunks_by_page: Optional[Dict[Tuple[str, str], Tuple[ChunkHit, ...]]] = None
        self._indexed_count: int = -1
        self._page_chunks_cache: Dict[Tuple[str, str], Tuple[ChunkHit, ...]] = {}
        self._cache_lock = threading.Lock()

    def _ensure_chunk_index(self) -> bool:
        if "get" in getattr(self.collection, "__dict__", {}):
            return False
        try:
            cur_count = int(self.collection.count())
        except Exception:
            return False
        if (
            self._chunk_by_id is not None
            and self._chunks_by_page is not None
            and self._indexed_count == cur_count
        ):
            return True
        with self._cache_lock:
            if (
                self._chunk_by_id is not None
                and self._chunks_by_page is not None
                and self._indexed_count == cur_count
            ):
                return True
            try:
                raw = self.collection.get(include=["documents", "metadatas"])
                ids = raw.get("ids") or []
                docs = raw.get("documents") or []
                mds = raw.get("metadatas") or []
                if not ids or len(ids) != len(docs) or len(ids) != len(mds):
                    return False
                by_id: Dict[str, Tuple[str, Dict[str, Any], Tuple[str, ...]]] = {}
                by_page_list: Dict[Tuple[str, str], List[ChunkHit]] = {}
                for cid, doc, md in zip(ids, docs, mds):
                    hp = tuple(json.loads(md.get("heading_path_json") or "[]"))
                    md_copy = dict(md)
                    by_id[str(cid)] = (str(doc), md_copy, hp)
                    key = (str(md["guide_id"]), str(md["page_id"]))
                    by_page_list.setdefault(key, []).append(
                        ChunkHit(
                            rank=0,
                            chunk_id=md_copy["chunk_id"],
                            guide_id=md_copy["guide_id"],
                            page_id=md_copy["page_id"],
                            source_url=md_copy["source_url"],
                            title=md_copy["title"],
                            heading_path=hp,
                            section_title=md_copy.get("section_title", ""),
                            chunk_index=int(md_copy["chunk_index"]),
                            chunk_count=int(md_copy["chunk_count"]),
                            content_hash=md_copy["content_hash"],
                            text=str(doc),
                            distance=1.0,
                            similarity=0.0,
                            metadata=dict(md_copy),
                        )
                    )
                by_page_frozen: Dict[Tuple[str, str], Tuple[ChunkHit, ...]] = {
                    k: tuple(sorted(v, key=lambda h: h.chunk_index))
                    for k, v in by_page_list.items()
                }
                self._chunk_by_id = by_id
                self._chunks_by_page = by_page_frozen
                self._indexed_count = len(by_id)
                for k, v in by_page_frozen.items():
                    if len(self._page_chunks_cache) < MAX_PAGE_CHUNKS_CACHE or k in self._page_chunks_cache:
                        self._page_chunks_cache[k] = v
                return True
            except Exception:
                return False

    @classmethod
    def from_store(cls, vector_dir: Path = BP.PAGE_VECTOR_DIR, collection: str = BP.PAGE_COLLECTION, embed: Optional[Callable] = None) -> "PageRetriever":
        import chromadb
        from chromadb.config import Settings
        BP.guard_names(collection, vector_dir)
        if not Path(vector_dir).is_dir():
            raise FileNotFoundError(f"page vector store {vector_dir} not found: run scripts/build_page_collection.py")
        client = chromadb.PersistentClient(path=str(vector_dir), settings=Settings(anonymized_telemetry=False))
        try:
            col = client.get_collection(collection)
        except Exception as e:
            raise PageStoreUnavailable(f"page collection {collection!r} not found in {vector_dir}: {e}") from e
        metadata = getattr(col, "metadata", None) or {}
        space = metadata.get("hnsw:space")
        if space != BP.DISTANCE_SPACE:
            raise PageStoreUnavailable(f"page collection {collection!r} reports distance space {space!r}; expected {BP.DISTANCE_SPACE!r}")
        try:
            count = int(col.count())
        except Exception as e:
            raise PageStoreUnavailable(f"page collection {collection!r} could not be counted: {e}") from e
        if count < 1:
            raise PageStoreUnavailable(f"page collection {collection!r} is empty")
        recorded_count = metadata.get("vector_count")
        if recorded_count is not None and int(recorded_count) != count:
            raise PageStoreUnavailable(f"page collection {collection!r} has {count} vectors, but metadata records {recorded_count}")
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
        where = {"$and": [{"guide_id": guide_id}, {"page_id": page_id}]}
        if query_embedding is None:
            hits = self._query(query, top_k, where)
        else:
            try:
                hits = self._query(query, top_k, where, query_embedding=query_embedding)
            except TypeError:
                hits = self._query(query, top_k, where)
        bad = [h.chunk_id for h in hits if h.guide_id != guide_id or h.page_id != page_id]
        if bad:
            raise LeakageError(f"chunks outside {guide_id}/{page_id}: {bad}")
        return hits

    def retrieve_many_pages(
        self,
        query: str,
        pages: Sequence[Tuple[str, str]],
        top_k: int = 5,
        query_embedding: Optional[Any] = None,
    ) -> Dict[Tuple[str, str], List[ChunkHit]]:
        """Batch-retrieve top_k chunks for multiple identity-constrained (guide_id, page_id) pages in one Chroma query."""
        for g, p in pages:
            if not g or not p:
                raise ValueError("guide_id and page_id are required for identity-constrained retrieval")
        unique_pages = list(dict.fromkeys((str(g), str(p)) for g, p in pages))
        if not str(query or "").strip() or not unique_pages:
            return {p: [] for p in unique_pages}
        if (
            "_query" in self.__dict__
            or "retrieve_in_page" in self.__dict__
            or not self._ensure_chunk_index()
            or self._chunk_by_id is None
            or self._chunks_by_page is None
        ):
            return {
                (g, p): self.retrieve_in_page(query, g, p, top_k=top_k, query_embedding=query_embedding)
                for g, p in unique_pages
            }
        out: Dict[Tuple[str, str], List[ChunkHit]] = {p: [] for p in unique_pages}
        present = [p for p in unique_pages if p in self._chunks_by_page and self._chunks_by_page[p]]
        if not present:
            return out
        if query_embedding is not None:
            if isinstance(query_embedding, (list, tuple)) and query_embedding and isinstance(query_embedding[0], (list, tuple)):
                q_embs = query_embedding
            elif hasattr(query_embedding, "ndim") and query_embedding.ndim == 2:
                q_embs = query_embedding
            else:
                q_embs = [query_embedding]
        else:
            q_embs = self.embed([query])
        n_target = sum(len(self._chunks_by_page[p]) for p in present)
        doc_ids = [f"{g}/{p}" for g, p in present]
        where: Dict[str, Any] = {"doc_id": doc_ids[0]} if len(doc_ids) == 1 else {"doc_id": {"$in": doc_ids}}
        res = self.collection.query(
            query_embeddings=q_embs,
            n_results=max(1, int(n_target)),
            where=where,
            include=["distances"],
        )
        ids_row = (res.get("ids") or [[]])[0]
        dists_row = (res.get("distances") or [[]])[0]
        req_set = set(unique_pages)
        k_lim = max(1, int(top_k))
        for cid, dist in zip(ids_row, dists_row):
            entry = self._chunk_by_id.get(str(cid))
            if entry is None:
                raise LeakageError(f"unknown chunk_id returned from collection: {cid!r}")
            doc, md, hp = entry
            key = (str(md["guide_id"]), str(md["page_id"]))
            if key not in req_set:
                raise LeakageError(f"chunks outside requested pages {unique_pages}: {[cid]}")
            bucket = out[key]
            if len(bucket) < k_lim:
                d_val = float(dist)
                bucket.append(
                    ChunkHit(
                        rank=len(bucket) + 1,
                        chunk_id=md["chunk_id"],
                        guide_id=md["guide_id"],
                        page_id=md["page_id"],
                        source_url=md["source_url"],
                        title=md["title"],
                        heading_path=hp,
                        section_title=md.get("section_title", ""),
                        chunk_index=int(md["chunk_index"]),
                        chunk_count=int(md["chunk_count"]),
                        content_hash=md["content_hash"],
                        text=doc,
                        distance=d_val,
                        similarity=1.0 - d_val,
                        metadata=dict(md),
                    )
                )
        return out

    def retrieve_corpus(self, query: str, top_k: int = 5) -> List[ChunkHit]:
        """Unconstrained search over all pages - evaluation ablation only."""
        return self._query(query, top_k, None)

    def page_chunks(self, guide_id: str, page_id: str) -> List[ChunkHit]:
        """All chunks of one page in document order (used for context neighbours and the lexical gate)."""
        key = (str(guide_id), str(page_id))
        if self._ensure_chunk_index() and self._chunks_by_page is not None:
            cached_idx = self._chunks_by_page.get(key, ())
            return [replace(h, metadata=dict(h.metadata)) for h in cached_idx]
        with self._cache_lock:
            cached = self._page_chunks_cache.get(key)
        if cached is not None:
            return [replace(h, metadata=dict(h.metadata)) for h in cached]
        res = self.collection.get(where={"$and": [{"guide_id": guide_id}, {"page_id": page_id}]}, include=["documents", "metadatas"])
        hits = sorted((_hit(0, d, m, 1.0) for d, m in zip(res["documents"], res["metadatas"])), key=lambda h: h.chunk_index)
        frozen_hits = tuple(replace(h, metadata=dict(h.metadata)) for h in hits)
        with self._cache_lock:
            if len(self._page_chunks_cache) < MAX_PAGE_CHUNKS_CACHE or key in self._page_chunks_cache:
                self._page_chunks_cache[key] = frozen_hits
        return [replace(h, metadata=dict(h.metadata)) for h in frozen_hits]

    def has_page(self, guide_id: str, page_id: str) -> bool:
        res = self.collection.get(where={"$and": [{"guide_id": guide_id}, {"page_id": page_id}]}, limit=1, include=[])
        return bool(res["ids"])
