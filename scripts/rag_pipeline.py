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

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import m2c_page_identity as pid  # noqa: E402
import page_citations as PCIT  # noqa: E402
import page_corpus as PC  # noqa: E402
import rag_text as T  # noqa: E402
from m2c_orchestrator import route_to_page, select_top_ranked  # noqa: E402
from rag_context import DEFAULT_BUDGET_TOKENS, DEFAULT_MAX_CHUNKS, build_context  # noqa: E402
from rag_generate import NO_ANSWER_TEXT, ExtractiveGenerator, verify_grounding  # noqa: E402

SCHEMA_VERSION = "8.1"
ANSWERED, INSUFFICIENT, UNRESOLVED, NOT_INGESTED, OUT_OF_DOMAIN, NO_PAGE = ("answered", "insufficient_context", "unresolved_identity", "page_not_ingested",
                                                                           "out_of_domain", "no_relevant_page")
STATUSES = (ANSWERED, INSUFFICIENT, UNRESOLVED, NOT_INGESTED, OUT_OF_DOMAIN, NO_PAGE)
OOD_MIN_COVERAGE = 0.25               # pre-declared: share of question content terms found in the routed card text (+ page text if ingested)
CONTEXT_MIN_COVERAGE = 0.5            # pre-declared: share of question content terms found in the retrieved context (+ page title/headings)


@dataclass(frozen=True)
class PipelineConfig:
    top_k_cards: int = 5
    k_chunks: int = 5
    context_budget_tokens: int = DEFAULT_BUDGET_TOKENS
    max_context_chunks: int = DEFAULT_MAX_CHUNKS
    ood_min_coverage: float = OOD_MIN_COVERAGE
    context_min_coverage: float = CONTEXT_MIN_COVERAGE

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


MESSAGES = {
    OUT_OF_DOMAIN: "This question does not appear to be about the SAP Utilities topics covered by the reference cards, so no answer is given.",
    NO_PAGE: "No topic could be identified for an empty question.",
    INSUFFICIENT: NO_ANSWER_TEXT,
}


class PageCorpusIndex:
    """Which cards have admitted page text (from ``data/page_corpus/manifest.json``); a card absent here is never answerable."""

    def __init__(self, manifest: Mapping[str, Any]) -> None:
        self.entries = {c["source_id"]: dict(c) for c in manifest["cards"]}
        self.corpus_sha256 = manifest["corpus_sha256"]

    @classmethod
    def from_dir(cls, out_dir: Path = PC.CORPUS_DIR) -> "PageCorpusIndex":
        import json
        return cls(json.loads((out_dir / "manifest.json").read_text(encoding="utf-8")))

    def entry(self, source_id: str) -> Optional[Dict[str, Any]]:
        return self.entries.get(source_id)


class RagPipeline:
    def __init__(self, card_backend: Any, retriever: Any, ctx: "pid.IdentityContext", corpus: PageCorpusIndex, generator: Any, count_tokens: Any,
                 cards: Optional[Sequence[Mapping[str, Any]]] = None, config: Optional[PipelineConfig] = None) -> None:
        self.backend, self.retriever, self.ctx, self.corpus = card_backend, retriever, ctx, corpus
        self.generator = generator
        self.count_tokens = count_tokens
        self.cfg = config or PipelineConfig()
        self.cards = {c["source_id"]: dict(c) for c in (cards if cards is not None else pid.load_cards(ctx.root if hasattr(ctx, "root") else PC.ROOT))}

    # ------------------------------------------------------------------------------------------------------------
    def answer(self, query: str, debug: bool = False, oracle_source_id: Optional[str] = None) -> Dict[str, Any]:
        """``oracle_source_id`` bypasses the router (evaluation only: isolates retrieval/generation from routing errors)."""
        t0 = time.perf_counter()
        timings: Dict[str, float] = {}
        dbg: Dict[str, Any] = {"config": self.cfg.to_dict(), "oracle_routing": oracle_source_id is not None}
        out: Dict[str, Any] = {"schema_version": SCHEMA_VERSION, "query": query, "status": None, "answer": None, "reason_code": None, "message": None,
                               "topic": None, "citations": {"topic_pointer": None, "answer_sources": [], "context_not_cited": [], "label": PCIT.LABEL_NONE, "notes": []},
                               "routing": {"selected_source_id": None, "candidates": [], "mode": "oracle" if oracle_source_id else "router_rank1"}}

        # ---- 1. card routing -------------------------------------------------------------------------------
        t = time.perf_counter()
        card: Any = None
        if oracle_source_id:
            card = self.cards.get(oracle_source_id)
            if card is None:
                raise KeyError(f"unknown card {oracle_source_id}")
        else:
            outcome = route_to_page(query, self.backend, self.ctx.page_index, top_k=self.cfg.top_k_cards, selector=select_top_ranked)
            out["routing"]["candidates"] = [{"rank": c.rank, "source_id": c.source_id, "title": c.title, "similarity": round(1.0 - c.distance, 4),
                                             "distance": round(c.distance, 6)} for c in outcome.candidates]
            card = outcome.selected_card
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
        out["citations"] = PCIT.build_citations(card, identity, self.ctx, corpus_entry=entry)
        dbg["identity"] = identity.to_dict()
        dbg["corpus_entry"] = {k: entry.get(k) for k in ("corpus_status", "reason", "doc_id", "text_sha256")}

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
        hits = self.retriever.retrieve_in_page(query, identity.effective_guide_id, identity.effective_page_id, top_k=self.cfg.k_chunks)
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
        dbg["gate_context"] = {"coverage": round(ccov, 3), "min": self.cfg.context_min_coverage}
        if ccov < self.cfg.context_min_coverage:
            out["citations"] = PCIT.build_citations(card, identity, self.ctx, context, None, entry)
            return self._finish(out, INSUFFICIENT, "LOW_QUERY_TERM_COVERAGE_IN_CONTEXT", MESSAGES[INSUFFICIENT], dbg, debug, timings, t0)

        # ---- 7. generation + verification ------------------------------------------------------------------------------
        t = time.perf_counter()
        gen = self.generator.generate(query, context)
        timings["generate_ms"] = (time.perf_counter() - t) * 1000
        report = verify_grounding(gen.text, context)
        dbg["generation"] = {"generator": gen.generator, "refused": gen.refused, "raw_text": gen.raw_text, "prompt": gen.prompt}
        dbg["grounding"] = report.to_dict()
        if gen.refused or report.refusal:
            out["citations"] = PCIT.build_citations(card, identity, self.ctx, context, None, entry)
            return self._finish(out, INSUFFICIENT, "GENERATOR_REFUSED", MESSAGES[INSUFFICIENT], dbg, debug, timings, t0)
        if not report.ok:
            out["citations"] = PCIT.build_citations(card, identity, self.ctx, context, None, entry)
            dbg["answer_withheld"] = gen.text
            return self._finish(out, INSUFFICIENT, "GROUNDING_VERIFICATION_FAILED", MESSAGES[INSUFFICIENT] + " (a generated answer was withheld because it failed the grounding check)",
                                dbg, debug, timings, t0)
        out["answer"] = gen.text
        out["citations"] = PCIT.build_citations(card, identity, self.ctx, context, report, entry)
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
    gen = ExtractiveGenerator() if generator == "extractive" else LLMGenerator(llm_client or OllamaClient(), name="ollama" if llm_client is None else "llm")
    return RagPipeline(backend, retriever, ctx, PageCorpusIndex.from_dir(), gen, count, config=config)
