"""Deterministic response composer for SAP Utilities RAG.

Transforms canonical grounded answers and verified sources into a structured
response representation (StructuredAnswer) and coverage metadata (DocumentationCoverage).

Strict architectural constraints:
- Deterministic only (zero LLM / external network calls)
- No answer prose synthesis (all text is drawn verbatim from the canonical answer)
- No validator or grounding weakening
- If status != 'answered' or answer is missing, structured_answer is None
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

CITATION_MARKER_RE = re.compile(r"\[(S\d+)\]")


def extract_citations(text: str) -> List[str]:
    """Extract ordered unique citation markers like ['S1', 'S2'] from text."""
    if not text:
        return []
    seen = set()
    markers = []
    for m in CITATION_MARKER_RE.findall(text):
        if m not in seen:
            seen.add(m)
            markers.append(m)
    return markers


def categorize_line(line: str) -> str:
    """Deterministically categorize an answer line into a section key."""
    lower = line.lower()
    if any(k in lower for k in ("step", "prerequisite", "condition", "required", "must", "before")):
        return "conditions_and_prerequisites"
    if any(k in lower for k in ("how to", "procedure", "process", "configure", "execute", "run", "transaction")):
        return "procedure_and_usage"
    if any(k in lower for k in ("note", "important", "detail", "parameter", "code", "table")):
        return "key_details"
    return "overview"


TITLE_MAP = {
    "overview": "Overview",
    "procedure_and_usage": "Procedure & Usage",
    "conditions_and_prerequisites": "Prerequisites & Requirements",
    "key_details": "Key Details",
}


def compose_structured_answer(
    answer: str,
    sources: Sequence[Mapping[str, Any]] = (),
) -> Optional[Dict[str, Any]]:
    """Compose a structured answer from canonical answer text and verified sources.

    Returns None if the answer is empty or invalid.
    """
    if not answer or not answer.strip():
        return None

    raw_lines = [line.strip() for line in answer.split("\n") if line.strip()]
    if not raw_lines:
        return None

    # Group lines by category while preserving exact content
    sections_by_key: Dict[str, List[str]] = {}
    for line in raw_lines:
        cat = categorize_line(line)
        sections_by_key.setdefault(cat, []).append(line)

    sections: List[Dict[str, Any]] = []
    all_citations = extract_citations(answer)

    # Standard section ordering
    ordered_keys = [
        "overview",
        "procedure_and_usage",
        "conditions_and_prerequisites",
        "key_details",
    ]

    for key in ordered_keys:
        if key in sections_by_key:
            lines = sections_by_key[key]
            content = "\n".join(lines)
            sec_citations = extract_citations(content)
            sections.append({
                "title": TITLE_MAP.get(key, key.replace("_", " ").title()),
                "key": key,
                "lines": lines,
                "content": content,
                "citations": sec_citations,
            })

    # Catch any categories outside ordered_keys
    for key, lines in sections_by_key.items():
        if key not in ordered_keys:
            content = "\n".join(lines)
            sec_citations = extract_citations(content)
            sections.append({
                "title": key.replace("_", " ").title(),
                "key": key,
                "lines": lines,
                "content": content,
                "citations": sec_citations,
            })

    summary = raw_lines[0] if raw_lines else ""

    return {
        "summary": summary,
        "sections": sections,
        "citations": all_citations,
    }


def compute_documentation_coverage(
    status: str,
    sources: Sequence[Mapping[str, Any]] = (),
    metadata: Optional[Mapping[str, Any]] = None,
    citations: Sequence[str] = (),
) -> Dict[str, Any]:
    """Compute documentation coverage metrics deterministically."""
    is_answered = status == "answered"
    meta = metadata or {}
    card_title = meta.get("card_title")
    matched_topics = [str(card_title)] if card_title else []

    total_sources = len(sources)
    total_cited = len(citations)

    if not is_answered:
        return {
            "covered": False,
            "coverage_percentage": 0.0,
            "total_sources_cited": 0,
            "matched_topics": matched_topics,
            "uncovered_aspects": [status],
        }

    # Coverage percentage based on available sources vs cited markers
    if total_sources > 0:
        coverage_pct = min(100.0, round((total_cited / max(1, total_sources)) * 100.0, 1))
    else:
        coverage_pct = 100.0 if total_cited > 0 else 0.0

    return {
        "covered": is_answered and total_cited > 0,
        "coverage_percentage": coverage_pct,
        "total_sources_cited": total_cited,
        "matched_topics": matched_topics,
        "uncovered_aspects": [],
    }


def compose_response(
    answer: str,
    sources: Sequence[Mapping[str, Any]] = (),
    status: str = "answered",
    metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Main entrypoint: compose structured answer and coverage metadata.

    Returns:
        {
            "structured_answer": Optional[Dict[str, Any]],
            "documentation_coverage": Dict[str, Any]
        }
    """
    if status != "answered" or not answer:
        cov = compute_documentation_coverage(status, sources, metadata, ())
        return {
            "structured_answer": None,
            "documentation_coverage": cov,
        }

    structured = compose_structured_answer(answer, sources)
    all_cits = structured.get("citations", []) if structured else []
    cov = compute_documentation_coverage(status, sources, metadata, all_cits)

    return {
        "structured_answer": structured,
        "documentation_coverage": cov,
    }
