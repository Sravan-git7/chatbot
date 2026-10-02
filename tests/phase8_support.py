"""Shared fixtures for the Phase 8 tests: a deterministic fake embedder, a stub card backend and an in-memory page store, so that the
pipeline logic is tested without the embedding model, the card store or the page store."""
from __future__ import annotations

import hashlib
import importlib.util
import itertools
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import m2c_page_identity as pid  # noqa: E402
import page_chunker as PK  # noqa: E402
import page_corpus as PC  # noqa: E402

DIM = 96
CARD_META_KEYS = ("retrieval_unit_id", "source_id", "source_number", "title", "category", "filename", "source_url", "source_status", "source_url_status",
                  "has_source_correction", "citation", "sha256")


def have(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


HAVE_CHROMA = have("chromadb")
HAVE_NUMPY = have("numpy")
HAVE_BS4 = have("bs4")
PAGE_STORE = ROOT / "data" / "vector_store" / "page_collection"
CARD_STORE = ROOT / "data" / "vector_store"


def fake_embed(texts: Sequence[str]) -> List[List[float]]:
    """Hashed bag-of-words, L2-normalised: deterministic and lexical, enough to rank chunks that share words with the query."""
    out = []
    for t in texts:
        v = [0.0] * DIM
        for w in re.findall(r"[a-z0-9]+", t.lower()):
            h = int(hashlib.md5(w.encode()).hexdigest(), 16)
            v[h % DIM] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


def regex_count(text: str) -> int:
    return len(re.findall(r"\w+|[^\w\s]", text)) + 2


def corpus_records() -> List[Dict[str, Any]]:
    return PC.load_records()


_COUNTER = itertools.count()


def ephemeral_page_collection(records: Sequence[Dict[str, Any]], strategy: str = "B_heading_200", name: str = "t8pages"):
    import chromadb
    from chromadb.config import Settings
    import build_page_collection as BP
    client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False, allow_reset=True))
    chunks = PK.chunk_corpus(records, PK.STRATEGIES[strategy], regex_count)
    col = client.create_collection(name=f"{name}_{next(_COUNTER)}", metadata={"hnsw:space": "cosine"})
    BP.fill_collection(col, chunks, list(records), fake_embed)
    return col, chunks


class StubBackend:
    """Card backend that returns a fixed ranking of source ids per query (cosine distance fabricated but ordered)."""
    distance_metric = "cosine"

    def __init__(self, ranking: Dict[str, Sequence[str]], default: Optional[Sequence[str]] = None) -> None:
        self.ranking = ranking
        self.default = list(default or ["M2C-24"])
        self.cards = {c["source_id"]: c for c in pid.load_cards(ROOT)}
        self.calls: List[str] = []

    def query(self, query: str, n_results: int):
        self.calls.append(query)
        ids = list(self.ranking.get(query, self.default))[:n_results]
        metas = []
        for sid in ids:
            u = self.cards[sid]
            metas.append({k: u[k] for k in CARD_META_KEYS})
        return {"ids": [ids], "metadatas": [metas], "distances": [[0.30 + 0.05 * i for i in range(len(ids))]]}


def make_pipeline(generator: Any, ranking: Optional[Dict[str, Sequence[str]]] = None, default: Optional[Sequence[str]] = None, strategy: str = "B_heading_200",
                  config: Any = None):
    import page_retriever as PR
    import rag_pipeline as RP
    records = corpus_records()
    col, _ = ephemeral_page_collection(records, strategy)
    return RP.RagPipeline(StubBackend(ranking or {}, default), PR.PageRetriever(col, fake_embed), pid.IdentityContext.from_root(ROOT), RP.PageCorpusIndex.from_dir(),
                          generator, regex_count, config=config)
