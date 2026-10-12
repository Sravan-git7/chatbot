#!/usr/bin/env python3
"""Phase 3 Evaluation Metrics Module.

Implements deterministic evaluation checks:
- Behavioral alignment (answer, partial_answer, clarify, abstain, unavailable)
- Key-fact recall and missing fact identification
- Citation precision and citation coverage
- Unsupported sentences and lexical overlap checks
- Hallucination checks (transaction codes, identifiers, numbers)
- Completeness of enumerations
- Procedural limitation correctness
- Grounding via exact substring verification (for A0/A2)
- Explicit tagging of automated vs. human-review metrics
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import rag_evidence as RE
import rag_generate as RG
import rag_text as T

_MARKER = re.compile(r"\[S(\d+)\]")
_CODE_TOKEN = re.compile(r"\b[A-Z][A-Z0-9_]*[0-9_][A-Z0-9_]*\b")
_NUMBER_TOKEN = re.compile(r"(?<![A-Za-z0-9_])\d+(?:[.,]\d+)?(?![A-Za-z0-9_])")

EXCLUDED_CODES = frozenset({"SAP", "IS", "SYSTEM", "THE", "AND", "FOR", "NOT", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10"})


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", (text or "").lower()).split())


def extract_markers(text: str) -> List[str]:
    return [f"S{m}" for m in _MARKER.findall(text or "")]


def determine_actual_behavior(pipeline_status: str, answer_text: str, refused: bool) -> str:
    """Classify the actual system behavior."""
    if pipeline_status == "page_not_ingested" or pipeline_status == "unresolved_identity":
        return "unavailable"
    if pipeline_status in ("out_of_domain", "no_relevant_page"):
        return "abstain"
    if pipeline_status == "insufficient_context" or refused:
        return "abstain"

    # Check for procedural limitation in answer
    if answer_text and RE.is_procedural_limitation_sentence(answer_text):
        return "partial_answer"

    # Check for clarification phrasing
    if answer_text and any(p in answer_text.lower() for p in ("could you specify", "please clarify", "which document", "which type")):
        return "clarify"

    if answer_text and answer_text.strip() != RG.NO_ANSWER_TEXT:
        return "answer"

    return "abstain"


def check_key_facts(answer_text: str, expected_key_facts: Sequence[str]) -> Tuple[int, List[str]]:
    """Check how many expected atomic key facts appear in the answer."""
    if not expected_key_facts or not answer_text:
        return 0, list(expected_key_facts or [])

    ans_norm = _norm(answer_text)
    recalled = 0
    missing: List[str] = []

    for fact in expected_key_facts:
        fact_norm = _norm(fact)
        # Check either direct substring or high token coverage
        if fact_norm in ans_norm:
            recalled += 1
        else:
            fact_tokens = [t for t in fact_norm.split() if t not in T.STOPWORDS and len(t) > 2]
            if fact_tokens and all(tok in ans_norm for tok in fact_tokens):
                recalled += 1
            else:
                missing.append(fact)

    return recalled, missing


def check_prohibited_claims(answer_text: str, prohibited_claims: Sequence[str]) -> List[str]:
    """Check whether any prohibited claims or fabricated details appear in the answer."""
    detected: List[str] = []
    if not answer_text or not prohibited_claims:
        return detected

    ans_norm = _norm(answer_text)
    ans_stems = set(RE.stem2(w) for w in ans_norm.split() if w not in T.STOPWORDS and len(w) > 2)

    for claim in prohibited_claims:
        claim_norm = _norm(claim)
        claim_stems = [RE.stem2(t) for t in claim_norm.split() if t not in T.STOPWORDS and len(t) > 2]
        if not claim_stems:
            if claim_norm in ans_norm:
                detected.append(claim)
            continue
        # If at least 75% of claim content stems appear in the answer, flag the claim
        overlap = sum(1 for s in claim_stems if s in ans_stems)
        if overlap >= max(2, int(0.75 * len(claim_stems))):
            detected.append(claim)
        elif claim_norm in ans_norm:
            detected.append(claim)

    return detected


def check_citations(answer_text: str, valid_markers: Set[str]) -> Dict[str, Any]:
    """Evaluate citation coverage and citation precision."""
    if not answer_text or answer_text.strip() == RG.NO_ANSWER_TEXT:
        return {
            "total_sentences": 0,
            "cited_sentences": 0,
            "citation_coverage": 1.0,
            "cited_markers": [],
            "invalid_markers": [],
            "citation_precision": 1.0,
        }

    lines = [ln.strip() for ln in answer_text.split("\n") if ln.strip()]
    content_lines: List[str] = []
    for ln in lines:
        if RE.is_procedural_limitation_sentence(ln):
            continue
        content_lines.append(ln)

    if not content_lines:
        return {
            "total_sentences": 0,
            "cited_sentences": 0,
            "citation_coverage": 1.0,
            "cited_markers": [],
            "invalid_markers": [],
            "citation_precision": 1.0,
        }

    cited_count = 0
    all_cited_markers: List[str] = []
    invalid_markers: List[str] = []

    for ln in content_lines:
        markers = extract_markers(ln)
        if markers:
            cited_count += 1
            for m in markers:
                all_cited_markers.append(m)
                if m not in valid_markers:
                    invalid_markers.append(m)

    coverage = round(cited_count / max(1, len(content_lines)), 3)
    precision = round((len(all_cited_markers) - len(invalid_markers)) / max(1, len(all_cited_markers)), 3)

    return {
        "total_sentences": len(content_lines),
        "cited_sentences": cited_count,
        "citation_coverage": coverage,
        "cited_markers": all_cited_markers,
        "invalid_markers": invalid_markers,
        "citation_precision": precision,
    }


def check_hallucinated_tokens(answer_text: str, context_items: Sequence[Mapping[str, Any]]) -> List[str]:
    """Identify any technical codes or identifiers in the answer that do not appear in the context."""
    if not answer_text or answer_text.strip() == RG.NO_ANSWER_TEXT:
        return []

    # Concatenate all context text
    context_text = " ".join((item.get("text") or "") for item in context_items)

    answer_codes = {c.upper() for c in _CODE_TOKEN.findall(answer_text) if c.upper() not in EXCLUDED_CODES}
    context_codes = {c.upper() for c in _CODE_TOKEN.findall(context_text) if c.upper() not in EXCLUDED_CODES}

    hallucinated: List[str] = []
    for c in answer_codes:
        if c not in context_codes and not c.startswith("CASE"):
            hallucinated.append(c)

    return sorted(hallucinated)


def check_substring_grounding(answer_text: str, context_items: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Verify that cited sentences are exact substrings of the cited chunks (A0/A2 requirement)."""
    by_marker = {item["marker"]: _norm(item.get("text", "")) for item in context_items if item.get("marker")}

    sentences = [ln.strip() for ln in answer_text.split("\n") if ln.strip()]
    checked_count = 0
    verbatim_count = 0
    unsupported_spans: List[str] = []

    for s in sentences:
        if RE.is_procedural_limitation_sentence(s):
            continue
        markers = extract_markers(s)
        cleaned = re.sub(r"\[S\d+\]", "", s).strip()
        cleaned_norm = _norm(cleaned)
        if not cleaned_norm:
            continue
        checked_count += 1

        is_verbatim = False
        for m in markers:
            if m in by_marker and cleaned_norm in by_marker[m]:
                is_verbatim = True
                break

        if is_verbatim:
            verbatim_count += 1
        else:
            unsupported_spans.append(cleaned[:100])

    ratio = round(verbatim_count / max(1, checked_count), 3) if checked_count else 1.0
    return {
        "sentences_checked": checked_count,
        "verbatim_sentences": verbatim_count,
        "substring_support_ratio": ratio,
        "unsupported_spans": unsupported_spans,
        "all_verbatim": verbatim_count == checked_count,
    }


def evaluate_case(case: Mapping[str, Any], answer_text: str, pipeline_status: str,
                  refused: bool, context_items: Sequence[Mapping[str, Any]],
                  adapter_id: str = "A0") -> Dict[str, Any]:
    """Execute complete deterministic evaluation checks for a single test case."""
    actual_behavior = determine_actual_behavior(pipeline_status, answer_text, refused)
    expected_behavior = case.get("expected_behavior", "answer")

    behavior_match = (actual_behavior == expected_behavior)
    # Relaxed match: if expected clarify and actual is partial_answer or vice versa
    if not behavior_match and expected_behavior in ("partial_answer", "clarify") and actual_behavior in ("partial_answer", "clarify"):
        behavior_match = True

    # Key fact matching
    expected_facts = case.get("key_facts") or []
    recalled_facts_count, missing_facts = check_key_facts(answer_text, expected_facts)
    key_fact_recall = round(recalled_facts_count / max(1, len(expected_facts)), 3) if expected_facts else 1.0

    # Prohibited claims
    prohibited = case.get("prohibited_claims") or []
    prohibited_detected = check_prohibited_claims(answer_text, prohibited)

    # Citations
    valid_markers = {item["marker"] for item in context_items if item.get("marker")}
    citation_metrics = check_citations(answer_text, valid_markers)

    # Hallucinated tokens
    hallucinated_tokens = check_hallucinated_tokens(answer_text, context_items)

    # Substring grounding check (applicable to exact span generators like A0)
    substring_metrics = check_substring_grounding(answer_text, context_items)

    # Procedural limitation correctness
    category = case.get("category")
    procedural_limitation_correct: Optional[bool] = None
    if category == "procedural_lacks_steps":
        procedural_limitation_correct = (
            actual_behavior == "partial_answer" and
            RE.is_procedural_limitation_sentence(answer_text)
        )
    elif category == "procedural_documented":
        procedural_limitation_correct = not RE.is_procedural_limitation_sentence(answer_text)

    # Enumeration completeness check
    enumeration_complete: Optional[bool] = None
    if category == "enumeration":
        enumeration_complete = (len(missing_facts) == 0)

    # Topic consistency check for follow-ups
    topic_consistent: Optional[bool] = None
    if category == "followup_and_transition":
        expected_src = case.get("expected_source_id")
        if expected_src and context_items:
            # Check whether routed chunks belong to expected source
            item_srcs = {item.get("source_id") for item in context_items}
            topic_consistent = (expected_src in item_srcs)
        else:
            topic_consistent = True

    # Fail closed check for unavailable documentation
    fail_closed_correct: Optional[bool] = None
    if category == "unavailable_documentation":
        fail_closed_correct = (pipeline_status == "page_not_ingested" and actual_behavior == "unavailable")

    # Metrics requiring human review tagging
    human_review_reasons: List[str] = []
    requires_human_review = False

    if adapter_id.startswith("A3"):
        requires_human_review = True
        human_review_reasons.append("Paraphrase semantic faithfulness requires human evaluation (substring matching is inapplicable)")

    if category in ("adversarial_false_premise", "ambiguous"):
        requires_human_review = True
        human_review_reasons.append(f"Nuanced reasoning in {category} category benefits from qualitative inspection")

    if prohibited_detected:
        requires_human_review = True
        human_review_reasons.append("Prohibited claim heuristic triggered: verify semantic intent")

    return {
        "case_id": case.get("case_id"),
        "category": category,
        "adapter_id": adapter_id,
        "expected_behavior": expected_behavior,
        "actual_behavior": actual_behavior,
        "behavior_match": behavior_match,
        "key_facts_total": len(expected_facts),
        "key_facts_recalled": recalled_facts_count,
        "key_fact_recall": key_fact_recall,
        "missing_facts": missing_facts,
        "prohibited_claims_detected": prohibited_detected,
        "prohibited_claims_count": len(prohibited_detected),
        "citation_coverage": citation_metrics["citation_coverage"],
        "citation_precision": citation_metrics["citation_precision"],
        "invalid_markers": citation_metrics["invalid_markers"],
        "hallucinated_tokens": hallucinated_tokens,
        "substring_grounding_ratio": substring_metrics["substring_support_ratio"],
        "unsupported_spans": substring_metrics["unsupported_spans"],
        "procedural_limitation_correct": procedural_limitation_correct,
        "enumeration_complete": enumeration_complete,
        "topic_consistent": topic_consistent,
        "fail_closed_correct": fail_closed_correct,
        "requires_human_review": requires_human_review,
        "human_review_reasons": human_review_reasons,
    }
