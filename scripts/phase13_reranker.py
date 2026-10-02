#!/usr/bin/env python3
"""Phase 13-A: Multi-candidate router reranker using page retrieval evidence.

Retains top-k card candidates from the initial dense router, retrieves top page chunks
for each candidate that has valid local page content, and deterministically reranks them
using combined card similarity, page chunk relevance, lexical coverage, and identity validity.

Contract rules (Phase 13-A):
1. Reranker operates only on query + available corpus/card/page evidence (no hardcoded IDs or frozen labels).
2. Candidates with unresolved/invalid identity and no usable page evidence do NOT automatically win
   over candidates with verified valid page evidence.
3. If reranking is disabled (default), baseline rank-1 selection is strictly preserved.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import m2c_page_identity as pid
import page_corpus as PC
import rag_text as T
from m2c_router import CardCandidate

# Weights for deterministic scoring formula
W_CARD = 0.50
W_PAGE = 0.40
W_COVERAGE = 0.10
UNRESOLVED_PENALTY = 0.20
NOT_INGESTED_PENALTY = 0.10


@dataclass(frozen=True)
class ScoredCandidate:
    candidate: CardCandidate
    card_similarity: float
    page_similarity: float
    coverage: float
    ingested: bool
    identity_status: str
    final_score: float
    rerank: int
    note: str
    code_match: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.candidate.source_id,
            "title": self.candidate.title,
            "initial_rank": self.candidate.rank,
            "rank": self.rerank,
            "rerank": self.rerank,
            "card_similarity": round(self.card_similarity, 4),
            "similarity": round(self.card_similarity, 4),
            "page_similarity": round(self.page_similarity, 4),
            "coverage": round(self.coverage, 4),
            "code_match": round(self.code_match, 4),
            "ingested": self.ingested,
            "identity_status": self.identity_status,
            "final_score": round(self.final_score, 4),
            "note": self.note,
        }


def score_candidate(
    query: str,
    cand: CardCandidate,
    card_obj: Mapping[str, Any],
    retriever: Any,
    ctx: pid.IdentityContext,
    corpus: Any,
    qterms: Optional[Sequence[str]] = None,
    query_embedding: Optional[Any] = None,
    hits_cache: Optional[Dict[Tuple[str, str], Any]] = None,
    query_code_tokens: Optional[Set[str]] = None,
    code_aware: bool = False,
) -> ScoredCandidate:
    qterms = qterms if qterms is not None else T.terms(query)
    card_sim = round(1.0 - cand.distance, 4)

    identity = pid.resolve_identity(card_obj, ctx)
    status_7c = identity.resolution_status
    entry = corpus.entry(cand.source_id) or {}
    ingested = (entry.get("corpus_status") == PC.S_INGESTED and
                bool(identity.effective_guide_id) and
                bool(identity.effective_page_id))

    page_sim = 0.0
    coverage = 0.0
    code_match = 0.0
    note = "initial"
    hits = None

    if ingested:
        try:
            page_key = (identity.effective_guide_id, identity.effective_page_id)
            if hits_cache is not None and page_key in hits_cache:
                hits = hits_cache[page_key]
            else:
                hits = retriever.retrieve_in_page(
                    query,
                    identity.effective_guide_id,
                    identity.effective_page_id,
                    top_k=3,
                    query_embedding=query_embedding,
                )
                if hits_cache is not None:
                    hits_cache[page_key] = hits
            if hits:
                page_sim = round(max(h.similarity for h in hits), 4)
                cov_text = " ".join(f"{h.title} {h.text}" for h in hits[:2])
                coverage = round(T.coverage(qterms, cov_text), 4)
                note = f"page_hits={len(hits)}_top_chunk_sim={page_sim}"
            else:
                note = "ingested_but_no_chunks"
        except Exception as e:
            note = f"page_retrieval_error: {type(e).__name__}"
    elif status_7c in (pid.CONFLICTING_IDENTITY, pid.CARD_IDENTITY_ONLY, pid.UNRESOLVED):
        note = f"unresolved_identity_{status_7c}"
    else:
        note = "not_ingested_no_local_content"

    # Check code match in page text when code_aware mode is active
    if code_aware and query_code_tokens and ingested:
        page_txt = ""
        if hasattr(corpus, "page_text"):
            page_txt = corpus.page_text(cand.source_id)
        if not page_txt and hits:
            page_txt = " ".join(f"{h.title} {h.text}" for h in hits)
        import re
        if any(re.search(r'\b' + re.escape(ct.lower()) + r'\b', page_txt.lower()) for ct in query_code_tokens):
            code_match = 1.0

    # Deterministic scoring formula:
    # Phase 15: 0.40 card + 0.40 page + 0.10 cov + 0.10 code when code_aware AND query has code tokens
    # Phase 13 baseline: 0.50 card + 0.40 page + 0.10 cov when no code tokens or not code_aware
    if code_aware and query_code_tokens:
        w_card, w_page, w_cov, w_code = 0.40, 0.40, 0.10, 0.10
    else:
        w_card, w_page, w_cov, w_code = W_CARD, W_PAGE, W_COVERAGE, 0.0

    if ingested:
        score = w_card * card_sim + w_page * page_sim + w_cov * coverage + w_code * code_match
    elif status_7c in (pid.CONFLICTING_IDENTITY, pid.CARD_IDENTITY_ONLY, pid.UNRESOLVED):
        score = w_card * card_sim - UNRESOLVED_PENALTY
    else:
        score = w_card * card_sim - NOT_INGESTED_PENALTY

    return ScoredCandidate(
        candidate=cand,
        card_similarity=card_sim,
        page_similarity=page_sim,
        coverage=coverage,
        ingested=bool(ingested),
        identity_status=status_7c,
        final_score=round(score, 4),
        rerank=0,  # filled after sorting
        note=note,
        code_match=code_match,
    )


def rerank_candidates(
    query: str,
    candidates: Sequence[CardCandidate],
    cards_map: Mapping[str, Mapping[str, Any]],
    retriever: Any,
    ctx: pid.IdentityContext,
    corpus: Any,
    top_k_evaluate: int = 5,
    query_embedding: Optional[Any] = None,
    code_aware: bool = False,
) -> Tuple[CardCandidate, List[ScoredCandidate]]:
    """Rerank the top_k_evaluate candidates using page evidence and return (selected_card, scored_candidates)."""
    if not candidates:
        raise ValueError("candidates sequence is empty")

    to_eval = candidates[:top_k_evaluate]
    qterms = T.terms(query)

    query_code_tokens: Set[str] = set()
    if code_aware:
        EXCLUDED_CODES = frozenset({"SAP", "IS", "SYSTEM", "THE", "AND", "FOR", "NOT"})
        query_code_tokens = {c.upper() for c in T.code_tokens(query) if c.upper() not in EXCLUDED_CODES}

    # Precompute query embedding once per reranking operation if not supplied
    if query_embedding is None and hasattr(retriever, "embed"):
        query_embedding = retriever.embed([query])

    hits_cache: Dict[Tuple[str, str], Any] = {}

    scored: List[ScoredCandidate] = []
    for cand in to_eval:
        card_obj = cards_map.get(cand.source_id, {})
        sc = score_candidate(
            query,
            cand,
            card_obj,
            retriever,
            ctx,
            corpus,
            qterms=qterms,
            query_embedding=query_embedding,
            hits_cache=hits_cache,
            query_code_tokens=query_code_tokens,
            code_aware=code_aware,
        )
        scored.append(sc)

    # Sort descending by final_score, breaking ties by card_similarity, then initial rank
    scored.sort(key=lambda s: (s.final_score, s.card_similarity, -s.candidate.rank), reverse=True)

    # Assign rerank indices
    reranked_scored = [
        ScoredCandidate(
            candidate=sc.candidate,
            card_similarity=sc.card_similarity,
            page_similarity=sc.page_similarity,
            coverage=sc.coverage,
            ingested=sc.ingested,
            identity_status=sc.identity_status,
            final_score=sc.final_score,
            rerank=idx,
            note=sc.note,
            code_match=sc.code_match,
        )
        for idx, sc in enumerate(scored, 1)
    ]

    selected = reranked_scored[0].candidate
    return selected, reranked_scored
