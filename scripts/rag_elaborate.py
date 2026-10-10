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

* **wider evidence** - "elaborate" uses a 12-candidate pool and a 12-chunk / 2,000-token context only for this pass;
  its primary query is the resolved topic, plus one deterministic aspect query over the same identity-verified page;
  the two ranked lists are interleaved and deduplicated, while other intents keep their shipped scoped settings;
* **novel selection** - for "elaborate", exact and high-overlap evidence already present in the previous answer is removed
  before sufficiency checks and selection, and near-duplicate selected facts are collapsed; up to six supported units
  are emitted, with no repeated opener. Other intent-specific selection rules remain as before;
* **intent handling** - an example requires a sentence that actually introduces an example; a reason requires a
  reason-bearing sentence; continuation prefers evidence from later in the document; simplification picks the shortest
  sentences that still carry the topic;
* **fragment quality** - the shared evidence-layer pre-selection filter drops standalone headings, breadcrumbs,
  menu/TOC labels, numbered navigation fragments, malformed OCR-like text, and incomplete list lead-ins; short clauses
  with an explanatory predicate remain eligible;
* **the same verification** - the composed text is verified by the unchanged ``verify_grounding`` (in-page grounding +
  citation normalisation) inside ``RagPipeline`` and by the unchanged ``support_chain`` check in ``rag_service``. Every
  sentence is a verbatim span of the chunk its marker names.

Everything else remains untouched: routing, the ranker, EvidenceGuard, the gates, normal QA settings, and citation
validation. The sole normal-QA change is this shared deterministic pre-selection quality filter. If the wider pass cannot
find anything *new* the generator refuses, and the existing abstention path
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
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rag_evidence as EV  # noqa: E402  shared deterministic analysis, scoring, and evidence-quality helpers
import rag_followup as FU  # noqa: E402  the follow-up vocabulary (so "elaborate" never counts as a new topic term)
import rag_generate as RG  # noqa: E402  GenerationResult / NO_ANSWER_TEXT
import rag_text as T  # noqa: E402

# ---------------------------------------------------------------------------------------------------------------- scope
# Legacy wider settings for the other already-shipped follow-up intents; their retrieval/selection remains unchanged.
WIDE_K_CHUNKS = 10
WIDE_MAX_CONTEXT_CHUNKS = 8
WIDE_CONTEXT_BUDGET_TOKENS = 1400
# The "elaborate" intent uses one wider, two-view pool. It stays on the selected page; no page-family expansion is
# enabled because current admitted pages are short and page expansion would add scope without measured benefit.
ELABORATION_MIN_CANDIDATE_POOL_SIZE = 8
ELABORATION_CANDIDATE_POOL_SIZE = 12
ELABORATION_MAX_CONTEXT_CHUNKS = 12
ELABORATION_CONTEXT_BUDGET_TOKENS = 2000
ELABORATION_MAX_SELECTED_UNITS = 6
WORKFLOW_ELABORATION_MAX_UNITS = 12  # soft cap; keep a documented step/bullet intact rather than cutting its sequence
RICH_RATIO = 0.30                    # keep sentences scoring >= 30% of the best (minimal path: 0.6)
MAX_RICH_SENTENCES = 8
MAX_SIMPLE_SENTENCES = 2
MAX_EXAMPLE_SENTENCES = 3
REQUIRED_NEW_ELABORATE = 2           # minimum novel units; also preserves the shipped threshold for other wide intents
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
_INVOICING_ANCHOR = re.compile(r"\binvoic\w*\b", re.I)
_BUDGET_BILLING = re.compile(r"\bbudget[\s-]+bill(?:ing|ings|s)?\b", re.I)
_INVOICING_EVIDENCE = re.compile(
    r"\binvoic\w*\b|\bbill[\s-]+creation\b|\bbill[\s-]+checks?\b|\boutsort\w*\b|"
    r"\bprint[\s-]+documents?\b|\bsimulat\w*\b|\bcontract[\s-]+accounting\s+documents?\b|"
    r"\bposting\s+documents?\b|\bpostings?\b|\breleas(?:e|es|ed|ing)\b",
    re.I,
)
_INVOICING_POSTING_DETAIL = re.compile(
    r"\bposting\s+documents?\b|\bposted\s+in\s+subledger\s+accounting\b",
    re.I,
)
_INVOICING_PRINT_CONFIGURATION = re.compile(r"\b(?:reprint\w*|output\s+type|print\s+parameter)\b", re.I)
_INVOICING_REVERSAL_DETAIL = re.compile(
    r"\b(?:bill\s+reversal|full\s+reversal|invoic\w*\s+reversal|reverse\s+document|"
    r"reverse\s+print\s+document|offsetting\s+entries)\b",
    re.I,
)

# Shared evidence-quality predicates live in rag_evidence and run before normal or scoped-follow-up scoring.
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
    r"\b(?:FS\s*[-‐‑‒–—]?\s*CD|Insurance|PS\s*[-‐‑‒–—]?\s*CD|Public\s+Sector|"
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


def _quality_norm(text: str) -> str:
    return EV.quality_norm(text)


def _is_low_quality_fragment(text: str, heading_labels: Iterable[str] = ()) -> bool:
    """Compatibility shim for the shared evidence-layer quality predicate."""
    return EV.is_low_quality_fragment(text, tuple(heading_labels))


def _elaboration_quality_filter(units: Sequence[Any], context: Any) -> Tuple[List[Any], List[Any], int]:
    """Compatibility wrapper around the quality filter shared with normal QA."""
    kept, excluded, details = EV.filter_quality_units(units, context)
    return kept, excluded, int(details["excluded_adjacent_fragments"])


def _topic_identity_filter(units: Sequence[Any], context: Any, active_identity: Optional[Mapping[str, Any]]) -> Tuple[List[Any], Optional[Dict[str, Any]]]:
    """Keep only units whose source chunks match the active answer's verified guide/page/industry identity."""
    if not isinstance(active_identity, Mapping):
        return list(units), None
    expected = {
        "guide_id": str(active_identity.get("guide_id") or ""),
        "page_id": str(active_identity.get("page_id") or ""),
        "industry": str(active_identity.get("industry") or ""),
    }
    supported_industry = expected["industry"].strip().casefold() in {
        "sap utilities/isu", "sap utilities/is-u", "sap utilities (is-u)", "sap utilities / is-u", "is-u", "isu",
    }
    items = list(getattr(context, "items", ()) or ())
    rejected_markers: set = set()
    mismatches: List[Dict[str, str]] = []
    if not expected["guide_id"] or not expected["page_id"] or not supported_industry or not items:
        rejected_markers = {str(getattr(unit, "marker", "") or "") for unit in units if getattr(unit, "marker", None)}
        details = {"ok": False, "reason": "ACTIVE_TOPIC_IDENTITY_INCOMPLETE", "expected": expected,
                   "excluded_markers": sorted(m for m in rejected_markers if m)}
        return [], details

    allowed_markers: set = set()
    for item in items:
        marker = str(getattr(item, "marker", "") or "")
        guide_id = str(getattr(item, "guide_id", "") or "")
        page_id = str(getattr(item, "page_id", "") or "")
        valid = (guide_id.casefold() == expected["guide_id"].casefold()
                 and page_id.casefold() == expected["page_id"].casefold())
        if marker and valid:
            allowed_markers.add(marker)
        elif marker:
            rejected_markers.add(marker)
            mismatches.append({"marker": marker, "guide_id": guide_id, "page_id": page_id})

    kept = [unit for unit in units if str(getattr(unit, "marker", "") or "") in allowed_markers]
    for unit in units:
        marker = str(getattr(unit, "marker", "") or "")
        if marker and marker not in allowed_markers:
            rejected_markers.add(marker)
    details = {
        "ok": bool(kept),
        "expected": expected,
        "excluded_markers": sorted(marker for marker in rejected_markers if marker),
        "mismatches": mismatches,
    }
    return kept, details


def _industry_scope_units(units: Sequence[Any], context: Any, anchor: str, previous_answer: str,
                          new_terms: Iterable[str], expected_industry: Optional[str] = None) -> Tuple[List[Any], Optional[str], int, List[str]]:
    """Exclude explicit non-Utilities component evidence only in a routed IS-U elaboration.

    The question/relationship terms can explicitly request another industry (or a comparison); in that case the
    evidence is left alone. A context marker names a whole chunk, not one sentence: when that chunk's heading or text
    explicitly identifies Insurance/FS-CD, PSCD/Public Sector, or IS-T, reject its marker and all of its units before
    selection. Otherwise a clean sibling sentence could keep the rejected chunk in citations and Sources. The
    sentence-local check below also catches an explicit component label attached to an individual evidence unit.
    """
    original = list(units)
    terms = {str(term).casefold() for term in new_terms}
    explicit_alternate = bool(_OTHER_INDUSTRY_COMPONENT.search(anchor or "")) or bool(
        terms & {"insurance", "insur", "pscd", "telecommunications", "telecommunication", "fs-cd", "is-t"}
    ) or {"public", "sector"}.issubset(terms) or {"fs", "cd"}.issubset(terms)
    if explicit_alternate:
        return original, None, 0, []

    scope_parts = [anchor or "", previous_answer or ""]
    headings_by_marker: Dict[str, List[str]] = {}
    headings_by_chunk: Dict[str, List[str]] = {}
    excluded_markers: set = set()
    for item in getattr(context, "items", ()) or ():
        heading_text = _item_heading_text(item)
        marker = str(getattr(item, "marker", "") or "")
        chunk_id = getattr(item, "chunk_id", None)
        item_text: List[str] = []
        for attr in ("text", "rendered_text"):
            value = getattr(item, attr, "")
            if value:
                value = str(value)
                item_text.append(value)
                scope_parts.append(value)
        if heading_text:
            scope_parts.append(heading_text)
            if marker:
                headings_by_marker.setdefault(marker, []).append(heading_text)
            if chunk_id is not None:
                headings_by_chunk.setdefault(str(chunk_id), []).append(heading_text)
        # Reject the source marker at chunk granularity. This covers headings stored on a ContextItem even when its
        # chunk id is absent/mismatched, as well as malformed PSCD labels embedded in the chunk body.
        if marker and _OTHER_INDUSTRY_COMPONENT.search(" ".join((heading_text, *item_text))):
            excluded_markers.add(marker)

    for unit in original:
        scope_parts.extend((getattr(unit, "text", ""), getattr(unit, "chunk_text", "")))
        if getattr(unit, "prev_line", None):
            scope_parts.append(unit.prev_line)
    industry_is_isu = str(expected_industry or "").strip().casefold() in {
        "sap utilities/isu", "sap utilities/is-u", "sap utilities (is-u)", "sap utilities / is-u", "is-u", "isu",
    }
    if not industry_is_isu and not _ISU_SCOPE.search(" ".join(str(part) for part in scope_parts if part)):
        return original, None, 0, []

    candidates: List[Any] = []
    for unit in original:
        marker = str(getattr(unit, "marker", "") or "")
        if marker and marker in excluded_markers:
            continue
        chunk_id = str(getattr(unit, "chunk_id", ""))
        local_headings = " ".join([*headings_by_marker.get(marker, ()), *headings_by_chunk.get(chunk_id, ())])
        local_text = " ".join(str(part) for part in (
            getattr(unit, "prev_line", None), getattr(unit, "text", ""), getattr(unit, "follow", None), local_headings,
        ) if part)
        if _OTHER_INDUSTRY_COMPONENT.search(local_text):
            if marker:
                excluded_markers.add(marker)
        else:
            candidates.append(unit)
    # A citation marker is chunk-wide. If any of its units carries an explicit other-industry label, remove every
    # unit under that marker so neither answer text nor verifier-derived citations can retain the rejected source.
    relevant = [u for u in candidates if str(getattr(u, "marker", "") or "") not in excluded_markers]
    return relevant, "IS-U", len(original) - len(relevant), sorted(excluded_markers)


def scoped_config(base_config: Any, intent: Optional[str] = None) -> Any:
    """Return a follow-up-only config; only an explicit "elaborate" intent activates dual-view retrieval."""
    if intent == "elaborate":
        requested_pool_size = int(
            getattr(base_config, "elaboration_candidate_pool_size", 0) or ELABORATION_CANDIDATE_POOL_SIZE
        )
        candidate_pool_size = min(
            ELABORATION_CANDIDATE_POOL_SIZE,
            max(ELABORATION_MIN_CANDIDATE_POOL_SIZE, requested_pool_size),
        )
        return dataclasses.replace(
            base_config,
            k_chunks=max(int(getattr(base_config, "k_chunks", 5)), candidate_pool_size),
            max_context_chunks=max(int(getattr(base_config, "max_context_chunks", 4)), ELABORATION_MAX_CONTEXT_CHUNKS),
            context_budget_tokens=max(int(getattr(base_config, "context_budget_tokens", 700)), ELABORATION_CONTEXT_BUDGET_TOKENS),
            elaboration_candidate_pool_size=candidate_pool_size,
            elaboration_retrieval_enabled=True,
        )
    return dataclasses.replace(
        base_config,
        k_chunks=max(int(getattr(base_config, "k_chunks", 5)), WIDE_K_CHUNKS),
        max_context_chunks=max(int(getattr(base_config, "max_context_chunks", 4)), WIDE_MAX_CONTEXT_CHUNKS),
        context_budget_tokens=max(int(getattr(base_config, "context_budget_tokens", 700)), WIDE_CONTEXT_BUDGET_TOKENS),
        elaboration_candidate_pool_size=0,
        elaboration_retrieval_enabled=False,
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


def _evidence_overlap(left: str, right: str) -> Dict[str, Any]:
    """Cheap, conservative lexical near-duplicate score; no embeddings or paraphrase model are used."""
    left_norm, right_norm = _quality_norm(_CITE.sub("", str(left or ""))), _quality_norm(_CITE.sub("", str(right or "")))
    if left_norm and left_norm == right_norm:
        return {"exact": True, "overlap": len(EV.terms2(left_norm)), "jaccard": 1.0, "shorter_coverage": 1.0}
    left_terms, right_terms = set(EV.terms2(left_norm)), set(EV.terms2(right_norm))
    if not left_terms or not right_terms:
        return {"exact": False, "overlap": 0, "jaccard": 0.0, "shorter_coverage": 0.0}
    overlap = len(left_terms & right_terms)
    return {
        "exact": False,
        "overlap": overlap,
        "jaccard": overlap / len(left_terms | right_terms),
        "shorter_coverage": overlap / min(len(left_terms), len(right_terms)),
    }


def _is_redundant_evidence(candidate: str, references: Iterable[str]) -> Tuple[bool, Dict[str, Any]]:
    """Exact/high-overlap repeats are removed; excerpts with fewer than four content stems need an exact match."""
    best: Dict[str, Any] = {"exact": False, "overlap": 0, "jaccard": 0.0, "shorter_coverage": 0.0}
    for reference in references:
        score = _evidence_overlap(candidate, reference)
        if score["exact"]:
            return True, score
        if score["overlap"] >= best["overlap"]:
            best = score
    redundant = (
        (best["overlap"] >= 5 and best["jaccard"] >= 0.72)
        or (best["overlap"] >= 4 and best["shorter_coverage"] >= 0.90)
    )
    return redundant, best


def _novelty_filter_units(units: Sequence[Any], previous_answer: str) -> Tuple[List[Any], Dict[str, Any]]:
    """Drop elaboration evidence already shown, and detach repeated adjacent lines before selection/grounding."""
    previous = sentences_of(previous_answer)
    kept: List[Any] = []
    repeated: List[Dict[str, Any]] = []
    removed_adjacent = 0
    candidate_markers = {str(getattr(unit, "marker", "") or "") for unit in units if getattr(unit, "marker", None)}
    kept_markers: set = set()
    for unit in units:
        duplicate, score = _is_redundant_evidence(getattr(unit, "text", ""), previous)
        if duplicate:
            marker = str(getattr(unit, "marker", "") or "")
            repeated.append({"marker": marker or None, "overlap": int(score["overlap"]),
                             "jaccard": round(float(score["jaccard"]), 3), "exact": bool(score["exact"])})
            continue
        for attr in ("prev_line", "follow"):
            line = getattr(unit, attr, None)
            if line and _is_redundant_evidence(line, previous)[0]:
                setattr(unit, attr, None)
                removed_adjacent += 1
        kept.append(unit)
        marker = str(getattr(unit, "marker", "") or "")
        if marker:
            kept_markers.add(marker)
    excluded_markers = sorted(marker for marker in candidate_markers if marker not in kept_markers)
    return kept, {
        "enabled": True,
        "candidate_units": len(units),
        "excluded_units": len(repeated),
        "excluded_adjacent_lines": removed_adjacent,
        "excluded_markers": excluded_markers,
        "markers_with_repeated_evidence": sorted({item["marker"] for item in repeated if item["marker"]}),
        "repeats": repeated,
    }


def _invoicing_scope_filter(
    units: Sequence[Any], anchor: str, new_terms: Iterable[str] = (),
) -> Tuple[List[Any], Optional[Dict[str, Any]]]:
    """Keep invoice elaborations on invoice evidence instead of treating the page title as sentence-level support.

    The SAP Invoicing Procedure page also contains a separate Budget Billing branch and a general bill-recipient result.
    Those are not evidence for an invoicing elaboration merely because they share the same page/chunk or heading. A
    complete source list item is filtered as one unit so its trailing sentence cannot leak after its budget-billing
    introduction is removed. If the original question or the follow-up explicitly asks about budget billing, that branch
    remains eligible.
    """
    if not _INVOICING_ANCHOR.search(anchor or ""):
        return list(units), None

    new_term_list = [str(term) for term in new_terms]
    requested_terms = set(EV.terms2(anchor or "")) | {term.casefold() for term in new_term_list}
    requested_text = " ".join((anchor or "", *new_term_list))
    requested_budget = bool(_BUDGET_BILLING.search(requested_text)) or {"budget", "bill"}.issubset(requested_terms)
    requested_print_detail = bool(re.search(r"\b(?:print|reprint|parameter|output)\w*\b", requested_text, re.I))
    requested_reversal = bool(_INVOICING_REVERSAL_DETAIL.search(requested_text)) or bool(
        requested_terms & {"revers", "reversal"}
    )
    relevant_evidence = _INVOICING_EVIDENCE

    groups: Dict[Tuple[str, str, int], List[Any]] = {}
    group_for_unit: Dict[int, Tuple[str, str, int]] = {}
    for unit in units:
        group_key = _source_sequence_group(unit)
        if group_key is not None:
            groups.setdefault(group_key, []).append(unit)
            group_for_unit[id(unit)] = group_key

    allowed_groups: Dict[Tuple[str, str, int], bool] = {}
    for group_key, group in groups.items():
        group_text = " ".join(str(getattr(unit, "text", "") or "") for unit in group)
        if _BUDGET_BILLING.search(group_text) and not requested_budget:
            allowed_groups[group_key] = False
            continue
        if _INVOICING_PRINT_CONFIGURATION.search(group_text) and not requested_print_detail:
            allowed_groups[group_key] = False
            continue
        if _INVOICING_REVERSAL_DETAIL.search(group_text) and not requested_reversal:
            allowed_groups[group_key] = False
            continue
        allowed_groups[group_key] = bool(
            relevant_evidence.search(group_text)
            or (requested_budget and _BUDGET_BILLING.search(group_text))
        )

    kept: List[Any] = []
    excluded: List[Any] = []
    for unit in units:
        group_key = group_for_unit.get(id(unit))
        if group_key is not None:
            keep = allowed_groups[group_key]
        else:
            text = str(getattr(unit, "text", "") or "")
            keep = (
                (requested_budget or not _BUDGET_BILLING.search(text))
                and (requested_print_detail or not _INVOICING_PRINT_CONFIGURATION.search(text))
                and (requested_reversal or not _INVOICING_REVERSAL_DETAIL.search(text))
                and bool(relevant_evidence.search(text) or (requested_budget and _BUDGET_BILLING.search(text)))
            )
        (kept if keep else excluded).append(unit)

    details = {
        "enabled": True,
        "topic": "invoicing",
        "explicit_budget_billing": requested_budget,
        "explicit_print_detail": requested_print_detail,
        "explicit_reversal_detail": requested_reversal,
        "excluded_units": len(excluded),
        "excluded_markers": sorted(
            {str(getattr(unit, "marker", "")) for unit in excluded if getattr(unit, "marker", None)}
        ),
    }
    return kept, details


def _source_sequence_group(unit: Any) -> Optional[Tuple[str, str, int]]:
    """Identify one numbered step or bullet by its original source line and document chunk."""
    sequence = EV._source_sequence_info(unit)
    if sequence is None or not EV._has_workflow_heading(unit):
        return None
    kind, _position = sequence
    chunk_id = str(getattr(unit, "chunk_id", "") or "")
    line_index = getattr(unit, "source_line_index", -1)
    if type(line_index) is int and line_index >= 0:
        return chunk_id, kind, line_index

    source_line = _quality_norm(str(getattr(unit, "source_line", "") or ""))
    lines = str(getattr(unit, "chunk_text", "") or "").splitlines()
    if source_line:
        for index, line in enumerate(lines):
            if _quality_norm(line) == source_line:
                return chunk_id, kind, index

    sentence = _quality_norm(str(getattr(unit, "text", "") or ""))
    marker_pattern = r"^\s*\d{1,3}[.)]\s+" if kind == "numbered" else r"^\s*[-*•]\s+"
    for index, line in enumerate(lines):
        prefix = re.match(marker_pattern, line)
        if not prefix:
            continue
        candidates = {_quality_norm(part) for part in T.split_sentences(line[prefix.end():])}
        if sentence and sentence in candidates:
            return chunk_id, kind, index
    return None


def _source_sequence_prefix(unit: Any) -> str:
    """Return a list marker only for the first factual sentence of its original source line."""
    line = str(getattr(unit, "source_line", "") or "")
    sentence = _quality_norm(str(getattr(unit, "text", "") or ""))
    for pattern in (r"^\s*\d{1,3}[.)]\s+", r"^\s*[-*•]\s+"):
        match = re.match(pattern, line)
        if not match:
            continue
        source_sentences = [
            _quality_norm(part) for part in T.split_sentences(line[match.end():]) if _quality_norm(part)
        ]
        if sentence and source_sentences and sentence == source_sentences[0]:
            return match.group(0).lstrip()
    return ""


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
                 anchor: str = "", active_identity: Optional[Mapping[str, Any]] = None) -> None:
        if intent not in ELABORATION_INTENTS:
            raise ValueError(f"unknown intent: {intent}")
        self.intent = intent
        self.anchor = anchor            # the previous subject: the sufficiency analysis is done on it, never on the message's own wording
        self.active_identity = dict(active_identity) if isinstance(active_identity, Mapping) else None
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
        units, topic_consistency = _topic_identity_filter(EV.build_units(context.items), context, self.active_identity)
        if topic_consistency is not None and not topic_consistency.get("ok"):
            record = {"checked": True, "supported": False, "reason": "ACTIVE_TOPIC_MISMATCH",
                      "detail": {"reason": "selected evidence does not match the active page identity"},
                      **needs.to_dict(), "intent": self.intent, "selected": [], "topic_consistency": topic_consistency,
                      "elaborated": None}
            self.last = record
            return RG.GenerationResult(RG.NO_ANSWER_TEXT, True, self.name, "", evidence=copy.deepcopy(record))
        expected_industry = self.active_identity.get("industry") if self.active_identity else None
        units, industry_scope, excluded_industry_units, excluded_industry_markers = _industry_scope_units(
            units, context, self.anchor or question, self.previous_answer, self.new_terms, expected_industry=expected_industry
        )
        units, excluded_quality_units, quality_filter_details = EV.filter_quality_units(units, context)
        excluded_adjacent_fragments = quality_filter_details["excluded_adjacent_fragments"]
        if self.intent == "elaborate":
            units, topic_scope_filter = _invoicing_scope_filter(units, self.anchor or question, self.new_terms)
        else:
            topic_scope_filter = None
        novelty_filter: Optional[Dict[str, Any]] = None
        if self.intent == "elaborate":
            units, novelty_filter = _novelty_filter_units(units, self.previous_answer)
        quality_fragment_markers = sorted({str(getattr(unit, "marker", "")) for unit in excluded_quality_units
                                           if getattr(unit, "marker", None)})
        usable_quality_markers = {str(getattr(unit, "marker", "")) for unit in units if getattr(unit, "marker", None)}
        fully_excluded_quality_markers = [marker for marker in quality_fragment_markers if marker not in usable_quality_markers]
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
        if topic_consistency is not None:
            record["topic_consistency"] = topic_consistency
        if topic_scope_filter is not None:
            record["topic_scope_filter"] = topic_scope_filter
        if excluded_quality_units or excluded_adjacent_fragments:
            record["quality_filter"] = {
                "excluded_units": len(excluded_quality_units),
                "excluded_markers": fully_excluded_quality_markers,
                "markers_with_fragments": quality_fragment_markers,
                "excluded_adjacent_fragments": excluded_adjacent_fragments,
                "excluded_list_leadins": quality_filter_details["excluded_list_leadins"],
            }
        if industry_scope:
            record["industry_scope"] = {"preferred": industry_scope, "excluded_units": excluded_industry_units,
                                        "excluded_markers": excluded_industry_markers}
        if novelty_filter is not None:
            record["novelty_filter"] = novelty_filter
        if not decision.supported:
            # the topic itself is not supported by the retrieved evidence: unchanged behaviour (abstain -> no answer)
            record["elaborated"] = None
            self.last = record
            return RG.GenerationResult(RG.NO_ANSWER_TEXT, True, self.name, "", evidence=copy.deepcopy(record))

        chosen = self._choose(needs, units, baseline, context)
        if self.intent == "elaborate" and chosen:
            # A list introduction is useful only when its attached list item will actually survive novelty filtering
            # and appear with it. Never leave the colon-ended lead-in alone if that context line is repeated/dropped.
            candidate_texts = tuple(unit.text for unit in chosen)
            chosen = [
                unit for unit in chosen
                if not EV.is_incomplete_list_leadin(unit.text, unit.follow, getattr(unit, "heading_labels", ()))
                or (unit.follow and not _is_redundant_evidence(unit.follow, (*self.previous, *candidate_texts))[0])
            ]
        if not chosen:
            # the documentation supports the topic but has nothing to add to what the user already has
            record.update(elaborated=False, reason_added="NO_ADDITIONAL_EVIDENCE")
            self.last = record
            return RG.GenerationResult(RG.NO_ANSWER_TEXT, True, self.name, "", evidence=copy.deepcopy(record))

        weights = EV.focus_weights(needs, units)
        line_records: List[Dict[str, Any]] = []
        chosen_texts = [unit.text for unit in chosen]
        emitted_context_lines: List[str] = []

        def append_context_line(sentence: str, marker: str, section_key: str) -> None:
            if self.intent == "elaborate":
                references = (*self.previous, *chosen_texts, *emitted_context_lines)
                if _is_redundant_evidence(sentence, references)[0]:
                    return
            line = f"{sentence} [{marker}]"
            if not any(entry["text"] == line for entry in line_records):
                line_records.append({"text": line, "section_key": section_key, "sequence_group": None})
                emitted_context_lines.append(sentence)

        for u in chosen:
            sequence_group = _source_sequence_group(u) if self.intent == "elaborate" else None
            section_key = (
                SECTION_HOW_IT_WORKS_RELATIONSHIPS
                if sequence_group is not None
                else presentation_section_key(u.text)
            )
            if u.prev_line and needs.kinds and not EV.kind_satisfied(needs.kinds[0], u.text, needs):
                append_context_line(u.prev_line, u.marker, section_key)

            fact = u.text
            prefix = _source_sequence_prefix(u) if sequence_group is not None else ""
            if prefix:
                source_prefix = prefix.strip()
                if fact.lstrip().startswith(source_prefix):
                    fact = fact.lstrip()[len(source_prefix):].lstrip()
            cited_fact = f"{fact} [{u.marker}]"
            if sequence_group is not None and line_records and line_records[-1]["sequence_group"] == sequence_group:
                # Multiple cited sentences from one numbered step/bullet stay in the same Markdown list item; every
                # sentence retains its own marker, while the original source prefix appears only once.
                line_records[-1]["text"] += f" {cited_fact}"
            else:
                line = f"{prefix}{cited_fact}"
                if not any(entry["text"] == line for entry in line_records):
                    line_records.append({"text": line, "section_key": section_key, "sequence_group": sequence_group})
            if u.follow:
                append_context_line(u.follow, u.marker, section_key)
            record["selected"].append({"marker": u.marker, "chunk_id": u.chunk_id, "sentence": u.text,
                                       "coverage": round(EV.unit_score(u, needs, weights, frame_normalization=self.frame_normalization), 3),
                                       "kinds_ok": EV.unit_kinds_ok(u, needs)})
        dedup_records: List[Dict[str, Any]] = []
        seen_lines = set()
        for entry in line_records:                                    # a heading attached to two sentences is shown once
            if entry["text"] not in seen_lines:
                seen_lines.add(entry["text"])
                dedup_records.append(entry)
        dedup = [entry["text"] for entry in dedup_records]
        line_sections = {entry["text"]: entry["section_key"] for entry in dedup_records}
        text = "\n".join(dedup)
        # Keep the exact answer lines and citations. Categories are grouped globally for display; line_orders on each
        # section reconstruct the unchanged document order. Context lines inherit the category of their evidence sentence.
        record["presentation_sections"] = group_presentation_lines(
            (line_sections[ln], ln) for ln in dedup
        )
        record["elaborated"] = True
        if self.intent == "elaborate":
            record["added"] = sum(1 for u in chosen if not _is_redundant_evidence(u.text, self.previous)[0])
        else:
            record["added"] = sum(1 for u in chosen if _norm(u.text) not in self.previous)
        self.last = record
        return RG.GenerationResult(text, False, self.name, text, evidence=copy.deepcopy(record))

    # ------------------------------------------------------------------------------------------------------------ pick
    def _choose_workflow_groups(self, units: Sequence[Any]) -> List[Any]:
        """Continue with unused, complete source steps/bullets before falling back to looser lexical selection."""
        groups: Dict[Tuple[str, str, int], List[Any]] = {}
        for unit in units:
            group_key = _source_sequence_group(unit)
            if group_key is None or EV._is_answer_boilerplate(unit.text, process_question=True):
                continue
            if _is_redundant_evidence(unit.text, self.previous)[0]:
                continue
            groups.setdefault(group_key, []).append(unit)

        ordered_groups = sorted(groups.values(), key=lambda group: min(unit.order for unit in group))
        chosen: List[Any] = []
        for group in ordered_groups:
            pending: List[Any] = []
            for unit in sorted(group, key=lambda candidate: candidate.order):
                references = list(self.previous) + [candidate.text for candidate in chosen]
                references.extend(candidate.text for candidate in pending)
                if _is_redundant_evidence(unit.text, references)[0]:
                    continue
                pending.append(unit)
            if not pending:
                continue
            # The cap is soft: stop only at a source-step boundary, never midway through a reversal or other list item.
            if chosen and len(chosen) + len(pending) > WORKFLOW_ELABORATION_MAX_UNITS:
                break
            chosen.extend(pending)
            if len(chosen) >= WORKFLOW_ELABORATION_MAX_UNITS:
                break
        return sorted(chosen, key=lambda unit: unit.order)

    def _choose(self, needs: Any, units: Sequence[Any], baseline: Sequence[Any], context: Any) -> List[Any]:
        """The sentences this intent wants, in document reading order (empty = nothing to add)."""
        weights = EV.focus_weights(needs, units)
        anchor = self.anchor or getattr(needs, "question", "")
        process_question = EV.is_process_question(anchor)
        invoicing_question = bool(_INVOICING_ANCHOR.search(anchor))
        if self.intent == "elaborate" and (process_question or invoicing_question):
            workflow_units = self._choose_workflow_groups(units)
            if workflow_units:
                if invoicing_question:
                    # The page's overview also records where posting documents are posted. Keep that verified key detail
                    # with the focused workflow, in document order, when it adds something not already shown.
                    picked = list(workflow_units)
                    references: List[str] = [*self.previous, *(unit.text for unit in picked)]
                    for unit in units:
                        if _source_sequence_group(unit) is not None or not _INVOICING_POSTING_DETAIL.search(unit.text):
                            continue
                        if _is_redundant_evidence(unit.text, references)[0]:
                            continue
                        picked.append(unit)
                        references.append(unit.text)
                    return sorted(picked, key=lambda unit: unit.order)
                return workflow_units

        scored: List[Tuple[float, Any]] = []
        for u in units:
            if not EV.unit_kinds_ok(u, needs):
                continue
            score = EV.unit_score(u, needs, weights, frame_normalization=self.frame_normalization)
            if score > 0:
                scored.append((score, u))
        if self.intent == "elaborate":
            # References and incomplete workflow framing must not set the relevance cutoff or fill the answer budget.
            scored = [
                (score, unit) for score, unit in scored
                if not EV._is_answer_boilerplate(unit.text, process_question=process_question)
            ]
        if not scored:
            return []
        best = max(s for s, _ in scored)
        keep = [u for s, u in sorted(scored, key=lambda p: (-p[0], p[1].rank, p[1].order)) if s >= RICH_RATIO * best]

        if self.intent == "elaborate":
            # The original answer is already visible above this turn: select only novel, non-redundant evidence.
            # Keep the existing evidence score/rerank ordering, then show the chosen facts in document order.
            novel: List[Any] = []
            for unit in keep:
                if _is_redundant_evidence(unit.text, self.previous)[0]:
                    continue
                if any(_is_redundant_evidence(unit.text, (picked.text,))[0] for picked in novel):
                    continue
                novel.append(unit)
                if len(novel) >= ELABORATION_MAX_SELECTED_UNITS:
                    break
            if self.previous and len(novel) < REQUIRED_NEW_ELABORATE:
                return []
            return sorted(novel, key=lambda unit: unit.order)

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

        if self.intent in ("reason", "continuation", "reference"):
            # Preserve the established rules for the non-elaborate follow-up intents.
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
                    new_terms: Iterable[str] = (), tau: float = EV.SHIPPED_TAU,
                    active_identity: Optional[Mapping[str, Any]] = None) -> Any:
    """A ``RagPipeline`` that shares every heavy object of ``base`` (retriever, corpus, cards, backend) but runs the
    follow-up pass: wider config + the intent-aware generator. Building it is cheap - nothing is loaded again."""
    import rag_pipeline as RP

    fn = bool(getattr(base.cfg, "evidence_frame_normalization", False))
    gen = IntentExtractiveGenerator(intent, previous_answer=previous_answer, tau=tau, frame_normalization=fn,
                                    focus_terms=new_terms, anchor=anchor, active_identity=active_identity)
    return RP.RagPipeline(base.backend, base.retriever, base.ctx, base.corpus, gen, base.count_tokens,
                          cards=list(base.cards.values()), config=scoped_config(base.cfg, intent=intent))


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
