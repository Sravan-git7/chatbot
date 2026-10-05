"""Scoped elaboration for follow-up intents (additive; the production answer path is untouched).

Why this module exists
----------------------
The production generator (``rag_evidence.EvidenceExtractiveGenerator``) selects a **minimal sufficiency set**: the
evidence layer keeps the sentences that score at least ``KEEP_RATIO`` (0.6) of the best sentence, at most
``EXTRACTIVE_MAX_SENTENCES`` (3), out of a context built from ``k_chunks`` (5) within a 700-token budget. That is the
right behaviour for "answer this question" - and it is exactly why "elaborate" used to return the previous answer
verbatim: the resolved follow-up query has the same content terms as the question it resolves to, so the same
sentences score highest and the same minimal set is selected.

What this module adds
---------------------
For a follow-up whose intent asks for *more* (or for a different kind of content), the same pipeline is run once more
with a narrow, explicitly scoped difference:

* **wider evidence** - the follow-up pass reads more of the already-routed document (``k_chunks``/``max_context_chunks``/
  budget raised for this pass only) instead of the top few chunks;
* **wider selection** - every sentence that is still clearly on-topic is eligible (30% of the best score instead of
  60%), ordered in document reading order, deduplicated by section;
* **intent handling** - elaboration skips what the previous answer already said and adds new evidence; an example
  requires a sentence that actually introduces an example; a reason requires a reason-bearing sentence; continuation
  prefers evidence from later in the document; simplification picks the shortest sentences that still carry the topic;
* **the same verification** - the composed text is verified by the unchanged ``verify_grounding`` (in-page grounding +
  citation normalisation) inside ``RagPipeline`` and by the unchanged ``support_chain`` check in ``rag_service``. Every
  sentence is a verbatim span of the chunk its marker names.

Everything else is untouched: routing, the ranker, EvidenceGuard, the gates, the generator used for normal questions,
citations. If the wider pass cannot find anything *new* the generator refuses, and the existing abstention path
(``GENERATOR_REFUSED`` -> ``unable_to_verify``) tells the user the documentation does not provide more - it never
invents and never pads.
"""
from __future__ import annotations

import copy
import dataclasses
import re
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rag_evidence as EV  # noqa: E402  the evidence layer's own analysis/scoring helpers (reused, not changed)
import rag_followup as FU  # noqa: E402  the follow-up vocabulary (so "elaborate" never counts as a new topic term)
import rag_generate as RG  # noqa: E402  GenerationResult / NO_ANSWER_TEXT
import rag_text as T  # noqa: E402

# ---------------------------------------------------------------------------------------------------------------- scope
# Only the follow-up pass uses these; PipelineConfig defaults and the production service stay exactly as they are.
WIDE_K_CHUNKS = 10
WIDE_MAX_CONTEXT_CHUNKS = 8
WIDE_CONTEXT_BUDGET_TOKENS = 1400
RICH_RATIO = 0.30                    # keep sentences scoring >= 30% of the best (minimal path: 0.6)
MAX_RICH_SENTENCES = 8
MAX_SIMPLE_SENTENCES = 2
MAX_EXAMPLE_SENTENCES = 3
REQUIRED_NEW_ELABORATE = 2           # an elaboration must add at least this many sentences the user has not seen
ELABORATION_INTENTS = ("elaborate", "example", "simplify", "reason", "continuation", "reference")

_EXAMPLES = re.compile(r"\b(for example|for instance|e\.g\.|such as|example[s]? of|an example)\b", re.I)
# a sentence that starts with one of these cannot stand on its own as a simpler statement of the topic
_DANGLING = re.compile(r"^(this|these|those|that|it|they|such|the latter|the former)\s+(is|are|was|were|does|do|did|has|have|had|can|may|will|would|should|applies|apply|include[sd]?|mean[s]?|refer[s]?|enable[s]?|tend[s]?|contain[s]?|belong[s]?|result[s]?)\b", re.I)
_DANGLING_REF = re.compile(r"^(see\b|for more information\b|note\b|for additional information\b)", re.I)
_VERBISH = re.compile(r"\b(is|are|was|were|can|may|must|should|will|has|have|had|enables?|contains?|includes?|assigns?|manages?|uses?|create[sd]?|tend|mean[s]?|refer[s]?|applie[sd]?|applies|provide[sd]?|require[sd]?|allow[s]?|define[sd]?|posts?|posted|processe[sd]?|execute[sd]?|billed?|determines?|represents?)\b", re.I)
_DEFINING = re.compile(r"\b(is|are|enables?|means?|refers?|represents?|contains?|includes?|describes?|defines?|consists?)\b", re.I)
_REASON = re.compile(r"\b(because|since|due to|therefore|thus|so that|in order to|reason|reasons|result[s]? in|hence)\b", re.I)
_CONTINUE = re.compile(r"\b(next|after|then|subsequent|following|once|finally|step)\b", re.I)
_CITE = re.compile(r"\[S\d+\]")

# Presentation-only categories. These keys are stable API values; labels are rendered by the UI.
SECTION_WHAT_IT_IS_DOES = "what_it_is_does"
SECTION_HOW_IT_WORKS_RELATIONSHIPS = "how_it_works_relationships"
SECTION_CONDITIONS_PREREQUISITES = "conditions_prerequisites"
SECTION_KEY_DETAILS = "key_details"
PRESENTATION_SECTION_KEYS = (
    SECTION_WHAT_IT_IS_DOES,
    SECTION_HOW_IT_WORKS_RELATIONSHIPS,
    SECTION_CONDITIONS_PREREQUISITES,
    SECTION_KEY_DETAILS,
)

# Deliberately narrow lexical cues: uncertain sentences fall back to Key details. Conditions take precedence
# over process cues so a sentence with an explicit prerequisite is not mislabeled as a process step.
_SECTION_CONDITION = re.compile(
    r"\b(?:if|unless|only if|only when|provided that|when|whenever|as long as|subject to|"
    r"requires?|required|requirement|prerequisite[s]?|mandatory|must|depending on|until|once)\b",
    re.I,
)
_SECTION_PROCESS_RELATION = re.compile(
    r"\b(?:next|then|subsequent(?:ly)?|following|finally|step[s]?|process(?:es|ing)?|workflow|sequence|flow|"
    r"because|since|due to|therefore|thus|so that|as a result|result[s]? in|lead[s]? to|cause[s]?|"
    r"depend[s]? on|related to|relationship|associated with|linked to|connect[s]? (?:to|with)|between|"
    r"compared with|correspond[s]? to|assigned to|through|via|posts?|processes?|calculates?|updates?|"
    r"clears?|transfers?|executes?|triggers?)\b",
    re.I,
)
_SECTION_WHAT_IT_IS_DOES = re.compile(
    r"\b(?:means?|refers? to|is (?:a|an|the)|are (?:a|an|the)|is defined as|are defined as|"
    r"represents?|enables?|allows?|provides?|serves? as|is used to|are used to|describes?|defines?|"
    r"consists? of|contains?|includes?)\b",
    re.I,
)
# the follow-up wording, stemmed the same way as the evidence layer stems its focus terms
_FOLLOWUP_STEMS = frozenset(t for w in FU._FOLLOWUP_VOCAB for t in EV.terms2(w))

# If the routed page identifies the Utilities/IS-U domain, a sentence explicitly about another industry component is
# not evidence for this scoped elaboration just because it repeats "contract account". Keep this filter deliberately
# local to the scoped pass; the normal RAG generator and its standalone answers are untouched.
_ISU_SCOPE = re.compile(r"\b(?:SAP\s+Utilities\b|Utilities\s+Industry\b|IS\s*[-‐‑‒–—]?\s*U\b)", re.I)
_OTHER_INDUSTRY_COMPONENT = re.compile(
    r"\b(?:FS\s*[-‐‑‒–—]?\s*CD|Insurance|PSCD|Public\s+Sector|"
    r"IS\s*[-‐‑‒–—]?\s*T|Telecommunications)\b",
    re.I,
)


def presentation_section_key(sentence: str) -> str:
    """Conservatively classify one evidence sentence for display; this never changes answer text."""
    body = _CITE.sub("", sentence or "")
    if _SECTION_CONDITION.search(body):
        return SECTION_CONDITIONS_PREREQUISITES
    if _SECTION_PROCESS_RELATION.search(body) or _REASON.search(body) or _CONTINUE.search(body):
        return SECTION_HOW_IT_WORKS_RELATIONSHIPS
    if _SECTION_WHAT_IT_IS_DOES.search(body):
        return SECTION_WHAT_IT_IS_DOES
    return SECTION_KEY_DETAILS


def group_presentation_lines(classified_lines: Iterable[Tuple[str, str]]) -> List[Dict[str, Any]]:
    """Consolidate each category once while retaining original answer order per line.

    Category grouping can reorder interleaved lines (A, B, A becomes the A section and then the B section), so every
    line carries its zero-based position in the canonical answer. Consumers reconstruct/validate the original answer
    by sorting on ``line_orders``; the evidence text itself is never changed.
    """
    sections: List[Dict[str, Any]] = []
    by_key: Dict[str, Dict[str, Any]] = {}
    line_order = 0
    for key, line in classified_lines:
        if key not in PRESENTATION_SECTION_KEYS or not line or not line.strip():
            continue
        section = by_key.get(key)
        if section is None:
            section = {"key": key, "lines": [], "line_orders": []}
            by_key[key] = section
            sections.append(section)
        section["lines"].append(line)
        section["line_orders"].append(line_order)
        line_order += 1
    return sections


def _item_heading_text(item: Any) -> str:
    """The short, local metadata that can identify an evidence unit's section."""
    parts = [getattr(item, "title", ""), getattr(item, "section_title", "")]
    heading_path = getattr(item, "heading_path", ()) or ()
    parts.extend([heading_path] if isinstance(heading_path, str) else heading_path)
    return " ".join(str(part) for part in parts if part)


def _industry_scope_units(units: Sequence[Any], context: Any, anchor: str, previous_answer: str,
                          new_terms: Iterable[str]) -> Tuple[List[Any], Optional[str], int]:
    """Exclude explicit non-Utilities component snippets only when the routed evidence establishes an IS-U scope.

    The question/relationship terms can explicitly request another industry (or a comparison); in that case the
    evidence is left alone. For detection, broad chunk text is useful because several component labels can occur in
    one SAP chunk. For exclusion, inspect only the individual sentence, its adjacent local context, and its section
    headings so an IS-U sentence is not lost merely because a sibling sentence in the same chunk mentions FS-CD.
    """
    original = list(units)
    terms = {str(term).casefold() for term in new_terms}
    explicit_alternate = bool(_OTHER_INDUSTRY_COMPONENT.search(anchor or "")) or bool(
        terms & {"insurance", "insur", "pscd", "telecommunications", "telecommunication", "fs-cd", "is-t"}
    ) or {"public", "sector"}.issubset(terms) or {"fs", "cd"}.issubset(terms)
    if explicit_alternate:
        return original, None, 0

    scope_parts = [anchor or "", previous_answer or ""]
    local_headings: Dict[str, str] = {}
    for item in getattr(context, "items", ()) or ():
        heading_text = _item_heading_text(item)
        chunk_id = getattr(item, "chunk_id", None)
        if chunk_id is not None and heading_text:
            local_headings[str(chunk_id)] = " ".join(filter(None, (local_headings.get(str(chunk_id), ""), heading_text)))
        for attr in ("text", "rendered_text"):
            value = getattr(item, attr, "")
            if value:
                scope_parts.append(str(value))
        if heading_text:
            scope_parts.append(heading_text)
    for unit in original:
        scope_parts.extend((getattr(unit, "text", ""), getattr(unit, "chunk_text", "")))
        if getattr(unit, "prev_line", None):
            scope_parts.append(unit.prev_line)
    if not _ISU_SCOPE.search(" ".join(str(part) for part in scope_parts if part)):
        return original, None, 0

    relevant: List[Any] = []
    for unit in original:
        local_text = " ".join(str(part) for part in (
            getattr(unit, "prev_line", None), getattr(unit, "text", ""), getattr(unit, "follow", None),
            local_headings.get(str(getattr(unit, "chunk_id", "")), ""),
        ) if part)
        if not _OTHER_INDUSTRY_COMPONENT.search(local_text):
            relevant.append(unit)
    return relevant, "IS-U", len(original) - len(relevant)


def scoped_config(base_config: Any) -> Any:
    """The production configuration with a wider evidence window - for this pass only."""
    return dataclasses.replace(
        base_config,
        k_chunks=max(int(getattr(base_config, "k_chunks", 5)), WIDE_K_CHUNKS),
        max_context_chunks=max(int(getattr(base_config, "max_context_chunks", 4)), WIDE_MAX_CONTEXT_CHUNKS),
        context_budget_tokens=max(int(getattr(base_config, "context_budget_tokens", 700)), WIDE_CONTEXT_BUDGET_TOKENS),
    )


def sentences_of(answer: str) -> Tuple[str, ...]:
    """The sentences of a previously shown answer, normalised for comparison (citation markers removed)."""
    out: List[str] = []
    for line in (answer or "").split("\n"):
        body = _CITE.sub("", line).strip()
        if not body:
            continue
        for s in T.split_sentences(body):
            norm = _norm(s)
            if norm:
                out.append(norm)
    return tuple(out)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower()).strip(" .,:;")


class IntentExtractiveGenerator:
    """A wider, intent-aware sibling of ``EvidenceExtractiveGenerator`` (same ``generate`` contract, same name).

    It answers with the *same* kind of material - verbatim documentation sentences with their markers - but it is
    allowed to use more of the document for a follow-up whose intent asks for more, a different angle, or a simpler
    phrasing. It refuses (like the production generator) as soon as the evidence does not support the topic or the
    intent cannot be satisfied from the documentation.
    """

    name = "extractive"

    def __init__(self, intent: str, previous_answer: str = "", tau: float = EV.SHIPPED_TAU,
                 frame_normalization: bool = False, focus_terms: Optional[Iterable[str]] = None,
                 anchor: str = "") -> None:
        if intent not in ELABORATION_INTENTS:
            raise ValueError(f"unknown intent: {intent}")
        self.intent = intent
        self.anchor = anchor            # the previous subject: the sufficiency analysis is done on it, never on the message's own wording
        self.tau = tau
        self.frame_normalization = frame_normalization
        self.previous_answer = previous_answer
        self.previous = set(sentences_of(previous_answer))
        # for a "relationship" follow-up: the terms the *message* brought in (they must stay covered)
        self.new_terms = {t for t in (focus_terms or ()) }
        self._tls = threading.local()

    # -- same interface as the production generator (the service reads ``.last`` for the evidence record) ----------
    @property
    def last(self) -> Optional[Dict[str, Any]]:
        return getattr(self._tls, "last", None)

    @last.setter
    def last(self, value: Optional[Dict[str, Any]]) -> None:
        self._tls.last = copy.deepcopy(value) if value is not None else None

    def reset_request_state(self) -> None:
        self._tls.last = None

    # ---------------------------------------------------------------------------------------------------------- generate
    def generate(self, question: str, context: Any) -> RG.GenerationResult:
        self._tls.last = None
        needs = EV.analyze_question(self.anchor or question)
        units = EV.build_units(context.items)
        units, industry_scope, excluded_industry_units = _industry_scope_units(
            units, context, self.anchor or question, self.previous_answer, self.new_terms
        )
        if self.new_terms:                                           # a relationship follow-up: the terms the *message* added
            present: set = set()                                     # count only when the routed evidence actually covers them
            for u in units:
                present |= u.own | u.head
            extra = tuple(t for t in self.new_terms if t in present and t not in needs.focus)
            if extra:
                needs = dataclasses.replace(needs, focus=needs.focus + extra)
        decision, baseline = EV.assess(needs, units, self.tau, frame_normalization=self.frame_normalization)
        record: Dict[str, Any] = {"checked": True, "supported": decision.supported, "reason": decision.reason,
                                  "detail": decision.detail, **needs.to_dict(), "intent": self.intent, "selected": []}
        if industry_scope:
            record["industry_scope"] = {"preferred": industry_scope, "excluded_units": excluded_industry_units}
        if not decision.supported:
            # the topic itself is not supported by the retrieved evidence: unchanged behaviour (abstain -> no answer)
            record["elaborated"] = None
            self.last = record
            return RG.GenerationResult(RG.NO_ANSWER_TEXT, True, self.name, "", evidence=copy.deepcopy(record))

        chosen = self._choose(needs, units, baseline, context)
        if not chosen:
            # the documentation supports the topic but has nothing to add to what the user already has
            record.update(elaborated=False, reason_added="NO_ADDITIONAL_EVIDENCE")
            self.last = record
            return RG.GenerationResult(RG.NO_ANSWER_TEXT, True, self.name, "", evidence=copy.deepcopy(record))

        weights = EV.focus_weights(needs, units)
        lines: List[str] = []
        line_sections: Dict[str, str] = {}
        for u in chosen:
            section_key = presentation_section_key(u.text)
            if u.prev_line and needs.kinds and not EV.kind_satisfied(needs.kinds[0], u.text, needs):
                line = f"{u.prev_line} [{u.marker}]"
                lines.append(line)
                line_sections.setdefault(line, section_key)
            line = f"{u.text} [{u.marker}]"
            lines.append(line)
            line_sections.setdefault(line, section_key)
            if u.follow:
                line = f"{u.follow} [{u.marker}]"
                lines.append(line)
                line_sections.setdefault(line, section_key)
            record["selected"].append({"marker": u.marker, "chunk_id": u.chunk_id, "sentence": u.text,
                                       "coverage": round(EV.unit_score(u, needs, weights, frame_normalization=self.frame_normalization), 3),
                                       "kinds_ok": EV.unit_kinds_ok(u, needs)})
        dedup: List[str] = []
        for ln in lines:                                             # a heading attached to two sentences is shown once
            if ln not in dedup:
                dedup.append(ln)
        text = "\n".join(dedup)
        # Keep the exact answer lines and citations. Categories are grouped globally for display; line_orders on each
        # section reconstruct the unchanged document order. Context lines inherit the category of their evidence sentence.
        record["presentation_sections"] = group_presentation_lines(
            (line_sections[ln], ln) for ln in dedup
        )
        record["elaborated"] = True
        record["added"] = sum(1 for u in chosen if _norm(u.text) not in self.previous)
        self.last = record
        return RG.GenerationResult(text, False, self.name, text, evidence=copy.deepcopy(record))

    # ------------------------------------------------------------------------------------------------------------ pick
    def _choose(self, needs: Any, units: Sequence[Any], baseline: Sequence[Any], context: Any) -> List[Any]:
        """The sentences this intent wants, in document reading order (empty = nothing to add)."""
        weights = EV.focus_weights(needs, units)
        scored: List[Tuple[float, Any]] = []
        for u in units:
            if not EV.unit_kinds_ok(u, needs):
                continue
            score = EV.unit_score(u, needs, weights, frame_normalization=self.frame_normalization)
            if score > 0:
                scored.append((score, u))
        if not scored:
            return []
        best = max(s for s, _ in scored)
        keep = [u for s, u in sorted(scored, key=lambda p: (-p[0], p[1].rank, p[1].order)) if s >= RICH_RATIO * best]

        if self.intent == "continuation":
            # "what happens next": the material that follows the part already shown - new sentences, with the ones
            # that read as a next step first, in document order. One new sentence is enough here (it is a different
            # question, not a request for more detail), but the answer may never be a pure repeat.
            fresh = [u for u in keep if _norm(u.text) not in self.previous]
            if not fresh:
                return []
            cued = [u for u in fresh if _CONTINUE.search(u.full_text()) or (u.follow and _CONTINUE.search(u.follow))]
            keep = cued if len(cued) >= 2 else fresh
            return sorted(keep, key=lambda u: u.order)[:MAX_RICH_SENTENCES]
        if self.intent == "example":
            # a documented example may not repeat the topic terms itself ("These include, for example, payment and
            # dunning."), so examples are taken from chunks that do carry the topic, and the sentence the example
            # belongs to is shown in front of it so the excerpt stays readable.
            strong = {u.chunk_id for u in units if EV.unit_kinds_ok(u, needs) and EV.unit_score(u, needs, weights, frame_normalization=self.frame_normalization) >= self.tau}
            ex = [u for u in units if u.chunk_id in strong and (_EXAMPLES.search(u.full_text()) or (u.follow and _EXAMPLES.search(u.follow)))]
            ex = [u for u in ex if _norm(u.text) not in self.previous][:MAX_EXAMPLE_SENTENCES]
            if not ex:
                return []
            picked: List[Any] = []
            for u in ex:
                anchor = self._leading_sentence(u, units, needs, weights)
                if anchor is not None and anchor not in picked:
                    picked.append(anchor)
                picked.append(u)
            return sorted(picked, key=lambda u: u.order)
        elif self.intent == "reason":
            reasons = [u for u in keep if _REASON.search(u.full_text()) or (u.follow and _REASON.search(u.follow))]
            keep = reasons or keep
        elif self.intent == "simplify":
            # "same content, expressed more simply": the shortest sentences that still state the topic on their own.
            # Dropped are sentences that only make sense next to the previous sentence ("This does not apply ...") and
            # pure cross-references ("See ..."); the remaining ones are shown in document order.
            on_topic = [u for s_pos, u in scored if s_pos >= self.tau]
            simple = [u for u in on_topic if len(u.text) > 20 and (u.own & set(needs.focus))
                      and _VERBISH.search(u.text) and not _DANGLING.match(u.text.strip()) and not _DANGLING_REF.match(u.text.strip())]
            # a sentence that states what the thing is ("... enables you to ...") explains better than a detail sentence
            simple = sorted(simple, key=lambda u: (0 if _DEFINING.search(u.text) else 1, len(u.text), u.order))[:MAX_SIMPLE_SENTENCES]
            return sorted(simple, key=lambda u: u.order)
        elif self.intent == "reference":
            covering = [u for u in keep if self.new_terms and (u.own & self.new_terms)]
            keep = covering or keep

        if self.intent in ("elaborate", "reason", "continuation", "reference"):
            # never hand back only what the user has already read: keep one anchor sentence, require fresh evidence
            fresh = [u for u in keep if _norm(u.text) not in self.previous]
            if self.previous:
                if len(fresh) < REQUIRED_NEW_ELABORATE:
                    return []
                opener = [u for u in keep if _norm(u.text) in self.previous][:1]
                keep = opener + fresh
            keep = keep[: MAX_RICH_SENTENCES]
        elif self.intent == "example":
            keep = [u for u in keep if _norm(u.text) not in self.previous][:MAX_EXAMPLE_SENTENCES]
        return sorted(keep, key=lambda u: u.order)

    def _leading_sentence(self, unit: Any, units: Sequence[Any], needs: Any, weights: Any) -> Optional[Any]:
        """The nearest preceding on-topic sentence of the same chunk (context for a sentence that cannot stand alone)."""
        best: Optional[Any] = None
        for u in units:
            if u.chunk_id != unit.chunk_id or u.order >= unit.order or u is unit:
                continue
            if not (u.own & set(needs.focus)):
                continue
            if not EV.unit_kinds_ok(u, needs):
                continue
            if best is None or u.order > best.order:
                best = u
        return best

def scoped_pipeline(base: Any, intent: str, previous_answer: str = "", anchor: str = "",
                    new_terms: Iterable[str] = (), tau: float = EV.SHIPPED_TAU) -> Any:
    """A ``RagPipeline`` that shares every heavy object of ``base`` (retriever, corpus, cards, backend) but runs the
    follow-up pass: wider config + the intent-aware generator. Building it is cheap - nothing is loaded again."""
    import rag_pipeline as RP

    fn = bool(getattr(base.cfg, "evidence_frame_normalization", False))
    gen = IntentExtractiveGenerator(intent, previous_answer=previous_answer, tau=tau, frame_normalization=fn,
                                    focus_terms=new_terms, anchor=anchor)
    return RP.RagPipeline(base.backend, base.retriever, base.ctx, base.corpus, gen, base.count_tokens,
                          cards=list(base.cards.values()), config=scoped_config(base.cfg))


def is_elaboration_intent(category: Optional[str]) -> bool:
    return category in ELABORATION_INTENTS or category == "relationship"   # "relationship" = the product's name for FU's "reference"


def new_terms_of(message: str, anchor: str) -> Tuple[str, ...]:
    """Content terms the follow-up message brings that the anchor question does not have (relationship questions)."""
    anchor_terms = set(EV.terms2(anchor))
    terms = [t for t in EV.terms2(message)
             if t not in anchor_terms and t not in EV.FRAME_STEMS and t not in _FOLLOWUP_STEMS]
    # The lexical tokenizer discards short code fragments such as FS-CD; retain the explicit component code so the
    # scoped domain filter can distinguish a relationship/comparison request from an unrelated extracted passage.
    for code, pattern in (("fs-cd", r"\bFS\s*[-‐‑‒–—]?\s*CD\b"), ("is-t", r"\bIS\s*[-‐‑‒–—]?\s*T\b")):
        if re.search(pattern, message or "", re.I):
            terms.append(code)
    return tuple(dict.fromkeys(terms))
