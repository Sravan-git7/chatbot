"""Phase 11 - service boundary between a chat front end and the existing card-first grounded RAG pipeline.

This module adds NO retrieval or routing logic. It calls ``rag_pipeline.RagPipeline.answer`` (Phases 7-10; since Phase 11.1 with the evidence-checked generator of ``rag_evidence``) and
translates its structured answer into a stable, UI-safe contract:

    answer_question(question, pipeline=..., debug=False) -> dict      # see ``ChatResult`` keys below

Contract rules (all tested in ``tests/test_phase11_service.py`` / ``tests/test_phase11_api.py``):

* ``answer`` is the pipeline's grounded answer text, verbatim, and only when the pipeline status is ``answered``. For every other status ``answer`` is a
  short fixed explanation written here (never generated text, never card text).
* ``sources`` are ONLY the pipeline's verified ``answer_sources`` (chunks that were supplied to the generator, cited, and passed the grounding verifier).
  Their URLs are copied unchanged; a URL that is not http(s) is dropped (``url`` becomes ``None``), never rewritten.
* A routed card is a topic pointer, never evidence: it is exposed separately as ``topic_reference`` (only for ``documentation_unavailable`` and
  ``unable_to_verify``), labelled as a reference and never listed in ``sources``.
* Internal ids (``M2C-18`` ...) appear only in ``metadata`` (as ``card_id``) and in ``debug``; the explanation texts never contain them.
* A generator exception is not caught into a fake answer: it is raised as ``GeneratorFailure`` and surfaced by the API as a controlled error.
* The pipeline is always run with its debug block so the grounding verdict can be preserved; the block is returned only when ``debug=True``.
"""
from __future__ import annotations

from collections import deque
import copy
import re
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

SCHEMA_VERSION = "11.1"
MAX_MESSAGE_CHARS = 2000
CONVERSATION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

ANSWERED, DOC_UNAVAILABLE, UNABLE_TO_VERIFY, OUT_OF_SCOPE = "answered", "documentation_unavailable", "unable_to_verify", "out_of_scope"
API_STATUSES = (ANSWERED, DOC_UNAVAILABLE, UNABLE_TO_VERIFY, OUT_OF_SCOPE)
# pipeline status (rag_pipeline.STATUSES) -> API status
STATUS_MAP = {"answered": ANSWERED, "page_not_ingested": DOC_UNAVAILABLE, "unresolved_identity": UNABLE_TO_VERIFY, "insufficient_context": UNABLE_TO_VERIFY,
              "out_of_domain": OUT_OF_SCOPE, "no_relevant_page": OUT_OF_SCOPE}
USER_TEXT = {
    DOC_UNAVAILABLE: "I found the relevant topic, but the underlying SAP Help page is not currently available in the local knowledge base.",
    UNABLE_TO_VERIFY: "I couldn't find enough verified information in the available SAP Utilities documentation to answer that specific detail.",
    OUT_OF_SCOPE: "This question doesn't appear to match the SAP Utilities documentation available to me.",
}
UNRESOLVED_TEXT = "I couldn't verify the relevant documentation."
REFERENCE_NOTE = "Topic reference only - not used as evidence for any answer."


class ServiceError(Exception):
    """Base class: ``code`` is a stable machine-readable string, ``message`` is safe to show."""
    code = "service_error"
    http_status = 500

    def __init__(self, message: str, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class InvalidQuestion(ServiceError):
    code, http_status = "invalid_request", 422


class NotReady(ServiceError):
    code, http_status = "service_not_ready", 503


class GeneratorFailure(ServiceError):
    code, http_status = "generator_failed", 502


class PipelineFailure(ServiceError):
    code, http_status = "pipeline_failed", 500


def clean_question(question: Any) -> str:
    """Validate and normalise a user question: a non-empty string of at most ``MAX_MESSAGE_CHARS`` characters without control characters."""
    if not isinstance(question, str):
        raise InvalidQuestion("The message must be text.")
    q = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", question).strip()
    if not q:
        raise InvalidQuestion("The message is empty.")
    if len(q) > MAX_MESSAGE_CHARS:
        raise InvalidQuestion(f"The message is too long ({len(q)} characters; the limit is {MAX_MESSAGE_CHARS}).")
    return q


def resolve_conversation_id(conversation_id: Optional[str]) -> str:
    """Echo a well-formed client id, or mint one. The service is stateless: the id only lets the client group its own messages."""
    if conversation_id is None or conversation_id == "":
        return uuid.uuid4().hex
    if not CONVERSATION_ID_RE.match(conversation_id):
        raise InvalidQuestion("conversation_id may only contain letters, digits, '-' and '_' (at most 64 characters).")
    return conversation_id


DEFAULT_GENERATION_CONCURRENCY = 1
MAX_CONCURRENT_REQUESTS = 4


class _FIFOBoundedSemaphore:
    """Fair FIFO bounded semaphore so concurrent workers acquire permits in arrival order without starvation."""

    def __init__(self, value: int = 1) -> None:
        if value < 1:
            raise ValueError("Semaphore initial value must be >= 1")
        self._value = int(value)
        self._max_value = int(value)
        self._lock = threading.Lock()
        self._waiters: deque[threading.Event] = deque()

    def acquire(self, blocking: bool = True, timeout: Optional[float] = None) -> bool:
        with self._lock:
            if self._value > 0 and not self._waiters:
                self._value -= 1
                return True
            if not blocking:
                return False
            ev = threading.Event()
            self._waiters.append(ev)
        if not ev.wait(timeout=timeout):
            with self._lock:
                if ev in self._waiters:
                    self._waiters.remove(ev)
                    return False
                return True
        return True

    def release(self) -> None:
        with self._lock:
            if self._waiters:
                ev = self._waiters.popleft()
                ev.set()
                return
            if self._value >= self._max_value:
                raise ValueError("Semaphore released too many times")
            self._value += 1

    def __enter__(self) -> "_FIFOBoundedSemaphore":
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.release()


class GeneratorGuard:
    """Wraps the pipeline's generator so that an exception inside generation is reported as ``GeneratorFailure`` (and never as any other status).
    When wrapping a raw non-extractive generator (without ``EvidenceGuard``), gates LLM calls with ``gen_sem``.
    When wrapping ``EvidenceGuard``, shares ``gen_sem`` so pre-check and post-check run outside the generation lock.
    """

    def __init__(self, inner: Any, gen_sem: Optional[threading.BoundedSemaphore] = None) -> None:
        self.inner = inner
        self.name = getattr(inner, "name", "generator")
        self._gen_sem = gen_sem
        if gen_sem is not None and hasattr(inner, "_gen_sem"):
            inner._gen_sem = gen_sem
            inner._llm_lock = gen_sem

    def reset_request_state(self) -> None:
        if hasattr(self.inner, "reset_request_state"):
            self.inner.reset_request_state()
        elif hasattr(self.inner, "last"):
            self.inner.last = None

    def generate(self, question: str, context: Any) -> Any:
        try:
            if hasattr(self.inner, "_gen_sem") or getattr(self.inner, "name", "") == "extractive" or self._gen_sem is None:
                return self.inner.generate(question, context)
            if self._gen_sem.acquire(blocking=False):
                queue_wait_ms = 0.0
            else:
                t_wait0 = time.perf_counter()
                self._gen_sem.acquire()
                queue_wait_ms = round((time.perf_counter() - t_wait0) * 1000.0, 3)
            try:
                res = self.inner.generate(question, context)
            finally:
                self._gen_sem.release()
            if hasattr(res, "telemetry"):
                raw_tel = getattr(res, "telemetry", None)
                tel = dict(raw_tel) if raw_tel is not None else {}
                tel.setdefault("queue_wait_ms", queue_wait_ms)
                res.telemetry = tel
            return res
        except Exception as e:                                       # noqa: BLE001 - re-raised as a typed, controlled failure
            raise GeneratorFailure(f"The answer generator failed ({type(e).__name__}). No answer was produced.") from e


def _safe_url(url: Any) -> Optional[str]:
    return url if isinstance(url, str) and re.match(r"^https?://", url) else None


def _source(s: Mapping[str, Any]) -> Dict[str, Any]:
    return {"type": "page", "marker": s.get("marker"), "title": s.get("title"), "section": " > ".join(s.get("heading_path") or []) or None, "url": _safe_url(s.get("url")),
            "source_id": (s.get("join") or {}).get("card_source_id"), "chunk_id": s.get("chunk_id")}


def _grounding(dbg: Mapping[str, Any], status: str) -> Dict[str, Any]:
    g = dbg.get("grounding")
    if g is None:
        return {"checked": False, "ok": None, "sentences": 0, "violations": 0, "cited_markers": []}
    return {"checked": True, "ok": bool(g["ok"]) and status == "answered", "sentences": len(g.get("sentences") or []), "violations": len(g.get("violations") or []),
            "cited_markers": list(g.get("cited_markers") or [])}


def support_chain(answer: str, dbg: Mapping[str, Any]) -> Dict[str, Any]:
    """Phase 11.1: traceability of an extractive answer - every sentence is a verbatim span of the chunk its marker names (``rag_evidence.verify_support_chain``)."""
    from types import SimpleNamespace
    import rag_evidence as EV
    items = [SimpleNamespace(marker=i["marker"], text=i["text"]) for i in ((dbg.get("context") or {}).get("items") or [])]
    return EV.verify_support_chain(answer, SimpleNamespace(items=items))


def to_chat_result(raw: Mapping[str, Any], generator: str, conversation_id: str, latency_ms: float, debug: bool = False,
                   evidence: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Translate one ``RagPipeline.answer`` dict (produced with ``debug=True``) into the public chat result."""
    pstatus = raw["status"]
    status = STATUS_MAP[pstatus]
    topic = raw.get("topic") or {}
    dbg = raw.get("debug") or {}
    if status == ANSWERED:
        answer = raw["answer"]
        sources = [_source(s) for s in raw["citations"]["answer_sources"]]
    else:
        answer = UNRESOLVED_TEXT if pstatus == "unresolved_identity" else USER_TEXT[status]
        sources = []
    reference = None
    if status in (DOC_UNAVAILABLE, UNABLE_TO_VERIFY) and pstatus != "unresolved_identity" and topic.get("title") and _safe_url(topic.get("card_url")):
        reference = {"type": "topic_reference", "title": topic["title"], "url": _safe_url(topic["card_url"]), "note": REFERENCE_NOTE}
    routed = status != OUT_OF_SCOPE
    meta = {"card_id": topic.get("source_id") if routed else None, "card_title": topic.get("title") if routed else None,
            "identity_status": topic.get("identity_status") if routed else None, "page_available": (topic.get("corpus_status") == "ingested") if routed else None, "generator": generator, "grounded": status == ANSWERED and _grounding(dbg, pstatus)["ok"] is True,
            "grounding": _grounding(dbg, pstatus), "pipeline_status": pstatus, "reason_code": raw.get("reason_code"), "latency_ms": round(latency_ms, 1)}
    out: Dict[str, Any] = {"schema_version": SCHEMA_VERSION, "conversation_id": conversation_id, "status": status, "answer": answer, "sources": sources,
                           "topic_reference": reference, "metadata": meta}
    if debug:
        out["debug"] = {"pipeline_message": raw.get("message"), "routing": raw.get("routing"), "topic": topic, "citations": raw.get("citations"), "pipeline": dbg,
                        "timings_ms": raw.get("timings_ms"), "evidence": dict(evidence) if evidence else None}
    return out


class RagService:
    """Holds one pipeline (guarded generator) with bounded request concurrency and fine-grained generation locking.
    Deterministic routing, retrieval, context construction, EvidenceGuard pre-check,
    EvidenceGuard post-check, grounding verification, and response assembly execute concurrently
    up to ``max_concurrency`` (default 4); only actual LLM generation acquires ``_gen_sem`` (default 1).
    """

    def __init__(
        self,
        pipeline: Any,
        generator: str,
        max_concurrency: int = MAX_CONCURRENT_REQUESTS,
        generation_concurrency: int = DEFAULT_GENERATION_CONCURRENCY,
        *,
        coarse_lock: bool = False,
    ) -> None:
        import rag_pipeline as RP
        self.generator_name = generator
        self.max_concurrency = max(1, int(max_concurrency))
        self.generation_concurrency = max(1, int(generation_concurrency))
        self.coarse_lock = bool(coarse_lock)
        self._request_sem = _FIFOBoundedSemaphore(self.max_concurrency)
        self._gen_sem = _FIFOBoundedSemaphore(self.generation_concurrency)
        self._lock = threading.Lock()
        self._evidence_gen = pipeline.generator
        self.pipeline = RP.RagPipeline(
            pipeline.backend,
            pipeline.retriever,
            pipeline.ctx,
            pipeline.corpus,
            GeneratorGuard(pipeline.generator, gen_sem=self._gen_sem),
            pipeline.count_tokens,
            cards=list(pipeline.cards.values()),
            config=pipeline.cfg,
        )

    def info(self) -> Dict[str, Any]:
        entries = self.pipeline.corpus.entries
        return {"generator": self.generator_name, "topics": len(self.pipeline.cards),
                "pages_available": sum(1 for e in entries.values() if e.get("corpus_status") == "ingested")}

    def _reset_request_state(self) -> None:
        if hasattr(self._evidence_gen, "reset_request_state"):
            self._evidence_gen.reset_request_state()
        elif hasattr(self._evidence_gen, "last"):
            self._evidence_gen.last = None
        if hasattr(self.pipeline.retriever, "reset_request_state"):
            self.pipeline.retriever.reset_request_state()
        elif hasattr(self.pipeline.retriever, "last_promoted"):
            self.pipeline.retriever.last_promoted = None

    def _run_pipeline_request(self, q: str, queue_wait_ms: Optional[float] = None) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        self._reset_request_state()
        raw = self.pipeline.answer(q, debug=True)
        dbg_dict = raw.get("debug")
        evidence: Optional[Dict[str, Any]] = None
        if isinstance(dbg_dict, dict) and "evidence" in dbg_dict:
            ev_raw = dbg_dict.pop("evidence", None)
            if ev_raw is not None:
                evidence = dict(ev_raw)
        elif hasattr(self._evidence_gen, "last") and self._evidence_gen.last is not None:
            evidence = dict(self._evidence_gen.last)
        timings = raw.get("timings_ms")
        if isinstance(timings, dict):
            if queue_wait_ms is not None:
                timings["queue_wait_ms"] = round(max(float(timings.get("queue_wait_ms", 0.0)), float(queue_wait_ms)), 2)
            else:
                timings.setdefault("queue_wait_ms", 0.0)
        if self.generator_name == "extractive" and raw["status"] == "answered":
            chain = support_chain(raw["answer"], raw.get("debug") or {})
            evidence = dict(evidence or {}, support_chain=chain)
            if not chain["ok"]:                                      # support cannot be established -> abstain, never "answered"
                raw = dict(raw, status="insufficient_context", answer=None, reason_code="SUPPORT_CHAIN_FAILED", citations={"answer_sources": []})
        return raw, evidence

    def ask(self, question: Any, conversation_id: Optional[str] = None, debug: bool = False) -> Dict[str, Any]:
        q = clean_question(question)
        cid = resolve_conversation_id(conversation_id)
        t0 = time.perf_counter()
        try:
            if self.coarse_lock:
                if self._lock.acquire(blocking=False):
                    q_wait = 0.0
                else:
                    t_w0 = time.perf_counter()
                    self._lock.acquire()
                    q_wait = (time.perf_counter() - t_w0) * 1000.0
                try:
                    raw, evidence = self._run_pipeline_request(q, queue_wait_ms=q_wait)
                finally:
                    self._lock.release()
            else:
                if self._request_sem.acquire(blocking=False):
                    q_wait = 0.0
                else:
                    t_w0 = time.perf_counter()
                    self._request_sem.acquire()
                    q_wait = (time.perf_counter() - t_w0) * 1000.0
                try:
                    raw, evidence = self._run_pipeline_request(q, queue_wait_ms=q_wait)
                finally:
                    self._request_sem.release()
        except ServiceError:
            raise
        except Exception as e:                                       # noqa: BLE001
            raise PipelineFailure(f"The retrieval pipeline failed ({type(e).__name__}). No answer was produced.") from e
        return to_chat_result(raw, self.generator_name, cid, (time.perf_counter() - t0) * 1000, debug=debug, evidence=evidence)


# Phase 18 - the VERIFIED production pipeline configuration (data/phase16/phase16_comparison.json,
# configuration "phase16_combined_ABC", the adopted Phase 16 baseline):
#   top_k_cards=10, rerank_router=True, code_aware_router=True (Phase 15),
#   in_page_grounding=True, citation_normalization=True, relaxed_context_gate=True (Phase 16 A/B/C),
#   evidence_frame_normalization=False (Phase 17A Feature E: experimental, MUST stay OFF).
# The service must serve exactly this configuration - the numbers the project claims are the numbers
# measured for it. NOTE: the dataclass defaults in rag_pipeline.PipelineConfig are intentionally left at
# their historical values so that pre-Phase-18 evaluators keep reproducing their sealed results; only the
# production service path is pinned here (lazy import, matching this module's import style).


def production_pipeline_config():
    import rag_pipeline as RP
    return RP.PipelineConfig(
        top_k_cards=10,
        rerank_router=True,
        code_aware_router=True,
        in_page_grounding=True,
        citation_normalization=True,
        relaxed_context_gate=True,
        evidence_frame_normalization=False,
        # Phase 18/19A adopted production configuration (e1a_v2_corroborated, R1-R4 PASS):
        phrase_reranker=True,
        phrase_min_corroboration=2,
        full_page_coverage=False,
        citation_repair=False,
    )


def build_service(generator: str = "extractive") -> RagService:
    """Wire the real pipeline (needs the card store, the page store and the embedding weights). ``generator`` is explicit: no silent fallback."""
    if generator not in ("extractive", "ollama"):
        raise ValueError("generator must be 'extractive' or 'ollama'")
    import rag_evidence as EV
    import rag_pipeline as RP
    # Phase 11.1: the shipped configuration is "C1" of data/phase11_1_contract.md - evidence-sufficiency generator, tau 0.5, NO retrieval widening.
    # Phase 18: routing/grounding flags come from production_pipeline_config() (the verified Phase 16 baseline).
    return RagService(EV.build_evidence_pipeline(RP.build_pipeline(generator=generator, config=production_pipeline_config()), tau=EV.SHIPPED_TAU, widen=False, generator=generator), generator)


def answer_question(question: str, service: Optional[RagService] = None, generator: str = "extractive", conversation_id: Optional[str] = None,
                    debug: bool = False) -> Dict[str, Any]:
    """The single public entry point: validate, run the real pipeline, return the chat result (raises ``ServiceError`` subclasses)."""
    svc = service or build_service(generator)
    return svc.ask(question, conversation_id=conversation_id, debug=debug)
