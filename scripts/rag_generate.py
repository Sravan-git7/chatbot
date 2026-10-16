"""Phase 8G - grounded generation, and the verifier that decides whether an answer may be shown.

Generators (all take a question and a ``ContextBlock`` and return a ``GenerationResult``):

* ``LLMGenerator(client)`` - builds the grounded prompt and calls an injectable ``LLMClient``. ``OllamaClient`` is the real local client
  (``ollama`` imported lazily; model and options come from ``rag_core.LLM_MODEL_NAME`` / ``LLM_OPTIONS`` - llama3.2:3b, temperature 0,
  seed 42). NOT VALIDATED in this repository's sandbox (no Ollama, no weights): it is tested only through stub clients.
* ``ExtractiveGenerator`` - deterministic, no model: returns the context sentences that best match the question, each with its ``[S#]``
  marker. Grounded by construction; it is a baseline that lets the whole chain be run and measured without an LLM. It does not
  paraphrase, so its answers read like the documentation.

``verify_grounding`` is applied to EVERY generator's output (including the LLM's). An answer is shown only if it passes:
  1. every sentence carries at least one ``[S#]`` marker and every marker names a chunk that was supplied (no phantom citations);
  2. no URL, no 32-hex SAP identifier and no ``help.sap.com`` text appears in the answer unless it is literally in a cited chunk;
  3. every identifier-like token (EL31, FPR1, ISU_AMI_1, numbers) occurs in the cited chunk text (no invented transaction codes/numbers);
  4. at least ``MIN_SENTENCE_SUPPORT`` of each sentence's content terms occur in the chunks it cites.
The checks are lexical. They catch fabricated codes, URLs, citations and off-context sentences; they cannot prove semantic faithfulness
(a sentence that reuses context words in a wrong claim can pass). That limit is reported, not hidden.
"""
from __future__ import annotations

import os
import math
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rag_text as T  # noqa: E402
from rag_context import ContextBlock  # noqa: E402

NO_ANSWER_TEXT = "I couldn't find this information in the provided SAP documentation."     # same sentence as the legacy prompt (rag_core)
MIN_SENTENCE_SUPPORT = 0.6          # pre-declared (not tuned): share of a sentence's content terms found in its cited chunks
EXTRACTIVE_MIN_SCORE = 0.34         # pre-declared (not tuned): minimum share of question terms a sentence must contain to be extracted
EXTRACTIVE_MAX_SENTENCES = 3
# A fixed request-local selection limitation, never a factual claim about an entire SAP page.
PROCEDURAL_LIMITATION_NOTICE = "The selected evidence does not establish a complete step-by-step procedure."
_MARKER = re.compile(r"\[S(\d+)\]")
_COMPOUND_MARKER = re.compile(r"\[(S\d+(?:[\s,/\-–]+(?:and\s+)?S?\d+)*)\]")
_URL = re.compile(r"https?://\S+|www\.\S+|help\.sap\.com\S*", re.I)
_HEX_ID = re.compile(r"\b[0-9a-f]{32}\b", re.I)

GROUNDED_PROMPT = """You are an SAP documentation assistant. Answer the question ONLY from the numbered documentation excerpts below.

RULES:
1. Use only facts stated in the excerpts. Do not use outside knowledge and do not guess.
2. After every sentence of your answer, add the marker of the excerpt that supports it, for example [S1]. Use only the markers shown below.
3. Do not write URLs, links, guide identifiers or transaction codes that are not written in the excerpts.
4. If the excerpts do not contain the answer, reply with exactly: {no_answer}
5. Keep the answer short and in your own words only where this does not change the meaning.

DOCUMENTATION EXCERPTS:

{context}

QUESTION:

{question}

ANSWER:
"""


def build_prompt(question: str, context: ContextBlock) -> str:
    return GROUNDED_PROMPT.format(no_answer=NO_ANSWER_TEXT, context=context.render(), question=question.strip())


class LLMClient(Protocol):
    def generate(self, prompt: str) -> str: ...


def _extract_ollama_telemetry(resp: Mapping[str, Any]) -> Dict[str, Any]:
    """Extract non-sensitive generation timing & token count metadata from an Ollama chat response."""
    if not isinstance(resp, Mapping):
        return {}
    total_ns = int(resp.get("total_duration") or 0)
    load_ns = int(resp.get("load_duration") or 0)
    peval_ns = int(resp.get("prompt_eval_duration") or 0)
    eval_ns = int(resp.get("eval_duration") or 0)
    peval_cnt = int(resp.get("prompt_eval_count") or 0)
    eval_cnt = int(resp.get("eval_count") or 0)
    tps = round(eval_cnt / (eval_ns / 1e9), 2) if eval_ns > 0 and eval_cnt > 0 else 0.0
    load_ms = round(load_ns / 1e6, 3)
    return {
        "prompt_eval_count": peval_cnt,
        "eval_count": eval_cnt,
        "total_duration_ms": round(total_ns / 1e6, 3),
        "load_duration_ms": load_ms,
        "prompt_eval_duration_ms": round(peval_ns / 1e6, 3),
        "eval_duration_ms": round(eval_ns / 1e6, 3),
        "tokens_per_sec": tps,
        "cold_load": bool(load_ms > 100.0),
    }


class OllamaClient:
    """Local Ollama client. Lazy import; no network beyond the local Ollama server; model and options default to ``rag_core``.
    Thread-safe: ``last_telemetry`` is stored in thread-local storage and reset at the start of every call,
    and ``generate_with_telemetry`` returns ``(text, telemetry)`` explicitly per invocation.
    """

    def __init__(self, model: Optional[str] = None, options: Optional[Dict[str, Any]] = None, chat: Any = None,
                 num_predict: Optional[int] = None, keep_alive: Optional[Any] = None, timeout: Optional[float] = None) -> None:
        import rag_core
        self.model = model or os.environ.get("OLLAMA_MODEL", "").strip() or rag_core.LLM_MODEL_NAME
        self.options = dict(options or rag_core.LLM_OPTIONS)
        if num_predict is not None:
            self.options["num_predict"] = int(num_predict)
        self.keep_alive = keep_alive
        # Finite network timeout by default. No unbounded ollama.chat path in production.
        # Invalid values cannot disable the bound; explicitly injected test clients remain offline.
        raw = timeout if timeout is not None else os.environ.get("SURA_OLLAMA_TIMEOUT_SECONDS", "60")
        try:
            bounded_timeout = float(raw)
            if not math.isfinite(bounded_timeout) or bounded_timeout <= 0:
                bounded_timeout = 60.0
        except (TypeError, ValueError):
            bounded_timeout = 60.0
        self.timeout = bounded_timeout
        self._chat = chat
        self._tls = threading.local()

    @property
    def last_telemetry(self) -> Dict[str, Any]:
        return getattr(self._tls, "last_telemetry", {})

    @last_telemetry.setter
    def last_telemetry(self, value: Dict[str, Any]) -> None:
        self._tls.last_telemetry = dict(value) if value else {}

    def reset_request_state(self) -> None:
        self._tls.last_telemetry = {}

    def generate_with_telemetry(self, prompt: str) -> Tuple[str, Dict[str, Any]]:
        self._tls.last_telemetry = {}
        chat = self._chat
        if chat is None:
            import ollama                                   # lazy: only when a real generation is requested
            chat = ollama.Client(timeout=self.timeout).chat
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "options": dict(self.options),
        }
        if self.keep_alive is not None:
            kwargs["keep_alive"] = self.keep_alive
        resp = chat(**kwargs)
        tel = _extract_ollama_telemetry(resp)
        self._tls.last_telemetry = dict(tel)
        return str(resp["message"]["content"]), tel

    def generate(self, prompt: str) -> str:
        text, _ = self.generate_with_telemetry(prompt)
        return text

    def check_available(self, timeout: float = 5.0) -> bool:
        """Bounded readiness probe for ``/ready``: True only when the local Ollama server answers AND the configured
        model is pulled. Never raises and never fabricates availability - any failure (unreachable server, missing
        model, import error, timeout) reports False so readiness fails closed instead of claiming a ready model.

        An injected ``chat`` callable (tests/evaluation stubs) counts as available: stubs must not touch the network.
        Model matching is strict: the exact configured name, or ``<name>:latest`` when the configured name carries no
        tag (Ollama's implicit-tag convention). A different tag of the same base model is NOT accepted.
        """
        if self._chat is not None:
            return callable(self._chat)
        try:
            import ollama                                   # lazy: only when readiness is actually probed
            client = ollama.Client(timeout=timeout)
            resp = client.list()
            models = resp.get("models") if isinstance(resp, Mapping) else getattr(resp, "models", None)
            names = set()
            for m in models or []:
                n = (m.get("model") or m.get("name")) if isinstance(m, Mapping) else (getattr(m, "model", None) or getattr(m, "name", None))
                if n:
                    names.add(str(n))
            want = str(self.model or "")
            if not want:
                return False
            if want in names:
                return True
            return ":" not in want and f"{want}:latest" in names
        except Exception:                                   # noqa: BLE001 - readiness must never raise
            return False


@dataclass
class GenerationResult:
    text: str
    refused: bool
    generator: str
    raw_text: str
    prompt: Optional[str] = None
    telemetry: Optional[Dict[str, Any]] = None
    evidence: Optional[Dict[str, Any]] = None


class LLMGenerator:
    name = "llm"

    def __init__(self, client: LLMClient, name: str = "llm") -> None:
        self.client = client
        self.name = name

    def generate(self, question: str, context: ContextBlock) -> GenerationResult:
        t_p0 = time.perf_counter()
        prompt = build_prompt(question, context)
        prompt_build_ms = round((time.perf_counter() - t_p0) * 1000.0, 3)
        t_g0 = time.perf_counter()
        if hasattr(self.client, "generate_with_telemetry"):
            raw, client_tel = self.client.generate_with_telemetry(prompt)
            raw = raw or ""
            tel: Dict[str, Any] = dict(client_tel or {})
        else:
            raw = self.client.generate(prompt) or ""
            tel = {}
        http_ms = round((time.perf_counter() - t_g0) * 1000.0, 3)
        text = raw.strip()
        refused = NO_ANSWER_TEXT.lower() in text.lower() or not text
        tel["prompt_build_ms"] = prompt_build_ms
        tel["ollama_http_ms"] = http_ms
        tel["context_chars"] = len(context.render())
        tel["prompt_chars"] = len(prompt)
        tel["output_chars"] = len(text)
        return GenerationResult(NO_ANSWER_TEXT if refused else text, refused, self.name, raw, prompt, telemetry=tel)


class ExtractiveGenerator:
    """Deterministic non-LLM baseline: the context sentences that contain most of the question's content terms, with markers."""
    name = "extractive"

    def __init__(self, min_score: float = EXTRACTIVE_MIN_SCORE, max_sentences: int = EXTRACTIVE_MAX_SENTENCES) -> None:
        self.min_score = min_score
        self.max_sentences = max_sentences

    def generate(self, question: str, context: ContextBlock) -> GenerationResult:
        qt = set(T.terms(question))
        cands = []                                           # (score, order, marker, sentence, following)
        order = 0
        for item in context.items:
            sents = T.split_sentences(item.rendered_text)
            for i, s in enumerate(sents):
                order += 1
                score = len(qt & T.term_set(s)) / len(qt) if qt else 0.0
                follows: List[str] = []
                if s.rstrip().endswith(":"):
                    k = i + 1
                    while k < len(sents):
                        cand = sents[k]
                        if cand.startswith(("-", "*", "•")) or re.match(r"^\d+[.)]", cand):
                            follows.append(cand)
                            k += 1
                        else:
                            break
                    if not follows and i + 1 < len(sents) and not sents[i + 1].rstrip().endswith(":"):
                        follows.append(sents[i + 1])
                cands.append((score, order, item.marker, s, follows))
        if not cands or not qt:
            return GenerationResult(NO_ANSWER_TEXT, True, self.name, "")
        best = max(c[0] for c in cands)
        if best < self.min_score:
            return GenerationResult(NO_ANSWER_TEXT, True, self.name, "")
        keep = [c for c in cands if c[0] >= max(self.min_score, 0.6 * best)]
        keep = sorted(sorted(keep, key=lambda c: (-c[0], c[1]))[: self.max_sentences], key=lambda c: c[1])
        lines: List[str] = []
        seen_bodies: Dict[str, int] = {}
        for _score, _o, marker, s, follows in keep:
            s_clean = s.strip()
            if not s_clean:
                continue
            body = re.sub(r"\s*\[S\d+\]", "", s_clean).strip()
            if body in seen_bodies:
                idx = seen_bodies[body]
                if f"[{marker}]" not in lines[idx]:
                    lines[idx] = f"{lines[idx]} [{marker}]"
            else:
                seen_bodies[body] = len(lines)
                lines.append(f"{s_clean} [{marker}]")
            for f in (follows or []):
                f_clean = f.strip()
                if not f_clean:
                    continue
                f_body = re.sub(r"\s*\[S\d+\]", "", f_clean).strip()
                if f_body not in seen_bodies:
                    seen_bodies[f_body] = len(lines)
                    lines.append(f_clean)
        text = "\n".join(lines)
        return GenerationResult(text, False, self.name, text)


# ---------------------------------------------------------------------------------------------------- verification


@dataclass
class GroundingReport:
    ok: bool
    refusal: bool
    violations: List[Dict[str, Any]] = field(default_factory=list)
    sentences: List[Dict[str, Any]] = field(default_factory=list)
    cited_markers: List[str] = field(default_factory=list)          # valid markers cited by sentences that passed
    phantom_markers: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "refusal": self.refusal, "violations": self.violations, "sentences": self.sentences,
                "cited_markers": self.cited_markers, "phantom_markers": self.phantom_markers}


def is_procedural_limitation_sentence(text: str) -> bool:
    # Exempt only this exact, fact-free notice. Prefix matching let arbitrary
    # unsupported claims bypass both grounding and verbatim support checks.
    return text.strip().casefold() == PROCEDURAL_LIMITATION_NOTICE.casefold()


def verify_grounding(
    answer: str,
    context: ContextBlock,
    min_support: float = MIN_SENTENCE_SUPPORT,
    require_citations: bool = True,
    in_page_grounding: bool = False,
    citation_normalization: bool = False,
) -> GroundingReport:
    text = (answer or "").strip()
    if not text or NO_ANSWER_TEXT.lower() in text.lower():
        return GroundingReport(ok=True, refusal=True)
    rep = GroundingReport(ok=True, refusal=False)
    valid = {i.marker: i for i in context.items}
    all_context = "\n".join(i.text for i in context.items)

    def violate(kind: str, detail: str, sentence: Optional[str] = None) -> None:
        rep.ok = False
        rep.violations.append({"kind": kind, "detail": detail, "sentence": sentence})

    for u in _URL.findall(text):
        if u.rstrip(".,;)") not in all_context:
            violate("URL_NOT_IN_CONTEXT", u)
    for h in _HEX_ID.findall(text):
        if h.lower() not in all_context.lower():
            violate("IDENTIFIER_NOT_IN_CONTEXT", h)

    raw_lines = T.split_cited_sentences(text)
    parsed_lines: List[Dict[str, Any]] = []
    all_explicit_good_markers: List[str] = []

    for line in raw_lines:
        if citation_normalization:
            marker_names = []
            for g in _COMPOUND_MARKER.findall(line):
                for num in re.findall(r"\d+", g):
                    mname = f"S{num}"
                    if mname not in marker_names:
                        marker_names.append(mname)
            body = _COMPOUND_MARKER.sub("", line).strip()
        else:
            markers = _MARKER.findall(line)
            marker_names = [f"S{m}" for m in markers]
            body = _MARKER.sub("", line).strip()

        if ((not T.terms(body) and not T.code_tokens(body))
                or (not marker_names and is_procedural_limitation_sentence(body))):
            continue                                              # marker-only / punctuation-only / limitation notice line

        phantom = [m for m in marker_names if m not in valid]
        for m in phantom:
            rep.phantom_markers.append(m)
            violate("PHANTOM_MARKER", m, line)

        good = [m for m in marker_names if m in valid]
        for m in good:
            if m not in all_explicit_good_markers:
                all_explicit_good_markers.append(m)

        parsed_lines.append({
            "line": line,
            "body": body,
            "markers": marker_names,
            "good": good,
        })

    cited_ok: List[str] = []
    for idx, p in enumerate(parsed_lines):
        line = p["line"]
        body = p["body"]
        marker_names = p["markers"]
        good = list(p["good"])

        # Citation inheritance for bullet lists or multi-sentence answers
        if not good and citation_normalization and all_explicit_good_markers:
            candidate_markers = []
            for prev_p in reversed(parsed_lines[:idx]):
                if prev_p["good"]:
                    candidate_markers = prev_p["good"]
                    break
            if not candidate_markers:
                for next_p in parsed_lines[idx + 1:]:
                    if next_p["good"]:
                        candidate_markers = next_p["good"]
                        break
            if not candidate_markers:
                candidate_markers = all_explicit_good_markers

            cand_text = "\n".join(valid[m].text for m in candidate_markers)
            bt = set(T.terms(body))
            cand_sup = (len(bt & T.term_set(cand_text)) / len(bt)) if bt else 1.0
            cand_unsupported = sorted(t for t in T.code_tokens(body) if t not in cand_text and t not in all_context)
            cand_in_other = sorted(t for t in T.code_tokens(body) if t not in cand_text and t in all_context)
            cand_tokens_ok = (not cand_unsupported) and (not cand_in_other or in_page_grounding)

            # Accept inheritance only if verified supported and no unsupported tokens
            if cand_sup >= min_support and cand_tokens_ok:
                good = candidate_markers

        entry: Dict[str, Any] = {"text": body, "markers": marker_names, "support": None, "unsupported_tokens": []}
        if not good:
            if require_citations:
                violate("NO_CITATION", "sentence has no valid [S#] marker", line)
            else:
                good = list(valid)

        cited_text = "\n".join(valid[m].text for m in good)
        unsupported = sorted(t for t in T.code_tokens(body) if t not in cited_text and t not in all_context)
        in_other = sorted(t for t in T.code_tokens(body) if t not in cited_text and t in all_context)

        if unsupported:
            entry["unsupported_tokens"] = unsupported
            violate("TOKEN_NOT_IN_CONTEXT", ", ".join(unsupported), line)
        if in_other and not in_page_grounding:
            violate("TOKEN_NOT_IN_CITED_CHUNK", ", ".join(in_other), line)

        bt = set(T.terms(body))
        sup = (len(bt & T.term_set(cited_text)) / len(bt)) if bt else 1.0
        entry["support"] = round(sup, 3)
        if good and sup < min_support:
            violate("LOW_SUPPORT", f"{sup:.2f} < {min_support}", line)

        rep.sentences.append(entry)
        tokens_ok = (not unsupported) and (not in_other or in_page_grounding)
        if good and sup >= min_support and tokens_ok:
            cited_ok += [m for m in good if m not in cited_ok]

    if not rep.sentences:
        violate("EMPTY_ANSWER", "no answer sentence found")
    rep.cited_markers = sorted(cited_ok, key=lambda m: int(m[1:])) if rep.ok else []
    return rep
