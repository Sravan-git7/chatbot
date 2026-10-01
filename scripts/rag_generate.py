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

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rag_text as T  # noqa: E402
from rag_context import ContextBlock  # noqa: E402

NO_ANSWER_TEXT = "I couldn't find this information in the provided SAP documentation."     # same sentence as the legacy prompt (rag_core)
MIN_SENTENCE_SUPPORT = 0.6          # pre-declared (not tuned): share of a sentence's content terms found in its cited chunks
EXTRACTIVE_MIN_SCORE = 0.34         # pre-declared (not tuned): minimum share of question terms a sentence must contain to be extracted
EXTRACTIVE_MAX_SENTENCES = 3
_MARKER = re.compile(r"\[S(\d+)\]")
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


class OllamaClient:
    """Local Ollama client. Lazy import; no network beyond the local Ollama server; model and options exactly those of ``rag_core``."""

    def __init__(self, model: Optional[str] = None, options: Optional[Dict[str, Any]] = None, chat: Any = None) -> None:
        import rag_core
        self.model = model or rag_core.LLM_MODEL_NAME
        self.options = dict(options or rag_core.LLM_OPTIONS)
        self._chat = chat

    def generate(self, prompt: str) -> str:
        chat = self._chat
        if chat is None:
            import ollama                                   # lazy: only when a real generation is requested
            chat = ollama.chat
        resp = chat(model=self.model, messages=[{"role": "user", "content": prompt}], options=self.options)
        return str(resp["message"]["content"])


@dataclass
class GenerationResult:
    text: str
    refused: bool
    generator: str
    raw_text: str
    prompt: Optional[str] = None


class LLMGenerator:
    name = "llm"

    def __init__(self, client: LLMClient, name: str = "llm") -> None:
        self.client = client
        self.name = name

    def generate(self, question: str, context: ContextBlock) -> GenerationResult:
        prompt = build_prompt(question, context)
        raw = self.client.generate(prompt) or ""
        text = raw.strip()
        refused = NO_ANSWER_TEXT.lower() in text.lower() or not text
        return GenerationResult(NO_ANSWER_TEXT if refused else text, refused, self.name, raw, prompt)


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
                follow = sents[i + 1] if s.rstrip().endswith(":") and i + 1 < len(sents) else None
                cands.append((score, order, item.marker, s, follow))
        if not cands or not qt:
            return GenerationResult(NO_ANSWER_TEXT, True, self.name, "")
        best = max(c[0] for c in cands)
        if best < self.min_score:
            return GenerationResult(NO_ANSWER_TEXT, True, self.name, "")
        keep = [c for c in cands if c[0] >= max(self.min_score, 0.6 * best)]
        keep = sorted(sorted(keep, key=lambda c: (-c[0], c[1]))[: self.max_sentences], key=lambda c: c[1])
        lines = []
        for _score, _o, marker, s, follow in keep:
            lines.append(f"{s} [{marker}]")
            if follow:
                lines.append(f"{follow} [{marker}]")
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


def verify_grounding(answer: str, context: ContextBlock, min_support: float = MIN_SENTENCE_SUPPORT, require_citations: bool = True) -> GroundingReport:
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
    cited_ok: List[str] = []
    for line in T.split_cited_sentences(text):
        markers = _MARKER.findall(line)
        marker_names = [f"S{m}" for m in markers]
        body = _MARKER.sub("", line).strip()
        if not T.terms(body) and not T.code_tokens(body):
            continue                                              # marker-only / punctuation-only line
        phantom = [m for m in marker_names if m not in valid]
        for m in phantom:
            rep.phantom_markers.append(m)
            violate("PHANTOM_MARKER", m, line)
        good = [m for m in marker_names if m in valid]
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
        if in_other:
            violate("TOKEN_NOT_IN_CITED_CHUNK", ", ".join(in_other), line)
        bt = set(T.terms(body))
        sup = (len(bt & T.term_set(cited_text)) / len(bt)) if bt else 1.0
        entry["support"] = round(sup, 3)
        if good and sup < min_support:
            violate("LOW_SUPPORT", f"{sup:.2f} < {min_support}", line)
        rep.sentences.append(entry)
        if good and sup >= min_support and not unsupported and not in_other:
            cited_ok += [m for m in good if m not in cited_ok]
    if not rep.sentences:
        violate("EMPTY_ANSWER", "no answer sentence found")
    rep.cited_markers = sorted(cited_ok, key=lambda m: int(m[1:])) if rep.ok else []
    return rep
