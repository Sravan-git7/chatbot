"""Phase 8G/8I - the end-to-end RAG pipeline with a structured answer contract.

    query -> card router (7B/7F, rank-1, no threshold) -> page identity (7C) -> lexical topic gate -> page corpus admission
          -> identity-constrained chunk retrieval -> context assembly -> generator -> grounding verifier -> citations (7D + 8H)

The card layer stays the first routing stage; it is never replaced by direct page-chunk retrieval. A card is a pointer, never
evidence: the generator receives page chunks only.

Answer statuses (``Answer["status"]``)
  answered              a grounded answer; every sentence cites supplied chunks and passed the verifier
  insufficient_context  the page was routed and retrieved but the chunks do not support an answer (or the generated answer failed the
                        grounding verifier and was withheld - ``reason_code`` says which)
  unresolved_identity   the routed card has no established page identity (M2C-18 conflict; cards whose guide is unverified)
  page_not_ingested     the topic and its page are identified but this system holds no text for the page
  out_of_domain         the question shares (almost) no content vocabulary with the routed topic
  no_relevant_page      the router produced no card (empty question)

Two lexical gates use pre-declared constants (``OOD_MIN_COVERAGE``, ``CONTEXT_MIN_COVERAGE``). They are heuristics, NOT calibrated
thresholds, and the card router is given no threshold at all (Phase 7F). Their measured behaviour is reported by the evaluation.
"""
from __future__ import annotations

import copy
import sys
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import m2c_page_identity as pid  # noqa: E402
import page_citations as PCIT  # noqa: E402
import page_corpus as PC  # noqa: E402
import rag_text as T  # noqa: E402
from m2c_orchestrator import route_to_page as _orch_route_to_page, select_top_ranked  # noqa: E402
from rag_context import DEFAULT_BUDGET_TOKENS, DEFAULT_MAX_CHUNKS, build_context  # noqa: E402
from rag_generate import NO_ANSWER_TEXT, ExtractiveGenerator, verify_grounding  # noqa: E402

_CARD_OPEN_LOCK = threading.Lock()
MAX_PAGE_TEXTS_CACHE = 64


class _PrecomputedQueryBackend:
    """Per-request adapter supplying a precomputed query embedding to ChromaCardBackend
    without mutating shared backend state or recomputing the query embedding."""

    def __init__(self, inner: Any, query_embedding: Optional[Any]) -> None:
        self.inner = inner
        self.query_embedding = query_embedding
        self.distance_metric = getattr(inner, "distance_metric", "cosine")

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def query(self, query: str, n_results: int) -> Mapping[str, Any]:
        if self.query_embedding is not None and hasattr(self.inner, "_open"):
            from m2c_router import CardStoreUnavailable
            if getattr(self.inner, "_collection", None) is None:
                with _CARD_OPEN_LOCK:
                    collection = self.inner._open()
            else:
                collection = self.inner._open()
            n = min(int(n_results), int(collection.count()))
            if n < 1:
                raise CardStoreUnavailable(f"collection {self.inner.collection_name!r} is empty")
            vec = (
                self.query_embedding[0]
                if isinstance(self.query_embedding, (list, tuple))
                and self.query_embedding
                and isinstance(self.query_embedding[0], (list, tuple))
                else self.query_embedding
            )
            return collection.query(
                query_embeddings=[[float(x) for x in vec]],
                n_results=n,
                include=["metadatas", "distances"],
            )
        return self.inner.query(query, n_results)


def route_to_page(
    query: str,
    backend: Any,
    page_index: Any,
    top_k: int = 10,
    selector: Any = select_top_ranked,
    query_embedding: Optional[Any] = None,
) -> Any:
    req_backend = _PrecomputedQueryBackend(backend, query_embedding) if query_embedding is not None else backend
    return _orch_route_to_page(query, req_backend, page_index, top_k=top_k, selector=selector)

SCHEMA_VERSION = "8.1"
ANSWERED, INSUFFICIENT, UNRESOLVED, NOT_INGESTED, OUT_OF_DOMAIN, NO_PAGE = ("answered", "insufficient_context", "unresolved_identity", "page_not_ingested",
                                                                           "out_of_domain", "no_relevant_page")
STATUSES = (ANSWERED, INSUFFICIENT, UNRESOLVED, NOT_INGESTED, OUT_OF_DOMAIN, NO_PAGE)
OOD_MIN_COVERAGE = 0.25               # pre-declared: share of question content terms found in the routed card text (+ page text if ingested)
CONTEXT_MIN_COVERAGE = 0.5            # pre-declared: share of question content terms found in the retrieved context (+ page title/headings)
ACTIVE_INDUSTRY_CONTEXT = "SAP Utilities/IS-U"

# A deterministic second retrieval view used only by the scoped "elaborate" pass. The resolved question stays at
# the front of the query; the suffix broadens which facets of that SAME page are considered without using the word
# "elaborate" as a search query or leaving the identity-constrained retriever.
_ELABORATION_ASPECT_SUFFIX = "prerequisites conditions process steps inputs outputs results rules exceptions"


def _elaboration_aspect_query(anchor: str) -> str:
    topic = " ".join(str(anchor or "").split())
    return f"{topic} {_ELABORATION_ASPECT_SUFFIX}".strip()


def _interleave_page_candidates(primary: Sequence[Any], aspect: Sequence[Any], limit: int) -> List[Any]:
    """Merge two ranked views of one page, reserving pool slots for aspect-only chunks when available."""
    limit = max(1, int(limit))

    def unique_hits(source: Sequence[Any], already_seen: Optional[set] = None) -> List[Any]:
        seen = set(already_seen or ())
        out: List[Any] = []
        for index, hit in enumerate(source):
            chunk_id = str(getattr(hit, "chunk_id", "") or "")
            key = chunk_id or (getattr(hit, "guide_id", None), getattr(hit, "page_id", None), index, id(hit))
            if key in seen:
                continue
            seen.add(key)
            out.append(hit)
        return out

    anchor_unique = unique_hits(primary)
    anchor_keys = {str(getattr(hit, "chunk_id", "") or "") for hit in anchor_unique}
    aspect_unique = unique_hits(aspect, anchor_keys)
    merged: List[Any] = []
    for rank in range(max(len(anchor_unique), len(aspect_unique))):
        for view in (anchor_unique, aspect_unique):
            if rank < len(view):
                merged.append(replace(view[rank], rank=len(merged) + 1))
                if len(merged) >= limit:
                    return merged
    return merged


@dataclass(frozen=True)
class PipelineConfig:
    top_k_cards: int = 10
    k_chunks: int = 5
    context_budget_tokens: int = DEFAULT_BUDGET_TOKENS
    max_context_chunks: int = DEFAULT_MAX_CHUNKS
    ood_min_coverage: float = OOD_MIN_COVERAGE
    context_min_coverage: float = CONTEXT_MIN_COVERAGE
    rerank_router: bool = True
    code_aware_router: bool = False
    in_page_grounding: bool = False
    citation_normalization: bool = False
    relaxed_context_gate: bool = False
    evidence_frame_normalization: bool = False
    phase16_context_experiment: bool = False
    # Phase 18 (experimental, OFF by default; adopted only if the Phase 18 adoption rules pass):
    phrase_reranker: bool = False          # E1a: unique-phrase channel in the Phase 13 reranker (0.10 weight)
    phrase_min_corroboration: int = 1      # E1a-v2: unique phrases a page must own before it earns the channel (1 = run-1 behaviour)
    full_page_coverage: bool = False       # E1b: reranker coverage over the candidate's full page text
    citation_repair: bool = False          # E2: deterministic in-page marker repair after grounding
    # Elaboration-only dual-view retrieval; both flags are OFF/zero on every normal QA request.
    elaboration_candidate_pool_size: int = 0
    elaboration_retrieval_enabled: bool = False
    # Phase 19B (optional Ollama generation tuning knobs; None = default rag_core options):
    ollama_num_predict: Optional[int] = None
    ollama_keep_alive: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


MESSAGES = {
    OUT_OF_DOMAIN: "This question does not appear to be about the SAP Utilities topics covered by the reference cards, so no answer is given.",
    NO_PAGE: "No topic could be identified for an empty question.",
    INSUFFICIENT: NO_ANSWER_TEXT,
}


class PageCorpusIndex:
    """Which cards have admitted page text (from ``data/page_corpus/manifest.json``); a card absent here is never answerable."""

    def __init__(self, manifest: Mapping[str, Any], corpus_dir: Optional[Path] = None) -> None:
        self.entries = {c["source_id"]: dict(c) for c in manifest["cards"]}
        self.corpus_sha256 = manifest["corpus_sha256"]
        self.corpus_dir = Path(corpus_dir or PC.CORPUS_DIR)
        self._page_texts: Dict[str, str] = {}
        self._page_texts_lower: Dict[str, str] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_dir(cls, out_dir: Path = PC.CORPUS_DIR) -> "PageCorpusIndex":
        import json
        return cls(json.loads((out_dir / "manifest.json").read_text(encoding="utf-8")), corpus_dir=out_dir)

    def entry(self, source_id: str) -> Optional[Dict[str, Any]]:
        e = self.entries.get(source_id)
        return dict(e) if e is not None else None

    def page_text(self, source_id: str) -> str:
        key = str(source_id)
        cached = self._page_texts.get(key)
        if cached is not None:
            return cached
        with self._lock:
            if key in self._page_texts:
                return self._page_texts[key]
        entry = self.entries.get(key) or {}
        rec = entry.get("record")
        txt = ""
        if rec and (self.corpus_dir / rec).is_file():
            import json
            try:
                txt = str(json.loads((self.corpus_dir / rec).read_text(encoding="utf-8")).get("text", "") or "")
            except Exception:
                txt = ""
        txt_low = txt.lower()
        with self._lock:
            if len(self._page_texts) < MAX_PAGE_TEXTS_CACHE or key in self._page_texts:
                self._page_texts[key] = txt
                self._page_texts_lower[key] = txt_low
        return txt

    def page_text_lower(self, source_id: str) -> str:
        key = str(source_id)
        cached = self._page_texts_lower.get(key)
        if cached is not None:
            return cached
        return self.page_text(key).lower()


def _identity_value(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _active_topic_consistency(expected_topic: Optional[Mapping[str, Any]], source_id: str, identity: Any) -> Optional[Dict[str, Any]]:
    """Compare a newly routed topic with the successfully answered topic that owns this follow-up.

    This gate is intentionally independent of grounding: valid evidence from a different card/page is still the wrong
    answer. The production corpus is SAP Utilities, so its industry label is checked as part of the same state tuple.
    """
    if expected_topic is None:
        return None
    expected_identity = expected_topic.get("identity") if isinstance(expected_topic.get("identity"), Mapping) else expected_topic
    expected = {
        "source_id": str(expected_identity.get("source_id") or ""),
        "title": str(expected_identity.get("title") or ""),
        "guide_id": str(expected_identity.get("guide_id") or ""),
        "page_id": str(expected_identity.get("page_id") or ""),
        "industry": str(expected_identity.get("industry") or ""),
    }
    actual = {
        "source_id": str(source_id or ""),
        "title": str(getattr(identity, "card_title", "") or ""),
        "guide_id": str(getattr(identity, "effective_guide_id", "") or ""),
        "page_id": str(getattr(identity, "effective_page_id", "") or ""),
        "industry": ACTIVE_INDUSTRY_CONTEXT,
    }
    mismatches = []
    for field in ("source_id", "guide_id", "page_id", "industry"):
        if not expected[field] or _identity_value(expected[field]) != _identity_value(actual[field]):
            mismatches.append(field)
    if expected["title"] and _identity_value(expected["title"]) != _identity_value(actual["title"]):
        mismatches.append("title")
    return {"ok": not mismatches, "expected": expected, "actual": actual, "mismatches": mismatches}


def _citation_context_after_scope(context: Any, generation_evidence: Any) -> Any:
    """Apply scoped elaboration's rejected source markers to grounding and citation construction only.

    The request's original context remains intact for retrieval/debug/support-chain auditing. The generator has already
    selected only allowed units; this narrower view prevents rejected industry, all-fragment, or fully repeated-evidence
    markers from being accepted by grounding or appearing in answer_sources/context_not_cited. With no scoped exclusions
    it is an identity operation. The unchanged support-chain verifier still checks answer lines against the original
    evidence context.
    """
    evidence = generation_evidence if isinstance(generation_evidence, Mapping) else {}
    industry_scope = evidence.get("industry_scope") or {}
    quality_filter = evidence.get("quality_filter") or {}
    novelty_filter = evidence.get("novelty_filter") or {}
    topic_consistency = evidence.get("topic_consistency") or {}
    excluded_markers = {
        str(marker)
        for marker in (*industry_scope.get("excluded_markers", ()), *quality_filter.get("excluded_markers", ()),
                       *novelty_filter.get("excluded_markers", ()), *topic_consistency.get("excluded_markers", ()))
        if marker
    }
    if not excluded_markers:
        return context
    filtered = copy.copy(context)
    filtered.items = [item for item in context.items if str(item.marker) not in excluded_markers]
    return filtered


class RagPipeline:
    def __init__(self, card_backend: Any, retriever: Any, ctx: "pid.IdentityContext", corpus: PageCorpusIndex, generator: Any, count_tokens: Any,
                 cards: Optional[Sequence[Mapping[str, Any]]] = None, config: Optional[PipelineConfig] = None) -> None:
        self.backend, self.retriever, self.ctx, self.corpus = card_backend, retriever, ctx, corpus
        self.generator = generator
        self.count_tokens = count_tokens
        self.cfg = config or PipelineConfig()
        self.cards = {c["source_id"]: dict(c) for c in (cards if cards is not None else pid.load_cards(ctx.root if hasattr(ctx, "root") else PC.ROOT))}

    def _inject_code_aware_candidates(
        self,
        query: str,
        dense_candidates: Sequence[Any],
        query_embedding: Optional[Any] = None,
    ) -> List[Any]:
        """Phase 15: If query contains technical codes or discriminative phrases matching page text,
        inject matching cards into the candidate pool (replacing lowest-ranked dense candidates to keep pool <= top_k_cards).
        """
        import re
        import m2c_router as rt

        GENERIC_WORDS = frozenset({"transaction", "business", "function", "process", "billing", "customer", "system", "utilities", "order", "detail", "display", "standard"})
        EXCLUDED_CODES = frozenset({"SAP", "IS", "SYSTEM", "THE", "AND", "FOR", "NOT"})

        raw_codes = {c.upper() for c in T.code_tokens(query) if c.upper() not in EXCLUDED_CODES}

        # Multi-word technical phrases
        words = [w.lower() for w in re.findall(r'[a-z0-9_-]+', query) if w.lower() not in T.STOPWORDS and len(w) > 2]
        candidate_phrases = []
        for n in (3, 2):
            for i in range(len(words) - n + 1):
                ngram = words[i:i+n]
                if all(w in GENERIC_WORDS for w in ngram):
                    continue
                candidate_phrases.append(" ".join(ngram))

        if hasattr(self.corpus, "page_text_lower"):
            page_texts = {sid: self.corpus.page_text_lower(sid) for sid in self.corpus.entries if self.corpus.page_text_lower(sid)}
        else:
            page_texts = {sid: self.corpus.page_text(sid).lower() for sid in self.corpus.entries if self.corpus.page_text(sid)}

        matched_sids: List[str] = []

        # 1. Code matches (highest precision)
        for sid in sorted(page_texts.keys()):
            ptxt = page_texts[sid]
            if any(re.search(r'\b' + re.escape(c.lower()) + r'\b', ptxt) for c in raw_codes):
                if sid not in matched_sids:
                    matched_sids.append(sid)

        # 2. Discriminative phrase matches (phrase occurs in 1 or 2 pages)
        for phrase in candidate_phrases:
            matching = [sid for sid in sorted(page_texts.keys()) if phrase in page_texts[sid]]
            if 1 <= len(matching) <= 2:
                for s in matching:
                    if s not in matched_sids:
                        matched_sids.append(s)

        current_pool_sids = {c.source_id for c in dense_candidates}
        to_inject = [sid for sid in matched_sids if sid not in current_pool_sids]
        if not to_inject:
            return list(dense_candidates)

        # Query all cards to obtain properly normalized CardCandidate objects with true Chroma distances
        req_backend = _PrecomputedQueryBackend(self.backend, query_embedding) if query_embedding is not None else self.backend
        all_raw = req_backend.query(query.strip(), len(self.cards))
        all_candidates_by_id = {}
        for i, (cid, meta, dist) in enumerate(zip(all_raw["ids"][0], all_raw["metadatas"][0], all_raw["distances"][0]), start=1):
            all_candidates_by_id[meta["source_id"]] = rt.normalize_candidate(i, cid, meta, dist)

        pool = list(dense_candidates)
        for sid in to_inject:
            if sid in all_candidates_by_id:
                cand = all_candidates_by_id[sid]
                if len(pool) >= self.cfg.top_k_cards:
                    pool.pop()  # Replace lowest-ranked dense candidate
                pool.append(cand)

        return pool

    # ------------------------------------------------------------------------------------------------------------
    def answer(self, query: str, debug: bool = False, oracle_source_id: Optional[str] = None,
               expected_topic: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        """``oracle_source_id`` is evaluation-only; ``expected_topic`` is the active-state gate for a user follow-up."""
        t0 = time.perf_counter()
        if hasattr(self.generator, "reset_request_state"):
            self.generator.reset_request_state()
        if hasattr(self.retriever, "reset_request_state"):
            self.retriever.reset_request_state()
        timings: Dict[str, float] = {}
        dbg: Dict[str, Any] = {"config": self.cfg.to_dict(), "oracle_routing": oracle_source_id is not None}
        out: Dict[str, Any] = {"schema_version": SCHEMA_VERSION, "query": query, "status": None, "answer": None, "reason_code": None, "message": None,
                               "topic": None, "citations": {"topic_pointer": None, "answer_sources": [], "context_not_cited": [], "label": PCIT.LABEL_NONE, "notes": []},
                               "routing": {"selected_source_id": None, "candidates": [], "mode": "oracle" if oracle_source_id else "router_rank1"}}

        # ---- 1. card routing -------------------------------------------------------------------------------
        t = time.perf_counter()
        card: Any = None
        q_emb: Any = None
        rerank_hits_cache: Dict[Any, Any] = {}
        if oracle_source_id:
            card = self.cards.get(oracle_source_id)
            if card is None:
                raise KeyError(f"unknown card {oracle_source_id}")
        else:
            retrieval_query = query.strip() if query else ""
            try:
                import rag_completeness as RC
                if RC.is_intent_aware_enabled():
                    retrieval_query = RC.normalize_retrieval_query(query)
            except Exception:
                pass
            if retrieval_query and hasattr(self.retriever, "embed"):
                q_emb = self.retriever.embed([retrieval_query])
            outcome = route_to_page(
                query,
                self.backend,
                self.ctx.page_index,
                top_k=self.cfg.top_k_cards,
                selector=select_top_ranked,
                query_embedding=q_emb,
            )
            candidates = list(outcome.candidates)
            if getattr(self.cfg, "code_aware_router", False):
                candidates = self._inject_code_aware_candidates(query, candidates, query_embedding=q_emb)

            if getattr(self.cfg, "rerank_router", False) and candidates:
                import phase13_reranker as PR13
                if q_emb is None and hasattr(self.retriever, "embed"):
                    q_emb = self.retriever.embed([query])
                card, scored = PR13.rerank_candidates(
                    query,
                    candidates,
                    self.cards,
                    self.retriever,
                    self.ctx,
                    self.corpus,
                    top_k_evaluate=self.cfg.top_k_cards,
                    query_embedding=q_emb,
                    code_aware=getattr(self.cfg, "code_aware_router", False),
                    phrase_reranker=getattr(self.cfg, "phrase_reranker", False),
                    phrase_min_corroboration=getattr(self.cfg, "phrase_min_corroboration", 1),
                    full_page_coverage=getattr(self.cfg, "full_page_coverage", False),
                    k_chunks=self.cfg.k_chunks,
                    hits_out=rerank_hits_cache,
                )
                mode_str = f"router_reranked_top{self.cfg.top_k_cards}"
                if getattr(self.cfg, "code_aware_router", False):
                    mode_str += "_code_aware"
                out["routing"]["mode"] = mode_str
                out["routing"]["candidates"] = [s.to_dict() for s in scored]
            else:
                out["routing"]["candidates"] = [{"rank": c.rank, "source_id": c.source_id, "title": c.title, "similarity": round(1.0 - c.distance, 4),
                                                 "distance": round(c.distance, 6)} for c in candidates]
                card = candidates[0] if candidates else None
            dbg["routing_outcome_state_7a"] = outcome.state
        timings["route_ms"] = (time.perf_counter() - t) * 1000
        if card is None:
            return self._finish(out, NO_PAGE, "EMPTY_OR_UNROUTABLE_QUERY", MESSAGES[NO_PAGE], dbg, debug, timings, t0)
        sid = card["source_id"] if isinstance(card, Mapping) else card.source_id
        out["routing"]["selected_source_id"] = sid

        # ---- 2. identity ----------------------------------------------------------------------------------
        identity = pid.resolve_identity(card, self.ctx)
        entry = self.corpus.entry(sid) or {}
        out["topic"] = self._topic(identity, entry)
        dbg["identity"] = identity.to_dict()
        dbg["corpus_entry"] = {k: entry.get(k) for k in ("corpus_status", "reason", "doc_id", "text_sha256")}

        # A follow-up must stay on the exact active card and resolved page before any second retrieval or generation.
        # This is a topic-consistency gate, not a grounding check: a well-grounded answer from another SAP page is wrong.
        topic_consistency = _active_topic_consistency(expected_topic, sid, identity)
        if topic_consistency is not None:
            dbg["topic_consistency"] = topic_consistency
            if not topic_consistency["ok"]:
                out["topic"] = {}  # do not surface the incorrectly routed page as a topic reference
                out["citations"] = {"topic_pointer": None, "answer_sources": [], "context_not_cited": [],
                                    "label": PCIT.LABEL_NONE, "notes": []}
                return self._finish(out, INSUFFICIENT, "ACTIVE_TOPIC_MISMATCH", MESSAGES[INSUFFICIENT], dbg, debug, timings, t0)

        out["citations"] = PCIT.build_citations(card, identity, self.ctx, corpus_entry=entry)

        # ---- 3. lexical topic gate (heuristic; see module docstring) -------------------------------------------------
        qterms = T.terms(query)
        card_text = str(self.cards.get(sid, {}).get("embedding_text") or "")
        page_chunks: List[Any] = []
        ingested = entry.get("corpus_status") == PC.S_INGESTED and identity.effective_guide_id and identity.effective_page_id
        if ingested:
            page_chunks = self.retriever.page_chunks(identity.effective_guide_id, identity.effective_page_id)
        topic_text = card_text + "\n" + "\n".join(f"{h.title} {' '.join(h.heading_path)} {h.text}" for h in page_chunks)
        cov = T.coverage(qterms, topic_text)
        dbg["gate_topic"] = {"query_terms": qterms, "coverage": round(cov, 3), "min": self.cfg.ood_min_coverage}
        if not qterms or cov < self.cfg.ood_min_coverage:
            return self._finish(out, OUT_OF_DOMAIN, "LOW_QUERY_TERM_COVERAGE_VS_ROUTED_TOPIC", MESSAGES[OUT_OF_DOMAIN], dbg, debug, timings, t0)

        # ---- 4. identity / corpus admission ------------------------------------------------------------------------
        if identity.resolution_status in (pid.CONFLICTING_IDENTITY, pid.CARD_IDENTITY_ONLY, pid.UNRESOLVED) or not identity.effective_page_id:
            msg = {pid.CONFLICTING_IDENTITY: "The reference for this topic carries conflicting identifiers, so no page is chosen and no answer is generated. "
                                             "The conflict is shown below, unresolved.",
                   pid.CARD_IDENTITY_ONLY: "The topic was identified, but the guide of its SAP Help page is not verified, so no page can be used and no answer is generated."
                   }.get(identity.resolution_status, "The page identity of this topic is not established, so no answer is generated.")
            return self._finish(out, UNRESOLVED, identity.resolution_status.upper(), msg, dbg, debug, timings, t0)
        if not ingested:
            return self._finish(out, NOT_INGESTED, "PAGE_IDENTIFIED_NO_LOCAL_CONTENT",
                                f"The topic was identified as \"{identity.card_title}\" ({sid}) and its SAP Help page is known, but the page text is not available "
                                "in this system, so no answer is generated. Use the reference link.", dbg, debug, timings, t0)

        # ---- 5. identity-constrained retrieval -------------------------------------------------------------------------
        t = time.perf_counter()
        elaboration_pool_size = max(0, int(getattr(self.cfg, "elaboration_candidate_pool_size", 0) or 0))
        elaboration_retrieval_enabled = bool(getattr(self.cfg, "elaboration_retrieval_enabled", False))
        if elaboration_retrieval_enabled and elaboration_pool_size:
            # The card reranker already fetched the anchor-query page hits (and cached them) at k_chunks. Reuse that
            # ranked view, then add one deterministic aspect-oriented query under the exact same guide/page identity.
            # Alternating the two ranked lists preserves the anchor retrieval while allowing lower-ranked, novel
            # page evidence to enter the bounded candidate pool.
            anchor_cache_key = (identity.effective_guide_id, identity.effective_page_id, self.cfg.k_chunks)
            if anchor_cache_key in rerank_hits_cache:
                anchor_hits = list(rerank_hits_cache[anchor_cache_key][:elaboration_pool_size])
            else:
                anchor_hits = self.retriever.retrieve_in_page(
                    query,
                    identity.effective_guide_id,
                    identity.effective_page_id,
                    top_k=elaboration_pool_size,
                    query_embedding=q_emb,
                )
            aspect_query = _elaboration_aspect_query(query)
            aspect_embedding = self.retriever.embed([aspect_query]) if hasattr(self.retriever, "embed") else None
            aspect_hits = self.retriever.retrieve_in_page(
                aspect_query,
                identity.effective_guide_id,
                identity.effective_page_id,
                top_k=elaboration_pool_size,
                query_embedding=aspect_embedding,
            )
            hits = _interleave_page_candidates(anchor_hits, aspect_hits, elaboration_pool_size)
            dbg["retrieval"] = {
                "scope": "resolved_active_page",
                "strategy": "topic_anchor_plus_aspect_query",
                "anchor_query": query,
                "aspect_query": aspect_query,
                "guide_id": identity.effective_guide_id,
                "page_id": identity.effective_page_id,
                "pool_limit": elaboration_pool_size,
                "anchor_candidates": len(anchor_hits),
                "aspect_candidates": len(aspect_hits),
                "unique_candidates_before_limit": len({str(getattr(h, "chunk_id", "")) for h in (*anchor_hits, *aspect_hits)}),
                "candidates_returned": len(hits),
                "page_expansion": "disabled",
            }
        else:
            win_page_key_k = (identity.effective_guide_id, identity.effective_page_id, self.cfg.k_chunks)
            if win_page_key_k in rerank_hits_cache:
                hits = list(rerank_hits_cache[win_page_key_k][: self.cfg.k_chunks])
            else:
                hits = self.retriever.retrieve_in_page(
                    query,
                    identity.effective_guide_id,
                    identity.effective_page_id,
                    top_k=self.cfg.k_chunks,
                    query_embedding=q_emb,
                )
        timings["retrieve_ms"] = (time.perf_counter() - t) * 1000
        dbg["retrieved"] = [h.to_dict(with_text=False) for h in hits]
        if not hits:
            return self._finish(out, NOT_INGESTED, "PAGE_MISSING_FROM_VECTOR_STORE", "The page is registered but has no chunks in the page index.", dbg, debug, timings, t0)

        # ---- 6. context -------------------------------------------------------------------------------------------
        t = time.perf_counter()
        context = build_context(hits, self.count_tokens, self.cfg.context_budget_tokens, self.cfg.max_context_chunks)
        timings["context_ms"] = (time.perf_counter() - t) * 1000
        dbg["context"] = context.to_dict(with_text=True)
        ctx_text = "\n".join(f"{' '.join(i.heading_path)} {i.rendered_text}" for i in context.items)
        ccov = T.coverage(qterms, ctx_text)
        relaxed_gate = getattr(self.cfg, "relaxed_context_gate", False) or getattr(self.cfg, "phase16_context_experiment", False)
        ccov_min = 0.25 if relaxed_gate else self.cfg.context_min_coverage
        dbg["gate_context"] = {"coverage": round(ccov, 3), "min": ccov_min}
        if ccov < ccov_min:
            out["citations"] = PCIT.build_citations(card, identity, self.ctx, context, None, entry)
            return self._finish(out, INSUFFICIENT, "LOW_QUERY_TERM_COVERAGE_IN_CONTEXT", MESSAGES[INSUFFICIENT], dbg, debug, timings, t0)

        # ---- 7. generation + verification ------------------------------------------------------------------------------
        t = time.perf_counter()
        gen = self.generator.generate(query, context)
        timings["generate_ms"] = (time.perf_counter() - t) * 1000
        in_page = getattr(self.cfg, "in_page_grounding", False) or getattr(self.cfg, "phase16_context_experiment", False)
        cit_norm = getattr(self.cfg, "citation_normalization", False) or getattr(self.cfg, "phase16_context_experiment", False)
        generation_evidence = getattr(gen, "evidence", None)
        citation_context = _citation_context_after_scope(context, generation_evidence)
        report = verify_grounding(gen.text, citation_context, in_page_grounding=in_page, citation_normalization=cit_norm)
        dbg["generation"] = {"generator": gen.generator, "refused": gen.refused, "raw_text": gen.raw_text, "prompt": gen.prompt}
        if getattr(gen, "telemetry", None):
            dbg["generation"]["telemetry"] = dict(gen.telemetry)
            if "queue_wait_ms" in gen.telemetry:
                timings["queue_wait_ms"] = float(gen.telemetry["queue_wait_ms"])
        if getattr(gen, "evidence", None) is not None:
            dbg["evidence"] = gen.evidence
        dbg["grounding"] = report.to_dict()
        if gen.refused or report.refusal:
            out["citations"] = PCIT.build_citations(card, identity, self.ctx, citation_context, None, entry)
            return self._finish(out, INSUFFICIENT, "GENERATOR_REFUSED", MESSAGES[INSUFFICIENT], dbg, debug, timings, t0)
        if not report.ok:
            out["citations"] = PCIT.build_citations(card, identity, self.ctx, citation_context, None, entry)
            dbg["answer_withheld"] = gen.text
            return self._finish(out, INSUFFICIENT, "GROUNDING_VERIFICATION_FAILED", MESSAGES[INSUFFICIENT] + " (a generated answer was withheld because it failed the grounding check)",
                                dbg, debug, timings, t0)

        # ---- 7b. Phase 18 (E2): deterministic in-page citation repair (flag OFF => no-op) --------------------
        # Only markers change, never content. The repaired text must pass the SAME verifier; otherwise the
        # original (already verified) answer is kept. Worst case is the status quo.
        repaired_text = gen.text
        if getattr(self.cfg, "citation_repair", False):
            import rag_citation_repair as CRC
            repaired_text, repair_log = CRC.repair_citations(gen.text, citation_context, citation_normalization=bool(cit_norm))
            if repair_log.get("changed"):
                repaired_report = verify_grounding(repaired_text, citation_context, in_page_grounding=in_page, citation_normalization=cit_norm)
                if repaired_report.ok and not repaired_report.refusal:
                    report = repaired_report
                else:
                    repair_log["revert"] = "REPAIR_FAILED_VERIFICATION"
                    repaired_text = gen.text
            dbg["citation_repair"] = repair_log

        out["answer"] = repaired_text
        out["citations"] = PCIT.build_citations(card, identity, self.ctx, citation_context, report, entry)
        return self._finish(out, ANSWERED, None, None, dbg, debug, timings, t0)

    # ------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _topic(identity: "pid.PageIdentity", entry: Mapping[str, Any]) -> Dict[str, Any]:
        return {"source_id": identity.source_id, "title": identity.card_title, "card_url": identity.card_url, "identity_status": identity.resolution_status,
                "effective_guide_id": identity.effective_guide_id, "effective_page_id": identity.effective_page_id, "review_flag": identity.card_needs_review,
                "corrected_identity": bool(identity.effective_guide_id and identity.card_guide_id and identity.effective_guide_id != identity.card_guide_id),
                "corpus_status": entry.get("corpus_status")}

    def _finish(self, out: Dict[str, Any], status: str, reason: Optional[str], message: Optional[str], dbg: Dict[str, Any], debug: bool,
                timings: Dict[str, float], t0: float) -> Dict[str, Any]:
        out["status"], out["reason_code"], out["message"] = status, reason, message
        assert status in STATUSES
        topic = out.get("topic") or {}
        badges = [f"status:{status}"]
        if topic.get("review_flag"):
            badges.append("card:needs_review")
        if topic.get("corrected_identity"):
            badges.append("identity:corrected")
        if topic.get("identity_status"):
            badges.append(f"identity:{topic['identity_status']}")
        out["ui"] = {"headline": {ANSWERED: "Answer", INSUFFICIENT: "Not enough information", UNRESOLVED: "Page identity not established",
                                  NOT_INGESTED: "Page not available here", OUT_OF_DOMAIN: "Out of scope", NO_PAGE: "No topic"}[status],
                     "text": out["answer"] if status == ANSWERED else message, "badges": badges,
                     "sources": [{"marker": s["marker"], "title": s["title"], "section": " > ".join(s["heading_path"]), "url": s["url"]}
                                 for s in out["citations"]["answer_sources"]],
                     "topic_reference": ({"title": topic.get("title"), "url": topic.get("card_url"), "note": "topic pointer, not answer evidence"} if topic else None)}
        timings["total_ms"] = (time.perf_counter() - t0) * 1000
        out["timings_ms"] = {k: round(v, 2) for k, v in timings.items()}
        if debug:
            out["debug"] = dbg
        return out


def format_answer(a: Mapping[str, Any]) -> str:
    lines = [f"[{a['status']}] {a['ui']['headline']}"]
    lines.append(a["answer"] if a["status"] == ANSWERED else (a["message"] or ""))
    if a.get("topic"):
        lines.append(PCIT.format_answer_sources(a["citations"]))
    return "\n".join(lines)


def build_pipeline(generator: str = "extractive", llm_client: Any = None, config: Optional[PipelineConfig] = None, root: Path = PC.ROOT) -> RagPipeline:
    """Wire the real components (needs the card store, the page store and the embedding weights; nothing is downloaded)."""
    import build_page_collection as BP
    import m2c_router as rt
    import page_chunker as PK
    import page_retriever as PR
    from rag_generate import LLMGenerator, OllamaClient
    embed, minfo = BP.load_embedder()
    count, _ = PK.make_token_counter(minfo["model_dir"])
    backend = rt.ChromaCardBackend(embedder=embed)
    retriever = PR.PageRetriever.from_store(embed=embed)
    ctx = pid.IdentityContext.from_root(root)
    client = llm_client
    if generator != "extractive" and client is None:
        client = OllamaClient(
            num_predict=getattr(config, "ollama_num_predict", None),
            keep_alive=getattr(config, "ollama_keep_alive", None),
        )
    gen = ExtractiveGenerator() if generator == "extractive" else LLMGenerator(client, name="ollama" if llm_client is None else "llm")
    return RagPipeline(backend, retriever, ctx, PageCorpusIndex.from_dir(), gen, count, config=config)
