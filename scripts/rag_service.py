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
import rag_elaborate as EL  # noqa: E402
import rag_followup as FU  # noqa: E402
import rag_response as RR  # noqa: E402  deterministic response composer

SCHEMA_VERSION = "11.1"
MAX_MESSAGE_CHARS = 500
CONVERSATION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

ANSWERED, DOC_UNAVAILABLE, UNABLE_TO_VERIFY, OUT_OF_SCOPE = "answered", "documentation_unavailable", "unable_to_verify", "out_of_scope"
# A scoped elaboration that cannot add any further verified evidence is its own deterministic state: the topic WAS
# answered and grounded, the source page exists in the corpus, and only the unused verified evidence is exhausted.
# It is deliberately NOT unable_to_verify (nothing failed to verify) and NOT documentation_unavailable (the page is
# not missing), so the response never claims that a used page is absent from the knowledge base.
NO_ADDITIONAL_VERIFIED_EVIDENCE = "no_additional_verified_evidence"
ELABORATION_CONTEXT_MISSING = "ELABORATION_CONTEXT_MISSING"
ELABORATION_CONTEXT_MISSING_TEXT = "Please share the SAP Utilities topic or original question you'd like me to elaborate on."
API_STATUSES = (ANSWERED, DOC_UNAVAILABLE, UNABLE_TO_VERIFY, OUT_OF_SCOPE, NO_ADDITIONAL_VERIFIED_EVIDENCE)
# pipeline status (rag_pipeline.STATUSES) -> API status
STATUS_MAP = {"answered": ANSWERED, "page_not_ingested": DOC_UNAVAILABLE, "unresolved_identity": UNABLE_TO_VERIFY, "insufficient_context": UNABLE_TO_VERIFY,
              "out_of_domain": OUT_OF_SCOPE, "no_relevant_page": OUT_OF_SCOPE}
USER_TEXT = {
    DOC_UNAVAILABLE: "I found the relevant topic, but the underlying SAP Help page is not currently available in the local knowledge base.",
    UNABLE_TO_VERIFY: "I couldn't find enough verified information in the available SAP Utilities documentation to answer that specific detail.",
    OUT_OF_SCOPE: "This question doesn't appear to match the SAP Utilities documentation available to me.",
    NO_ADDITIONAL_VERIFIED_EVIDENCE: "That's all the additional detail I could verify from the available documentation.",
}
UNRESOLVED_TEXT = "I couldn't verify the relevant documentation."
REFERENCE_NOTE = "Topic reference only - not used as evidence for any answer."
ACTIVE_INDUSTRY_CONTEXT = "SAP Utilities/IS-U"


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
MAX_CONVERSATION_HISTORY = 1000
CONVERSATION_TTL_SECONDS = 3600.0  # 1 hour TTL


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
                   evidence: Optional[Mapping[str, Any]] = None,
                   presentation_sections: Optional[List[Mapping[str, Any]]] = None,
                   follow_up_category: Optional[str] = None) -> Dict[str, Any]:
    """Translate one ``RagPipeline.answer`` dict (produced with ``debug=True``) into the public chat result."""
    pstatus = raw["status"]
    status = STATUS_MAP[pstatus]
    if raw.get("reason_code") == "NO_ADDITIONAL_SUPPORTED_DETAILS":
        # Scoped elaboration with no additional verified evidence: a distinct state, not an abstention failure.
        status = NO_ADDITIONAL_VERIFIED_EVIDENCE
    topic = raw.get("topic") or {}
    dbg = raw.get("debug") or {}
    if status == ANSWERED:
        answer = raw["answer"]
        sources = [_source(s) for s in raw["citations"]["answer_sources"]]
    elif status == NO_ADDITIONAL_VERIFIED_EVIDENCE:
        answer = USER_TEXT[NO_ADDITIONAL_VERIFIED_EVIDENCE]
        sources = []
    elif raw.get("reason_code") == ELABORATION_CONTEXT_MISSING:
        answer = ELABORATION_CONTEXT_MISSING_TEXT
        sources = []
    else:
        answer = UNRESOLVED_TEXT if pstatus == "unresolved_identity" else USER_TEXT[status]
        sources = []
    reference = None
    candidates = raw.get("routing", {}).get("candidates") or []
    cand = candidates[0] if candidates else {}
    has_routing_relevance = bool(
        cand.get("coverage", 0.0) > 0.0
        or cand.get("phrase_match", 0.0) > 0.0
        or cand.get("code_match", 0.0) > 0.0
    )
    if not any(k in cand for k in ("coverage", "phrase_match", "code_match")):
        has_routing_relevance = bool(topic.get("title"))

    is_relevant_topic = has_routing_relevance if status == UNABLE_TO_VERIFY else True

    if status in (DOC_UNAVAILABLE, UNABLE_TO_VERIFY) and pstatus != "unresolved_identity" and topic.get("title") and _safe_url(topic.get("card_url")) and is_relevant_topic:
        reference = {"type": "topic_reference", "title": topic["title"], "url": _safe_url(topic["card_url"]), "note": REFERENCE_NOTE}
    routed = status != OUT_OF_SCOPE
    grounding_view = _grounding(dbg, pstatus)
    grounded_ok = status == ANSWERED and grounding_view["ok"] is True
    if raw.get("reason_code") == ELABORATION_CONTEXT_MISSING:
        page_available = None  # no topic was resolved, so do not imply a page is missing
    else:
        page_available = (topic.get("corpus_status") == "ingested") if routed else None
    meta = {"card_id": topic.get("source_id") if routed else None, "card_title": topic.get("title") if routed else None,
            "identity_status": topic.get("identity_status") if routed else None, "page_available": page_available, "generator": generator, "grounded": grounded_ok,
            "can_elaborate": grounded_ok, "grounding": grounding_view, "pipeline_status": pstatus, "reason_code": raw.get("reason_code"), "latency_ms": round(latency_ms, 1)}
    if (status == ANSWERED and topic.get("source_id") and topic.get("effective_guide_id") and topic.get("effective_page_id")):
        meta["topic_identity"] = {
            "source_id": topic["source_id"], "title": topic.get("title"),
            "guide_id": topic["effective_guide_id"], "page_id": topic["effective_page_id"],
            "industry": ACTIVE_INDUSTRY_CONTEXT,
        }
    if follow_up_category:
        meta["follow_up_category"] = follow_up_category
    if presentation_sections:
        meta["elaboration_sections"] = list(presentation_sections)
    if evidence and "additional_evidence" in evidence:
        meta["additional_evidence"] = evidence["additional_evidence"]

    # Deterministic response composer
    composed = RR.compose_response(answer, sources, status=status, metadata=meta)
    structured_answer = composed.get("structured_answer")
    documentation_coverage = composed.get("documentation_coverage")
    meta["documentation_coverage"] = documentation_coverage

    out: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "conversation_id": conversation_id,
        "status": status,
        "answer": answer,
        "sources": sources,
        "topic_reference": reference,
        "metadata": meta,
        "structured_answer": structured_answer,
        "documentation_coverage": documentation_coverage,
    }
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
        self._conversations: Dict[str, Dict[str, Any]] = {}
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

    def _prune_conversations(self, current_time: float) -> None:
        """Evict expired conversations (TTL) and enforce bounded capacity (LRU/FIFO)."""
        expired = [
            c for c, item in self._conversations.items()
            if current_time - item.get("updated_at", current_time) > CONVERSATION_TTL_SECONDS
        ]
        for c in expired:
            self._conversations.pop(c, None)
        while len(self._conversations) > MAX_CONVERSATION_HISTORY:
            oldest_cid = next(iter(self._conversations))
            self._conversations.pop(oldest_cid, None)

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

    def _canonical_active_topic(self, context: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
        import m2c_page_identity as PID
        if not isinstance(context, Mapping) or "active_topic" not in context:
            return None
        active = context.get("active_topic")
        if not isinstance(active, Mapping):
            return None
        identity = active.get("identity")
        if not isinstance(identity, Mapping):
            return None
        card_id = str(identity.get("source_id") or "").strip()
        card = self.pipeline.cards.get(card_id)
        if card is None:
            return None
        resolved = PID.resolve_identity(card, self.pipeline.ctx)
        if not resolved.effective_guide_id or not resolved.effective_page_id:
            return None
        if (str(identity.get("guide_id") or "").casefold() != resolved.effective_guide_id.casefold() or
            str(identity.get("page_id") or "").casefold() != resolved.effective_page_id.casefold()):
            return None
        return dict(active)

    def _run_pipeline_request(self, q: str, queue_wait_ms: Optional[float] = None,
                              pipeline: Optional[Any] = None,
                              expected_topic: Optional[Mapping[str, Any]] = None) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        self._reset_request_state()
        active_pipeline = pipeline or self.pipeline
        if expected_topic is None:
            raw = active_pipeline.answer(q, debug=True)
        else:
            raw = active_pipeline.answer(q, debug=True, expected_topic=expected_topic)
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
        request_generator = getattr(active_pipeline, "generator", self._evidence_gen)
        actual_generator = str(getattr(request_generator, "name", self.generator_name))
        if actual_generator == "extractive" and raw["status"] == "answered":
            chain = support_chain(raw["answer"], raw.get("debug") or {})
            evidence = dict(evidence or {}, support_chain=chain)
            if not chain["ok"]:                                      # support cannot be established -> abstain, never "answered"
                raw = dict(raw, status="insufficient_context", answer=None, reason_code="SUPPORT_CHAIN_FAILED", citations={"answer_sources": []})
        return raw, evidence

    def ask(self, question: Any, conversation_id: Optional[str] = None, debug: bool = False,
            context: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        """Answer one question.

        ``context`` carries an explicit ``active_topic`` produced from a successful grounded standalone answer,
        or legacy conversation history (questions/answer).
        When the immediately previous assistant response is an answerable grounded SAP Utilities answer,
        follow-up requests (such as "elaborate", "explain more", etc.) are handled deterministically
        via scoped elaboration on the grounded topic without generative LLM calls.
        """
        q = clean_question(question)
        cid = resolve_conversation_id(conversation_id)

        # Context resolution: explicit caller context beats internal session state
        effective_context: Optional[Mapping[str, Any]] = None
        if isinstance(context, Mapping) and context:
            effective_context = dict(context)
        else:
            with self._lock:
                now = time.time()
                self._prune_conversations(now)
                prev = self._conversations.get(cid)
                if prev and prev.get("status") == ANSWERED and prev.get("grounded") and prev.get("answer"):
                    effective_context = {
                        "questions": [prev["query"]],
                        "answer": prev["answer"],
                        "active_topic": {
                            "query": prev["query"],
                            "answer": prev["answer"],
                            "identity": prev.get("topic_identity"),
                            "seen_answers": prev.get("seen_answers", []),
                        } if prev.get("topic_identity") else None,
                    }
                elif (prev and prev.get("status") == NO_ADDITIONAL_VERIFIED_EVIDENCE and prev.get("topic_identity")
                        and prev.get("answer") and prev.get("query")):
                    # The active topic survives an exhausted elaboration: the topic stays anchored, only the unused
                    # verified evidence is spent. Follow-ups keep resolving against it instead of falling through to
                    # out-of-scope routing.
                    effective_context = {
                        "questions": [prev["query"]],
                        "answer": prev["answer"],
                        "active_topic": {
                            "query": prev["query"],
                            "answer": prev["answer"],
                            "identity": prev.get("topic_identity"),
                            "seen_answers": prev.get("seen_answers", []),
                        },
                        "elaboration_exhausted": bool(prev.get("elaboration_exhausted")),
                    }

        follow_up = FU.resolve(q, effective_context) if effective_context else None
        category = follow_up["category"] if follow_up else None
        pipeline_query = follow_up["query"] if follow_up else q
        scoped: Optional[Any] = None
        expected_topic: Optional[Dict[str, Any]] = None
        anchor_query = q
        previous_answer = ""
        short_circuited = False
        with self._lock:
            stored_state = self._conversations.get(cid)

        if (
            follow_up is not None
            and category == "elaborate"
            and isinstance(stored_state, dict)
            and stored_state.get("status") == NO_ADDITIONAL_VERIFIED_EVIDENCE
            and stored_state.get("elaboration_exhausted") is True
            and stored_state.get("topic_identity")
            and stored_state.get("answer")
            and follow_up.get("anchor") == stored_state.get("query")
        ):
            # Repeated elaboration intent ("elaborate", "explain more", "tell me more", ... - all the same category)
            # after the verified evidence of the active topic is exhausted: return the same safe
            # no-additional-evidence state. The follow-up is never re-routed, so it can never fall through to
            # out_of_scope. The backend owns this state; the response mirrors it with can_elaborate=false.
            short_circuited = True
            identity = dict(stored_state["topic_identity"])
            card = self.pipeline.cards.get(str(identity.get("source_id") or "")) or {}
            raw: Dict[str, Any] = {
                "status": "insufficient_context",
                "reason_code": "NO_ADDITIONAL_SUPPORTED_DETAILS",
                "answer": None,
                "topic": {
                    "source_id": identity.get("source_id"),
                    "title": identity.get("title"),
                    "card_url": card.get("source_url"),
                    "identity_status": "resolved_local_page",
                    "effective_guide_id": identity.get("guide_id"),
                    "effective_page_id": identity.get("page_id"),
                    "corpus_status": "ingested",
                },
                "citations": {"topic_pointer": None, "answer_sources": [], "context_not_cited": [], "label": "none", "notes": []},
                "routing": {"selected_source_id": identity.get("source_id"), "candidates": [], "mode": "elaboration_exhausted"},
                "debug": {},
                "timings_ms": {},
            }
            evidence: Optional[Dict[str, Any]] = {
                "checked": True, "supported": False, "reason": "NO_ADDITIONAL_EVIDENCE", "intent": category,
                "selected": [], "elaborated": None, "final_novelty_check": {"ok": False},
                "reason_added": "NO_ADDITIONAL_EVIDENCE", "elaboration_exhausted": True,
            }
        elif FU.classify(q) == "elaborate" and follow_up is None:
            # A bare elaboration alias has no standalone subject. Do not send it through ordinary topic routing, where
            # it can be mislabeled out-of-scope (or accidentally attach to unrelated evidence). Ask for the topic instead.
            short_circuited = True
            raw = {
                "message": q,
                "status": "insufficient_context",
                "reason_code": ELABORATION_CONTEXT_MISSING,
                "answer": None,
                "topic": {},
                "citations": {"topic_pointer": None, "answer_sources": [], "context_not_cited": [], "label": "none", "notes": []},
                "routing": {"candidates": [], "mode": "follow_up_clarification"},
                "debug": {},
                "timings_ms": {},
            }
            evidence = None
        elif follow_up and EL.is_elaboration_intent(category):
            active_topic = self._canonical_active_topic(effective_context)
            if active_topic:
                expected_topic = {"identity": active_topic["identity"]}
                active_identity = active_topic["identity"]
                anchor_query = active_topic["query"]
                seen_answers = active_topic.get("seen_answers") or []
                previous_answer = "\n".join([active_topic["answer"], *seen_answers]) if seen_answers else active_topic["answer"]
            else:
                active_identity = None
                anchor_query = follow_up["anchor"]
                previous_answer = str(effective_context.get("answer") or "") if effective_context else ""

            scoped = EL.scoped_pipeline(
                self.pipeline,
                category,
                previous_answer=previous_answer,
                anchor=anchor_query,
                new_terms=EL.new_terms_of(q, anchor_query) if follow_up.get("form") == "message" else (),
                active_identity=active_identity,
            )
            pipeline_query = anchor_query if follow_up.get("form") == "clause" else follow_up["query"]

        t0 = time.perf_counter()
        if short_circuited:
            pass                                                # raw/evidence already built: no retrieval, no generation, no gates
        else:
            try:
                if self.coarse_lock:
                    if self._lock.acquire(blocking=False):
                        q_wait = 0.0
                    else:
                        t_w0 = time.perf_counter()
                        self._lock.acquire()
                        q_wait = (time.perf_counter() - t_w0) * 1000.0
                    try:
                        raw, evidence = self._run_pipeline_request(
                            pipeline_query, queue_wait_ms=q_wait, pipeline=scoped, expected_topic=expected_topic
                        )
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
                        raw, evidence = self._run_pipeline_request(
                            pipeline_query, queue_wait_ms=q_wait, pipeline=scoped, expected_topic=expected_topic
                        )
                    finally:
                        self._request_sem.release()
            except ServiceError:
                raise
            except Exception as e:                               # noqa: BLE001
                raise PipelineFailure(f"The retrieval pipeline failed ({type(e).__name__}). No answer was produced.") from e

        # Scoped elaboration validation & novelty check
        if scoped is not None:
            if raw.get("status") == "answered":
                answer_body = raw.get("answer") or ""
                # Redundancy check: cannot simply repeat the previous answer
                is_redundant = answer_body.strip() == previous_answer.strip()
                if is_redundant:
                    raw = dict(
                        raw,
                        status="insufficient_context",
                        answer=None,
                        reason_code="NO_ADDITIONAL_SUPPORTED_DETAILS",
                        citations={"answer_sources": []},
                    )
                    if evidence is not None:
                        evidence["final_novelty_check"] = {"ok": False}
                    else:
                        evidence = {"final_novelty_check": {"ok": False}}
            elif raw.get("reason_code") in ("GENERATOR_REFUSED", "NO_ADDITIONAL_SUPPORTED_DETAILS"):
                raw = dict(
                    raw,
                    status="insufficient_context",
                    answer=None,
                    reason_code="NO_ADDITIONAL_SUPPORTED_DETAILS",
                    citations={"answer_sources": []},
                )
                if evidence is not None:
                    evidence.setdefault("final_novelty_check", {"ok": False})
                    evidence.setdefault("reason_added", "NO_ADDITIONAL_EVIDENCE")
                else:
                    evidence = {"final_novelty_check": {"ok": False}, "reason_added": "NO_ADDITIONAL_EVIDENCE"}

        if follow_up is not None and isinstance(raw.get("debug"), dict):
            view = FU.debug_view(follow_up, q)
            if scoped is not None:
                view["pass"] = "elaboration"
                view["retrieval_query"] = pipeline_query
                view["selected"] = [u.get("sentence") for u in (evidence or {}).get("selected") or []]
            elif short_circuited:
                view["pass"] = "elaboration_exhausted"
                view["retrieval_query"] = stored_state.get("query") if isinstance(stored_state, dict) else None
            raw["debug"]["follow_up"] = view

        presentation_sections = None
        if scoped is not None and raw.get("status") == "answered" and (evidence or {}).get("elaborated") is True:
            presentation_sections = (evidence or {}).get("presentation_sections")

        result = to_chat_result(
            raw,
            "extractive" if (scoped is not None or short_circuited) else self.generator_name,
            cid,
            (time.perf_counter() - t0) * 1000,
            debug=debug,
            evidence=evidence,
            presentation_sections=presentation_sections,
            follow_up_category=category if follow_up else None,
        )

        # Update per-conversation state with bounded capacity and TTL
        with self._lock:
            now = time.time()
            self._prune_conversations(now)
            if result["status"] == ANSWERED:
                seen = []
                if cid in self._conversations and self._conversations[cid].get("query") == anchor_query:
                    seen = list(self._conversations[cid].get("seen_answers", []))
                if result["answer"] not in seen:
                    seen.append(result["answer"])
                self._conversations[cid] = {
                    "query": anchor_query,
                    "answer": result["answer"],
                    "status": result["status"],
                    "grounded": result.get("metadata", {}).get("grounded", False),
                    "topic_identity": result.get("metadata", {}).get("topic_identity"),
                    "sources": result.get("sources", []),
                    "seen_answers": seen,
                    "updated_at": now,
                }
            elif (result["status"] == NO_ADDITIONAL_VERIFIED_EVIDENCE and follow_up is not None
                    and EL.is_elaboration_intent(category)):
                # An exhausted elaboration never replaces the active topic (the same rule the client-side state
                # machine applies to every failed follow-up): the anchor, identity and evidence history survive, so
                # the next follow-up still resolves against this topic instead of falling through to out_of_scope.
                # Only the "elaborate" intent itself spends the elaboration availability.
                prev_now = self._conversations.get(cid)
                if isinstance(prev_now, dict) and prev_now.get("topic_identity") and prev_now.get("answer") and prev_now.get("query"):
                    self._conversations[cid] = {
                        "query": prev_now["query"],
                        "answer": prev_now["answer"],
                        "status": result["status"],
                        "grounded": False,
                        "topic_identity": prev_now["topic_identity"],
                        "sources": prev_now.get("sources", []),
                        "seen_answers": list(prev_now.get("seen_answers", [])),
                        "elaboration_exhausted": category == "elaborate",
                        "updated_at": now,
                    }
                else:
                    self._conversations[cid] = {
                        "query": q,
                        "answer": result.get("answer", ""),
                        "status": result["status"],
                        "grounded": False,
                        "topic_identity": None,
                        "sources": [],
                        "seen_answers": [],
                        "updated_at": now,
                    }
            else:
                self._conversations[cid] = {
                    "query": q,
                    "answer": result.get("answer", ""),
                    "status": result["status"],
                    "grounded": False,
                    "topic_identity": None,
                    "sources": [],
                    "seen_answers": [],
                    "updated_at": now,
                }

        return result


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
                    debug: bool = False, context: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """The single public entry point: validate, run the real pipeline, return the chat result (raises ``ServiceError`` subclasses).

    ``context`` is the previous turns, used only to resolve a context-dependent follow-up (see ``RagService.ask``)."""
    svc = service or build_service(generator)
    return svc.ask(question, conversation_id=conversation_id, debug=debug, context=context)
