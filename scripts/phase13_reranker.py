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
# Phase 18 (E1): technical-match channel weight (generalisation of the Phase 15 code channel).
# Active only when code_aware AND the query carries code tokens and/or discriminative phrases.
W_TECH = 0.10
PHRASE_MAX = 24                      # cap on number of query phrases considered per query (performance bound)
PHRASE_TOKEN_MIN_LEN = 3             # tokens shorter than this never form a phrase token


def discriminative_phrases(query: str, max_phrases: int = PHRASE_MAX) -> List[str]:
    """Phase 18 (E1a) - query 2-3grams over the ORIGINAL token sequence (stopwords kept, case-folded).

    Stopwords are deliberately NOT removed: the phrase must occur *verbatim* in page text, so the
    source's own function words are part of the match ("save the installment plan" only matches
    because "the" is kept). Uniqueness is enforced at scoring time (a phrase that occurs in exactly
    ONE ingested page page is discriminative; phrases in 0 or >= 2 pages carry no signal).
    """
    import re
    tokens = [t for t in re.findall(r"[a-z0-9_-]+", (query or "").lower()) if len(t) >= PHRASE_TOKEN_MIN_LEN]
    out: List[str] = []
    seen = set()
    for n in (3, 2):
        for i in range(len(tokens) - n + 1):
            gram = " ".join(tokens[i:i + n])
            if gram not in seen:
                seen.add(gram)
                out.append(gram)
            if len(out) >= max_phrases:
                return out
    return out


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
    phrase_match: float = 0.0

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
            "phrase_match": round(self.phrase_match, 4),
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
    phrase_match: float = 0.0,
    tech_regime: Optional[bool] = None,
    full_page_coverage: bool = False,
    k_chunks: int = 3,
) -> ScoredCandidate:
    qterms = qterms if qterms is not None else T.terms(query)
    if tech_regime is None:
        # Direct-call fallback (tests / ad-hoc use): derive the regime per candidate.
        tech_regime = bool(code_aware and (query_code_tokens or phrase_match > 0.0))
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
    page_txt = ""

    if ingested:
        try:
            page_key = (identity.effective_guide_id, identity.effective_page_id)
            fetch_k = max(3, int(k_chunks))
            page_key_k = (identity.effective_guide_id, identity.effective_page_id, fetch_k)
            if hits_cache is not None and page_key_k in hits_cache:
                raw_hits = hits_cache[page_key_k]
            elif hits_cache is not None and page_key in hits_cache and int(k_chunks) <= 3:
                raw_hits = hits_cache[page_key]
            else:
                raw_hits = retriever.retrieve_in_page(
                    query,
                    identity.effective_guide_id,
                    identity.effective_page_id,
                    top_k=fetch_k,
                    query_embedding=query_embedding,
                )
                if hits_cache is not None:
                    hits_cache[page_key] = raw_hits
                    hits_cache[page_key_k] = raw_hits
            hits = list(raw_hits)[:3] if raw_hits else []
            if hits:
                page_sim = round(max(h.similarity for h in hits), 4)
                note = f"page_hits={len(hits)}_top_chunk_sim={page_sim}"
            else:
                note = "ingested_but_no_chunks"
        except Exception as e:
            note = f"page_retrieval_error: {type(e).__name__}"
        if hasattr(corpus, "page_text"):
            page_txt = corpus.page_text(cand.source_id) or ""

        # Phase 18 (E1b): coverage over the candidate's FULL page text (the page is small, ~1-6 KB)
        # instead of only the top-2 retrieved chunks. Flag OFF preserves the Phase 13 behaviour.
        if full_page_coverage and page_txt:
            coverage = round(T.coverage(qterms, page_txt), 4)
        elif hits:
            cov_text = " ".join(f"{h.title} {h.text}" for h in hits[:2])
            coverage = round(T.coverage(qterms, cov_text), 4)
    elif status_7c in (pid.CONFLICTING_IDENTITY, pid.CARD_IDENTITY_ONLY, pid.UNRESOLVED):
        note = f"unresolved_identity_{status_7c}"
    else:
        note = "not_ingested_no_local_content"

    # Check code match in page text when code_aware mode is active
    if code_aware and query_code_tokens and ingested:
        if not page_txt and hits:
            page_txt = " ".join(f"{h.title} {h.text}" for h in hits)
        import re
        if any(re.search(r'\b' + re.escape(ct.lower()) + r'\b', page_txt.lower()) for ct in query_code_tokens):
            code_match = 1.0

    # Phase 18 (E1a): phrase_match is precomputed per candidate in rerank_candidates (a query phrase
    # that occurs in EXACTLY ONE ingested page page is discriminative; the matching candidate gets 1.0).
    # It is only ever supplied when code_aware is on; 0.0 otherwise (flag OFF => always 0.0).

    # Deterministic scoring formula:
    # Phase 15: 0.40 card + 0.40 page + 0.10 cov + 0.10 code when code_aware AND query has code tokens
    # Phase 18 (E1): 0.40 card + 0.40 page + 0.10 cov + 0.10 tech when the query-level tech regime is
    #                active (code_aware AND the query carries code tokens and/or discriminative phrases
    #                with a unique page owner; tech = max(code_match, phrase_match) per candidate).
    #                The regime is chosen per QUERY (not per candidate) so all candidates share one
    #                comparable score scale, exactly as in Phase 15; with only code tokens this
    #                reduces EXACTLY to the Phase 15 formula.
    # Phase 13 baseline: 0.50 card + 0.40 page + 0.10 cov when no code tokens or not code_aware
    tech = max(code_match, phrase_match)
    if tech_regime:
        w_card, w_page, w_cov, w_tech = 0.40, 0.40, 0.10, W_TECH
    else:
        w_card, w_page, w_cov, w_tech = W_CARD, W_PAGE, W_COVERAGE, 0.0

    if ingested:
        score = w_card * card_sim + w_page * page_sim + w_cov * coverage + w_tech * tech
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
        phrase_match=phrase_match,
    )


def unique_phrase_page_map(phrases: Sequence[str], corpus: Any, min_corroboration: int = 1) -> Dict[str, str]:
    """Phase 18 (E1a) - for each query phrase, the single ingested page (by source_id) whose FULL page text
    contains it as a substring, when EXACTLY ONE such page exists. Phrases in 0 or >= 2 pages are dropped
    (no discriminative signal). Deterministic; reads only the corpus page texts (cached).

    ``min_corroboration`` (E1a-v2, evaluated in Phase 18 run 2): a page only qualifies if it is the unique
    owner of at least ``min_corroboration`` DISTINCT query phrases. A single verbatim 2-3gram ("when bill",
    "the billing period") is weak evidence - it can appear on a page without that page being the answer
    source - and with ``min_corroboration=1`` it was sufficient to flip the #1 slot against the correct
    embedding + coverage signal (Phase 18 run 1, P12-020 / P12-023). Two independent verbatim matches are
    convergent evidence about the page's topic. ``min_corroboration=1`` (default) preserves the run-1
    behaviour exactly, so the old configuration stays reproducible for comparison."""
    out: Dict[str, str] = {}
    if not phrases or not hasattr(corpus, "entries") or not hasattr(corpus, "page_text"):
        return out
    page_texts: Dict[str, str] = {}
    has_low = hasattr(corpus, "page_text_lower")
    for sid in sorted(corpus.entries):
        if corpus.entries[sid].get("corpus_status") != PC.S_INGESTED:
            continue
        txt = corpus.page_text_lower(sid) if has_low else (corpus.page_text(sid) or "").lower()
        if txt:
            page_texts[sid] = txt
    if not page_texts:
        return out
    by_page: Dict[str, List[str]] = {}
    for phrase in phrases:
        matching = [sid for sid, txt in page_texts.items() if phrase in txt]
        if len(matching) == 1:
            by_page.setdefault(matching[0], []).append(phrase)
    for page, owned in by_page.items():
        if len(owned) >= min_corroboration:
            out.update({ph: page for ph in owned})
    return out


def _can_batch_retrieve(retriever: Any) -> bool:
    return (
        hasattr(retriever, "retrieve_many_pages")
        and "retrieve_in_page" not in getattr(retriever, "__dict__", {})
        and "_query" not in getattr(retriever, "__dict__", {})
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
    phrase_reranker: bool = False,
    phrase_min_corroboration: int = 1,
    full_page_coverage: bool = False,
    k_chunks: int = 3,
    hits_out: Optional[Dict[Tuple[str, str], Any]] = None,
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

    # Phase 18 (E1a): precompute the unique-phrase -> page map ONCE per query. Only candidates whose page is
    # the (sufficiently corroborated) unique page of the query phrases get phrase_match = 1.0.
    # Flag OFF => empty map, zero behaviour change.
    phrase_owner: Dict[str, str] = {}
    if code_aware and phrase_reranker:
        phrases = discriminative_phrases(query)
        phrase_owner = unique_phrase_page_map(phrases, corpus, min_corroboration=phrase_min_corroboration)
    # Query-level tech regime (Phase 15 pattern): all candidates share one weight regime so their scores
    # remain comparable; active when code_aware AND the query carries code tokens and/or a discriminative
    # phrase with a unique page owner. With the phrase flag OFF this reduces EXACTLY to the Phase 15 rule.
    tech_regime = bool(code_aware and (query_code_tokens or phrase_owner))

    # Precompute query embedding once per reranking operation if not supplied
    if query_embedding is None and hasattr(retriever, "embed"):
        query_embedding = retriever.embed([query])

    hits_cache: Dict[Tuple[Any, ...], Any] = hits_out if hits_out is not None else {}

    if _can_batch_retrieve(retriever):
        fetch_k = max(3, int(k_chunks))
        pages_to_fetch: List[Tuple[str, str]] = []
        for cand in to_eval:
            card_obj = cards_map.get(cand.source_id, {})
            ident = pid.resolve_identity(card_obj if card_obj else cand, ctx)
            entry = corpus.entry(cand.source_id) or {}
            ingested = bool(
                entry.get("corpus_status") == "ingested"
                and ident.effective_guide_id
                and ident.effective_page_id
            )
            if ingested:
                pk = (str(ident.effective_guide_id), str(ident.effective_page_id))
                pk_k = (pk[0], pk[1], fetch_k)
                if pk_k not in hits_cache and pk not in pages_to_fetch:
                    pages_to_fetch.append(pk)
        if pages_to_fetch:
            batched = retriever.retrieve_many_pages(
                query,
                pages_to_fetch,
                top_k=fetch_k,
                query_embedding=query_embedding,
            )
            for pk, raw_hits in batched.items():
                hits_list = list(raw_hits)
                hits_cache[pk] = hits_list
                hits_cache[(pk[0], pk[1], fetch_k)] = hits_list

    scored: List[ScoredCandidate] = []
    for cand in to_eval:
        card_obj = cards_map.get(cand.source_id, {})
        p_match = 1.0 if any(sid == cand.source_id for sid in phrase_owner.values()) else 0.0
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
            phrase_match=p_match,
            tech_regime=tech_regime,
            full_page_coverage=full_page_coverage,
            k_chunks=k_chunks,
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
            phrase_match=sc.phrase_match,
        )
        for idx, sc in enumerate(scored, 1)
    ]

    selected = reranked_scored[0].candidate
    return selected, reranked_scored
