#!/usr/bin/env python3
"""Phase 11.1 - evidence sufficiency for the card-first RAG pipeline (opt-in building blocks; the default ``rag_pipeline`` is not modified).

Problem (Phase 11 E2E, see ``data/phase11_1_contract.md``): the extractive generator answers whenever *some* sentence shares >= 34 % of the question's terms. A page that
discusses the topic but does not contain the asked detail therefore produced a related, misleading answer; and a sentence that merely overlaps was preferred to the sentence
that states the fact. This module adds a deterministic, question-aware check **between retrieval and the answer**:

1. ``analyze_question``   - what the question asks for: detail kinds (code / number / limit / default / time), the *asked-for* terms (the noun right after
                            which/what/how many) and the focus terms (content terms without question-frame words).
2. ``EvidenceExtractiveGenerator`` - sentence extraction that
     * counts a sentence's section heading as context (a sentence under "Gadget > Purpose" is about the gadget),
     * REFUSES when an asked-for term occurs nowhere in the retrieved evidence,
     * REFUSES when the question needs a kind of detail (a code, a number, a minimum ...) and no evidence sentence contains it,
     * REFUSES when the best sentence covers fewer than ``tau`` of the focus terms,
     * emits only sentences taken verbatim from the cited chunk and records the chain question -> sentence -> marker -> chunk.
3. ``EvidenceRetriever``  - when the retrieved chunks cannot provide the required detail, the rest of the SAME identity-constrained page is searched for a chunk that can
                            (the detail may sit on another chunk of the right page). Never leaves the page; never mixes pages; the promoted chunk is cited as itself.
4. ``verify_support_chain`` - independent check that every answer sentence is a verbatim span of the chunk its marker names (traceability, not word overlap).
5. ``EvidenceGuard``      - the same pre/post checks around an LLM generator (stub-tested only; no Ollama here).

Everything is lexical and deterministic; it cannot prove semantic faithfulness (documented limit). Constants are pre-declared in ``data/phase11_1_contract.md``.
"""
from __future__ import annotations

import dataclasses
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rag_text as T  # noqa: E402
from rag_generate import EXTRACTIVE_MAX_SENTENCES, NO_ANSWER_TEXT, GenerationResult  # noqa: E402

TAU = 0.6                           # pre-declared: share of focus terms the best answer sentence (+ its section heading) must cover
SHIPPED_TAU = 0.5                                           # shipped value, selected on DEV2 (contract Amendment 2c); TAU above is the pre-declared grid middle
TAU_GRID = (0.5, 0.6, 0.67)         # DEV selection grid (contract section 5)
KEEP_RATIO = 0.6                    # same relative cut as the baseline extractive generator
_WORD = re.compile(r"[a-z0-9][a-z0-9_]*")

# question-frame words: they carry no topic information (stems are computed below)
FRAME_WORDS = frozenset("possible available required needed need happen happens work works exist exists mean means called allowed applicable relevant important typical typically "
                        "usually normally generally come comes get gets many much relationship difference differences purpose reason reasons meaning kind kinds type types way ways example examples overview".split())
_ASK_SKIP = frozenset("is are does do did the a an of in for to can could will would should be it its this that these those one must may might shall have has had been being".split())
HEAD_WEIGHT = 0.5                   # a term found only in the section heading counts half (context, weaker than the sentence itself)


def stem2(w: str) -> str:
    """Evidence-layer stemmer: calculate / calculated / calculates / calculating / calculation(s) -> one stem; manage / management -> one stem; process / processes -> one stem."""
    w = w.lower()
    for suf, add in (("ations", "at"), ("ation", "at"), ("ments", ""), ("ment", ""), ("ings", ""), ("ing", ""), ("ies", "y"), ("ied", "y"), ("es", ""), ("ed", ""), ("s", "")):
        if w.endswith(suf) and len(w) - len(suf) >= (4 if suf in ("ments", "ment") else 3):
            if suf == "s" and w.endswith("ss"):
                continue
            w = w[: -len(suf)] + add
            break
    if len(w) > 4 and w.endswith("e"):
        w = w[:-1]
    for tail, repl in (("izat", "iz"), ("urat", "ur")):                  # authorization ~ authorize, configuration ~ configure
        if w.endswith(tail) and len(w) - len(tail) >= 3:
            w = w[: -len(tail)] + repl
    return w


def terms2(text: str) -> List[str]:
    return [stem2(w) for w in _WORD.findall((text or "").lower().replace("-", " ")) if w not in T.STOPWORDS and len(w) > 2]


FRAME_STEMS = frozenset(stem2(w) for w in FRAME_WORDS)

# ------------------------------------------------------------------------------------------------------------ question analysis
CUES: Dict[str, Tuple[str, ...]] = {
    "code": (r"\b(which|what)\s+(\w+\s+){0,2}(transaction|t-?code|tcode|function module|business function|badi|user exit)s?\b", r"\b(transaction|t-?code)\s+(code|number|name)\b", r"\bwhat\s+code\b"),
    "number": (r"\bhow\s+(many|much)\b", r"\bwhat\s+(is|are)\s+the\s+(\w+\s+){0,2}(amount|percentage|percent|rate|number|total|price|cost|fee|size|length|duration)\b",
               r"\b(what|which)\s+(\w+\s+){0,2}(rate|fee|price|cost|amount|percentage|percent)\b"),
    "limit": (r"\b(minimum|maximum|at\s+least|at\s+most|upper\s+limit|lower\s+limit|limit|threshold|largest|smallest|highest|lowest|longest|shortest|cap|ceiling)\b",),
    "default": (r"\bdefault\b",),
    "time": (r"\b(what|which)\s+(date|time|day|year|month|week)\b", r"\bhow\s+(long|often|soon|early|late)\b", r"\bby\s+when\b", r"\bdeadline\b"),
}
LIMIT_GROUPS = {"min": ("minimum", "minimal", "least", "smallest", "lowest", "shortest", "lower"), "max": ("maximum", "most", "largest", "highest", "longest", "upper", "ceiling", "up to"),
                "limit": ("limit", "threshold", "restrict", "cap", "ceiling")}
_LIMIT_Q = {"minimum": "min", "at least": "min", "lower limit": "min", "smallest": "min", "lowest": "min", "shortest": "min",
            "maximum": "max", "at most": "max", "upper limit": "max", "largest": "max", "highest": "max", "longest": "max", "ceiling": "max",
            "limit": "limit", "threshold": "limit", "cap": "limit"}
NUMBER_WORDS = ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "twenty", "thirty", "forty", "fifty", "hundred", "thousand", "percent", "half")
TIME_WORDS = ("day", "days", "week", "weeks", "month", "months", "year", "years", "hour", "hours", "minute", "minutes", "daily", "weekly", "monthly", "yearly", "annually", "date", "dates", "time")
DEFAULT_WORDS = ("default", "predefined", "preset", "pre-defined", "initial value")
_CODE_TOKEN = re.compile(r"\b[A-Z][A-Z0-9_]*[0-9_][A-Z0-9_]*\b")
_NUMBER = re.compile(r"(?<![A-Za-z0-9_])\d+(?:[.,]\d+)?(?![A-Za-z0-9_])")


@dataclass
class QuestionNeeds:
    question: str
    kinds: Tuple[str, ...]
    focus: Tuple[str, ...]
    asked: Tuple[str, ...]
    limit_groups: Tuple[str, ...] = ()
    code_words: Tuple[str, ...] = ()            # the kind of identifier the question names ("transaction", "function module", ...): the evidence must name it too

    def to_dict(self) -> Dict[str, Any]:
        return {"kinds": list(self.kinds), "focus_terms": list(self.focus), "asked_terms": list(self.asked), "limit_groups": list(self.limit_groups), "code_words": list(self.code_words)}


def analyze_question(question: str) -> QuestionNeeds:
    ql = (question or "").lower()
    kinds = tuple(k for k, pats in CUES.items() if any(re.search(p, ql) for p in pats))
    groups: List[str] = []
    for m in re.finditer(r"\b(minimum|maximum|at\s+least|at\s+most|upper\s+limit|lower\s+limit|limit|threshold|largest|smallest|highest|lowest|longest|shortest|cap|ceiling)\b", ql):
        g = _LIMIT_Q.get(re.sub(r"\s+", " ", m.group(1)))
        if g and g not in groups:
            groups.append(g)
    focus: List[str] = []
    for t in terms2(question):
        if t not in FRAME_STEMS and t not in focus:
            focus.append(t)
    asked: List[str] = []
    toks = _WORD.findall(ql.replace("-", " "))
    for i, w in enumerate(toks):
        if w in ("which", "what") or (w in ("many", "much") and i and toks[i - 1] == "how"):
            got = 0
            for nxt in toks[i + 1:i + 5]:
                if nxt in T.STOPWORDS or nxt in _ASK_SKIP or len(nxt) <= 2:
                    continue
                s = stem2(nxt)
                if s in FRAME_STEMS:
                    continue
                if s not in asked and s not in groups:
                    asked.append(s)
                got += 1
                if got == 1:                                    # only the first content word after the interrogative is the asked-for thing
                    break
    # cue words themselves (minimum, default, ...) are checked as kinds, not as asked-for terms and not as ordinary focus terms
    cue = {stem2(x) for g in LIMIT_GROUPS.values() for x in g} | {stem2("default")}
    focus = [t for t in focus if t not in cue or not any(k in kinds for k in ("limit", "default"))] or focus
    asked = [a for a in asked if a not in {stem2(x) for g in LIMIT_GROUPS.values() for x in g} and a != stem2("default")]
    code_words: List[str] = []
    if "code" in kinds:
        for pat, words in ((r"\b(transaction|t-?code|tcode)s?\b", ("transaction", "t-code", "tcode")), (r"\bfunction module\b", ("function module",)), (r"\bbusiness function\b", ("business function",)),
                           (r"\bbadi\b", ("badi",)), (r"\buser exit\b", ("user exit",))):
            if re.search(pat, ql):
                code_words += list(words)
    return QuestionNeeds(question, kinds, tuple(focus), tuple(asked), tuple(groups), tuple(code_words))


def kind_satisfied(kind: str, text: str, needs: QuestionNeeds) -> bool:
    low = (text or "").lower()
    if kind == "code":
        if not _CODE_TOKEN.search(text or ""):
            return False
        return not needs.code_words or any(w in low for w in needs.code_words)
    if kind == "number":
        return bool(_NUMBER.search(text or "")) or any(re.search(rf"\b{w}\b", low) for w in NUMBER_WORDS) or "%" in low
    if kind == "limit":
        groups = needs.limit_groups or tuple(LIMIT_GROUPS)
        return any(re.search(rf"\b{re.escape(w)}\b", low) for g in groups for w in LIMIT_GROUPS[g])
    if kind == "default":
        return any(w in low for w in DEFAULT_WORDS)
    if kind == "time":
        return bool(_NUMBER.search(text or "")) or any(re.search(rf"\b{w}\b", low) for w in TIME_WORDS)
    return True


# ------------------------------------------------------------------------------------------------------------ evidence units
@dataclass
class Unit:
    marker: str
    chunk_id: str
    rank: int
    order: int
    text: str                                   # one sentence, verbatim from the chunk
    own: frozenset
    head: frozenset                             # section heading terms (context, not evidence by themselves)
    prev_line: Optional[str] = None             # an immediately preceding short heading-like line (e.g. "Transaction EL43")
    follow: Optional[str] = None                # the sentence after a list introduction ending in ":"
    chunk_text: str = ""

    def full_text(self) -> str:
        return " ".join(x for x in (self.prev_line, self.text) if x)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _lines(text: str) -> List[Tuple[str, List[str]]]:
    out = []
    for line in (text or "").split("\n"):
        line = line.strip()
        if line:
            out.append((line, T.split_sentences(line)))
    return out


def build_units(items: Sequence[Any]) -> List[Unit]:
    """Sentence units from context items (``ContextItem``: rendered_text) or chunk hits (``ChunkHit``: text)."""
    units: List[Unit] = []
    order = 0
    for it in items:
        body = getattr(it, "rendered_text", None) or it.text
        marker = getattr(it, "marker", "")
        head = frozenset(terms2(" ".join(it.heading_path) if it.heading_path else it.title))
        lines = _lines(body)
        for li, (line, sents) in enumerate(lines):
            for si, s in enumerate(sents):
                order += 1
                prev = None
                if si == 0 and li > 0:
                    pl = lines[li - 1][0]
                    if len(pl.split()) <= 8 and not re.search(r"[.!?:]\s*$", pl):
                        prev = pl
                follow = sents[si + 1] if s.rstrip().endswith(":") and si + 1 < len(sents) else None
                units.append(Unit(marker, it.chunk_id, int(getattr(it, "rank", 0)), order, s, frozenset(terms2(s)), head, prev, follow, it.text))
    return units


def unit_kinds_ok(u: Unit, needs: QuestionNeeds) -> bool:
    return all(kind_satisfied(k, u.full_text(), needs) for k in needs.kinds)


USE_IDF = False                                             # iteration-2 ablation switch; OFF = shipped behaviour (IDF over-abstained on DEV2, see data/phase11_1_contract.md Amendment 2c)


def focus_weights(needs: QuestionNeeds, units: Sequence[Unit]) -> Dict[str, float]:
    """IDF over the sentences of the retrieved evidence: ln((N+1)/(df+0.5)); a term found in every sentence (the topic itself) counts little, a term found nowhere counts most."""
    n = len(units)
    out = {}
    if not USE_IDF:
        return {t: 1.0 for t in needs.focus}
    for t in needs.focus:
        df = sum(1 for u in units if t in u.own or t in u.head)
        out[t] = max(0.1, math.log((n + 1) / (df + 0.5)))
    return out


def unit_score(u: Unit, needs: QuestionNeeds, w: Optional[Dict[str, float]] = None) -> float:
    if not needs.focus:
        return 0.0
    f = set(needs.focus)
    own = u.own | frozenset(terms2(u.prev_line or ""))
    if not (own & f):
        return 0.0
    weight = (lambda t: w[t]) if w else (lambda t: 1.0)
    total = sum(weight(t) for t in f)
    return (sum(weight(t) for t in own & f) + HEAD_WEIGHT * sum(weight(t) for t in (u.head - own) & f)) / total


@dataclass
class Decision:
    supported: bool
    reason: str                                  # SUPPORTED | ASKED_TERM_NOT_IN_EVIDENCE | KIND_NOT_IN_EVIDENCE | LOW_FOCUS_COVERAGE | NO_QUERY_TERMS | NO_EVIDENCE
    detail: Dict[str, Any] = field(default_factory=dict)


def assess(needs: QuestionNeeds, units: Sequence[Unit], tau: float = TAU) -> Tuple[Decision, List[Unit]]:
    """Decide whether the evidence supports an answer; return the supporting units (best first, document order not applied)."""
    if not needs.focus:
        return Decision(False, "NO_QUERY_TERMS"), []
    if not units:
        return Decision(False, "NO_EVIDENCE"), []
    present = set()
    for u in units:
        present |= u.own | u.head | frozenset(terms2(u.prev_line or ""))
    missing = [a for a in needs.asked if a not in present]
    if missing:
        return Decision(False, "ASKED_TERM_NOT_IN_EVIDENCE", {"missing": missing}), []
    pool = [u for u in units if unit_kinds_ok(u, needs)]
    if needs.kinds and not pool:
        return Decision(False, "KIND_NOT_IN_EVIDENCE", {"kinds": list(needs.kinds)}), []
    w = focus_weights(needs, units)
    scored = sorted(((unit_score(u, needs, w), u) for u in pool), key=lambda p: (-p[0], p[1].rank, p[1].order))
    if not scored or scored[0][0] < tau:
        return Decision(False, "LOW_FOCUS_COVERAGE", {"best": round(scored[0][0], 3) if scored else 0.0, "tau": tau}), []
    best = scored[0][0]
    keep = [(s, u) for s, u in scored if s >= max(tau, KEEP_RATIO * best)][:EXTRACTIVE_MAX_SENTENCES]
    return Decision(True, "SUPPORTED", {"best": round(best, 3), "tau": tau}), [u for _, u in keep]


# ------------------------------------------------------------------------------------------------------------ generator
class EvidenceExtractiveGenerator:
    """Deterministic extractive generator with an evidence-sufficiency decision. Public name stays ``extractive`` (same generator family, same API contract)."""
    name = "extractive"

    def __init__(self, tau: float = TAU) -> None:
        self.tau = tau
        self.last: Optional[Dict[str, Any]] = None

    def generate(self, question: str, context: Any) -> GenerationResult:
        needs = analyze_question(question)
        units = build_units(context.items)
        decision, chosen = assess(needs, units, self.tau)
        record: Dict[str, Any] = {"checked": True, "supported": decision.supported, "reason": decision.reason, "detail": decision.detail, **needs.to_dict(), "selected": []}
        self.last = record
        if not decision.supported:
            return GenerationResult(NO_ANSWER_TEXT, True, self.name, "")
        chosen = sorted(chosen, key=lambda u: u.order)
        weights = focus_weights(needs, units)
        lines: List[str] = []
        for u in chosen:
            if u.prev_line and needs.kinds and not kind_satisfied(needs.kinds[0], u.text, needs):
                lines.append(f"{u.prev_line} [{u.marker}]")
            lines.append(f"{u.text} [{u.marker}]")
            if u.follow:
                lines.append(f"{u.follow} [{u.marker}]")
            record["selected"].append({"marker": u.marker, "chunk_id": u.chunk_id, "sentence": u.text, "coverage": round(unit_score(u, needs, weights), 3), "kinds_ok": unit_kinds_ok(u, needs)})
        dedup: List[str] = []
        for ln in lines:                                                    # a header line attached to two neighbouring sentences is shown once
            if ln not in dedup:
                dedup.append(ln)
        text = "\n".join(dedup)
        return GenerationResult(text, False, self.name, text)


class EvidenceGuard:
    """Pre/post evidence checks around any generator (used for the LLM generator; tested with stub clients only)."""

    def __init__(self, inner: Any, tau: float = TAU) -> None:
        self.inner, self.tau = inner, tau
        self.name = getattr(inner, "name", "generator")
        self.last: Optional[Dict[str, Any]] = None

    def generate(self, question: str, context: Any) -> GenerationResult:
        needs = analyze_question(question)
        units = build_units(context.items)
        decision, _ = assess(needs, units, self.tau)
        self.last = {"checked": True, "supported": decision.supported, "reason": decision.reason, "detail": decision.detail, **needs.to_dict(), "selected": []}
        if not decision.supported:                                          # the model is not even asked: the evidence cannot contain the answer
            return GenerationResult(NO_ANSWER_TEXT, True, self.name, "")
        res = self.inner.generate(question, context)
        if not res.refused:
            body = re.sub(r"\[S\d+\]", "", res.text)
            if not all(kind_satisfied(k, body, needs) for k in needs.kinds):  # the produced text lacks the kind of detail that was asked for
                self.last.update({"supported": False, "reason": "ANSWER_LACKS_ASKED_DETAIL"})
                return GenerationResult(NO_ANSWER_TEXT, True, self.name, res.raw_text, res.prompt)
        return res


# ------------------------------------------------------------------------------------------------------------ retrieval widening
class EvidenceRetriever:
    """Wraps a ``PageRetriever``. Unchanged unless the question needs a kind of detail that the retrieved chunks cannot supply; then the best chunk of the SAME page
    that can supply it (sentence-level kind + focus coverage >= tau) is promoted to rank 1. Cited as itself; ``metadata['promoted']`` marks it."""

    def __init__(self, base: Any, tau: float = TAU) -> None:
        self._base = base
        self.tau = tau
        self.last_promoted: Optional[str] = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)

    def _supplies(self, needs: QuestionNeeds, units: Sequence[Unit], weight_units: Optional[Sequence[Unit]] = None) -> bool:
        w = focus_weights(needs, weight_units or units)
        return any(unit_kinds_ok(u, needs) and unit_score(u, needs, w) >= self.tau for u in units)

    def retrieve_in_page(self, query: str, guide_id: str, page_id: str, top_k: int = 5) -> List[Any]:
        self.last_promoted = None
        hits = self._base.retrieve_in_page(query, guide_id, page_id, top_k=top_k)
        needs = analyze_question(query)
        if not needs.kinds or not hits:
            return hits
        if self._supplies(needs, build_units(hits)):
            return hits
        total = len(self._base.page_chunks(guide_id, page_id))
        ranked = self._base.retrieve_in_page(query, guide_id, page_id, top_k=max(top_k, total))
        have = {h.chunk_id for h in hits}
        for h in ranked:
            if h.chunk_id in have:
                continue
            if self._supplies(needs, build_units([h]), build_units(hits) + build_units([h])):
                self.last_promoted = h.chunk_id
                promoted = dataclasses.replace(h, rank=1, metadata={**dict(h.metadata), "promoted": "detail_evidence", "dense_rank": h.rank})
                rest = [dataclasses.replace(x, rank=i + 2) for i, x in enumerate(hits[: max(0, top_k - 1)])]
                return [promoted] + rest
        return hits


# ------------------------------------------------------------------------------------------------------------ support chain
def verify_support_chain(answer: str, context: Any) -> Dict[str, Any]:
    """Independent traceability check: every answer sentence must be a verbatim span of the original text of the chunk its marker names."""
    by = {i.marker: i for i in context.items}
    records, ok = [], True
    for line in T.split_cited_sentences(answer or ""):
        markers = re.findall(r"\[(S\d+)\]", line)
        body = _norm(re.sub(r"\[S\d+\]", "", line))
        if not body:
            continue
        hit = [m for m in markers if m in by and body in _norm(by[m].text)]
        records.append({"sentence": body[:160], "markers": markers, "verbatim_in": hit})
        ok = ok and bool(hit)
    return {"ok": ok and bool(records), "verbatim_all": ok and bool(records), "sentences": records}


def build_evidence_pipeline(base: Any, tau: float = TAU, widen: bool = True, generator: str = "extractive", llm_client: Any = None) -> Any:
    """A ``RagPipeline`` identical to ``base`` except for the retriever wrapper (optional) and the evidence-checked generator."""
    import rag_pipeline as RP
    retriever = EvidenceRetriever(base.retriever, tau) if widen else base.retriever
    gen = EvidenceExtractiveGenerator(tau) if generator == "extractive" else EvidenceGuard(base.generator, tau)
    return RP.RagPipeline(base.backend, retriever, base.ctx, base.corpus, gen, base.count_tokens, cards=list(base.cards.values()), config=base.cfg)
