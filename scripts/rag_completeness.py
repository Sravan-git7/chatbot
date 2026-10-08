"""Phase 3 Answer-Completeness Module for SURA.

Provides deterministic, feature-flagged enhancements:
1. SURA_INTENT_AWARE: Deterministic intent classification and retrieval-only query normalization.
2. SURA_SECTION_SELECTION: Section tagging and complementary evidence selection across distinct headings.
3. SURA_ADDITIONAL_EVIDENCE: Extract complementary verified evidence sentences from cited chunks.

All features are feature-flagged and default to OFF (False).
Zero LLM, zero generative synthesis, 100% verbatim and deterministic.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple


def is_intent_aware_enabled() -> bool:
    return os.environ.get("SURA_INTENT_AWARE", "").strip().lower() in ("1", "true", "yes")


def is_section_selection_enabled() -> bool:
    return os.environ.get("SURA_SECTION_SELECTION", "").strip().lower() in ("1", "true", "yes")


def is_additional_evidence_enabled() -> bool:
    return os.environ.get("SURA_ADDITIONAL_EVIDENCE", "").strip().lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# 1. Deterministic Intent Classification & Retrieval-Only Query Normalization
# ---------------------------------------------------------------------------

_CONVERSATIONAL_PREFIXES = re.compile(
    r"^(?:can\s+you\s+(?:please\s+)?(?:tell\s+me|explain|describe|show\s+me)|"
    r"could\s+you\s+(?:please\s+)?(?:tell\s+me|explain|describe)|"
    r"i\s+(?:would\s+like|want)\s+to\s+(?:know|understand)|"
    r"please\s+(?:tell\s+me|explain|describe)|"
    r"what\s+can\s+you\s+tell\s+me\s+about)\s+",
    re.IGNORECASE,
)

_PROCEDURAL_PATTERNS = re.compile(
    r"\b(?:how\s+do\s+i|how\s+to|how\s+can\s+i|how\s+are|how\s+is\s+(?:.*?)(?:created|handled|processed|executed|run|carried\s+out|configured)|"
    r"steps\s+to|procedure\s+for|what\s+steps|process\s+of)\b",
    re.IGNORECASE,
)

_DEFINITION_PATTERNS = re.compile(
    r"\b(?:what\s+is\s+a|what\s+is\s+an|what\s+is\s+the|what\s+is|what\s+are|define|definition\s+of|meaning\s+of|overview\s+of)\b",
    re.IGNORECASE,
)

_RELATIONSHIP_PATTERNS = re.compile(
    r"\b(?:relat(?:e|es|ion|ionship)|connect(?:s|ed|ion)|differ(?:s|ence|ences)|distinction|link(?:s|ed)?\s+between|link(?:s|ed)?\s+to)\b",
    re.IGNORECASE,
)

_STATUS_MONITORING_PATTERNS = re.compile(
    r"\b(?:status|monitor(?:ing|ed|s)?|track(?:ing|ed|s)?|analyz(?:e|ed|ing|is|es)?|check(?:ing|ed|s)?|overview|display(?:ing|ed|s)?)\b",
    re.IGNORECASE,
)


def classify_intent(query: str) -> Dict[str, Any]:
    """Classify the user question into a deterministic intent category."""
    q = (query or "").strip()
    intents: List[str] = []

    if _DEFINITION_PATTERNS.search(q):
        intents.append("definition")
    if _PROCEDURAL_PATTERNS.search(q):
        intents.append("procedural")
    if _RELATIONSHIP_PATTERNS.search(q):
        intents.append("relationship")
    if _STATUS_MONITORING_PATTERNS.search(q):
        intents.append("status_monitoring")

    primary_intent = intents[0] if intents else "general"
    return {
        "primary_intent": primary_intent,
        "intents": intents or ["general"],
        "is_procedural": "procedural" in intents,
        "is_definition": "definition" in intents,
        "is_relationship": "relationship" in intents,
    }


def normalize_retrieval_query(query: str) -> str:
    """Normalize query strictly for retrieval/routing token matching.

    Removes conversational fluff prefixes while leaving domain tokens intact.
    Does NOT modify the user-visible question.
    """
    if not is_intent_aware_enabled():
        return query

    q = (query or "").strip()
    cleaned = _CONVERSATIONAL_PREFIXES.sub("", q).strip()
    return cleaned if cleaned else q


# ---------------------------------------------------------------------------
# 2. Section Tagging & Complementary Evidence Selection
# ---------------------------------------------------------------------------

def get_unit_section_signature(unit: Any) -> str:
    """Derive a stable section signature from a unit's heading labels and chunk_id."""
    labels = getattr(unit, "heading_labels", ()) or ()
    if labels:
        # Top heading label normalized
        return " > ".join(str(lbl).strip().lower() for lbl in labels[:2] if str(lbl).strip())
    chunk_id = getattr(unit, "chunk_id", "") or ""
    return str(chunk_id)


def select_complementary_units(
    scored_units: Sequence[Tuple[float, Any]],
    tau: float,
    keep_ratio: float,
    max_sentences: int = 3,
) -> List[Any]:
    """Select units favoring complementary section coverage over redundant sentences.

    If SURA_SECTION_SELECTION is disabled, falls back strictly to the baseline selection.
    """
    if not scored_units or scored_units[0][0] < tau:
        return []

    best_score = scored_units[0][0]
    cutoff = max(tau, keep_ratio * best_score)
    valid_candidates = [(s, u) for s, u in scored_units if s >= cutoff]

    if not is_section_selection_enabled():
        # Baseline: top-N highest scoring units directly
        return [u for _, u in valid_candidates[:max_sentences]]

    # Section-aware complementary selection:
    # 1. Always pick the top-ranked unit
    chosen: List[Any] = [valid_candidates[0][1]]
    chosen_sections: Set[str] = {get_unit_section_signature(valid_candidates[0][1])}

    # 2. For subsequent slots, prioritize units from different sections that still meet cutoff
    remaining = valid_candidates[1:]

    # First pass: try to pick from unrepresented sections
    unrepresented = []
    same_section = []
    for s, u in remaining:
        sec = get_unit_section_signature(u)
        if sec not in chosen_sections:
            unrepresented.append(u)
        else:
            same_section.append(u)

    while len(chosen) < max_sentences and (unrepresented or same_section):
        if unrepresented:
            next_u = unrepresented.pop(0)
            chosen.append(next_u)
            chosen_sections.add(get_unit_section_signature(next_u))
        elif same_section:
            chosen.append(same_section.pop(0))

    return chosen


# ---------------------------------------------------------------------------
# 3. Additional Evidence Extraction
# ---------------------------------------------------------------------------

def extract_additional_evidence(
    units: Sequence[Any],
    chosen_units: Sequence[Any],
    needs: Any,
    weights: Dict[str, float],
    unit_score_fn: Any,
    min_score: float = 0.35,
    max_additional: int = 2,
) -> List[Dict[str, Any]]:
    """Extract secondary verified evidence sentences from cited chunks.

    Captures verifiable facts from the cited chunks that did not fit in the primary answer.
    """
    if not is_additional_evidence_enabled():
        return []

    chosen_ids = {id(u) for u in chosen_units}
    chosen_texts = {getattr(u, "text", "").strip() for u in chosen_units}
    chosen_markers = {getattr(u, "marker", "") for u in chosen_units}

    candidates = []
    for u in units:
        if id(u) in chosen_ids or getattr(u, "text", "").strip() in chosen_texts:
            continue
        # Restrict additional evidence strictly to chunks whose markers are in the cited context
        if getattr(u, "marker", "") not in chosen_markers:
            continue
        score = unit_score_fn(u, needs, weights)
        if score >= min_score:
            candidates.append((score, u))

    candidates.sort(key=lambda p: -p[0])
    results = []
    seen_texts = set()
    for s, u in candidates:
        txt = getattr(u, "text", "").strip()
        if txt and txt not in seen_texts:
            seen_texts.add(txt)
            results.append({
                "marker": getattr(u, "marker", ""),
                "chunk_id": getattr(u, "chunk_id", ""),
                "sentence": txt,
                "coverage": round(s, 3),
                "section": get_unit_section_signature(u),
            })
            if len(results) >= max_additional:
                break

    return results
