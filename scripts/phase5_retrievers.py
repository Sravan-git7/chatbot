"""Phase 5 EXPERIMENTAL retrievers (separate from every production path; nothing here is imported by the RAG scripts).

  dense   : cosine similarity of the query embedding against the existing `sap_m2c_card_v1` vectors (read-only use)
  bm25    : Okapi BM25 over the same `embedding_text` of the 29 cards (own implementation, no new dependency)
  hybrid  : w * minmax(dense) + (1 - w) * minmax(bm25), both min-max normalised over the 29 cards of ONE query

Fixed, transparent settings (declared before any result was seen):
  * tokenisation: lower-case, `[a-z0-9]+` (so "FI-CA" -> "fi", "ca"; "Move-In/Out" -> "move", "in", "out"); no stemming
  * stop words: the 33-word Lucene/Elasticsearch default English list
  * BM25: k1 = 1.5, b = 0.75, idf = ln(1 + (N - n + 0.5) / (n + 0.5)) (never negative)
  * hybrid: min-max normalisation per query; if a score vector is constant (e.g. BM25 finds no term), it becomes all zeros, so the
    hybrid then reduces to the dense ranking scaled by w
  * ties are broken by source id, so rankings are deterministic
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, List, Sequence, Tuple

STOPWORDS = frozenset("a an and are as at be but by for if in into is it no not of on or such that the their then there these they this to was will with".split())
K1, B = 1.5, 0.75
HYBRID_WEIGHTS = (0.75, 0.5, 0.25)        # weight of the DENSE component; 1.0 = dense only, 0.0 = BM25 only
PRIMARY_HYBRID_WEIGHT = 0.5               # declared in advance as the equal-weight reference; the others are a sensitivity check

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str, drop_stopwords: bool = True) -> List[str]:
    toks = _TOKEN.findall(text.lower())
    return [t for t in toks if t not in STOPWORDS] if drop_stopwords else toks


class BM25:
    def __init__(self, doc_ids: Sequence[str], docs: Sequence[str], k1: float = K1, b: float = B):
        self.ids = list(doc_ids)
        self.k1, self.b = k1, b
        self.tf = [Counter(tokenize(d)) for d in docs]
        self.len = [sum(c.values()) for c in self.tf]
        self.n = len(docs)
        self.avg = sum(self.len) / self.n
        self.df: Counter = Counter()
        for c in self.tf:
            self.df.update(c.keys())

    def idf(self, term: str) -> float:
        n = self.df.get(term, 0)
        return math.log(1.0 + (self.n - n + 0.5) / (n + 0.5))

    def scores(self, query: str) -> Dict[str, float]:
        q = tokenize(query)
        out = {}
        for i, doc_id in enumerate(self.ids):
            s = 0.0
            for t in q:
                f = self.tf[i].get(t, 0)
                if f:
                    s += self.idf(t) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
            out[doc_id] = s
        return out

    def matched_terms(self, query: str, doc_id: str) -> List[str]:
        i = self.ids.index(doc_id)
        return sorted({t for t in tokenize(query) if self.tf[i].get(t)})


def minmax(scores: Dict[str, float]) -> Dict[str, float]:
    lo, hi = min(scores.values()), max(scores.values())
    if hi - lo < 1e-12:
        return {k: 0.0 for k in scores}
    return {k: (v - lo) / (hi - lo) for k, v in scores.items()}


def hybrid(dense: Dict[str, float], lexical: Dict[str, float], w_dense: float) -> Dict[str, float]:
    if not 0.0 <= w_dense <= 1.0:
        raise ValueError("w_dense must be within [0, 1]")
    d, l = minmax(dense), minmax(lexical)
    return {k: w_dense * d[k] + (1.0 - w_dense) * l[k] for k in dense}


def rank(scores: Dict[str, float]) -> List[Tuple[str, float]]:
    return sorted(scores.items(), key=lambda kv: (-round(kv[1], 12), kv[0]))
