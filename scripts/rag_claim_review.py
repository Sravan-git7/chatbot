"""Claim-level citation review using deterministic lexical screens only.

This module checks that each answer line names an explicit context marker, the marker maps
uniquely to a source object with valid provenance, and records verbatim/token-overlap signals.
It does NOT assess semantic entailment, SAP correctness, procedure completeness, or truth.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional

import rag_text as T
from citation_markers import has_claim_body, parse_citation_line, valid_marker
from rag_generate import is_procedural_limitation_sentence


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def _screen_claim(body: str, source_text: str) -> Dict[str, Any]:
    claim_norm, source_norm = _norm(body), _norm(source_text)
    claim_terms = set(T.terms(body))
    source_terms = set(T.terms(source_text))
    overlap = len(claim_terms & source_terms) / len(claim_terms) if claim_terms else 0.0
    verbatim = bool(claim_norm and (claim_norm in source_norm or
                                    re.sub(r"^[-*•]\s*", "", claim_norm).strip() in source_norm))
    if verbatim:
        category = "VERBATIM_NORMALIZED_SPAN"
    elif overlap >= 0.6:
        category = "HIGH_LEXICAL_OVERLAP"
    elif overlap > 0:
        category = "PARTIAL_LEXICAL_OVERLAP"
    else:
        category = "LOW_OR_NO_LEXICAL_OVERLAP"
    return {"category": category, "verbatim_normalized_span": verbatim,
            "content_term_overlap": round(overlap, 3), "claim_term_count": len(claim_terms),
            "semantic_entailment": "NOT_ASSESSED"}


def review_answer_claims(answer: str, context: Any, grounding: Optional[Mapping[str, Any]] = None,
                         provenance: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Produce a line-by-line citation/source review without presenting lexical overlap as entailment."""
    items = list(getattr(context, "items", ()) or ())
    by_marker: Dict[str, List[Any]] = {}
    for item in items:
        marker = str(getattr(item, "marker", "") or "")
        by_marker.setdefault(marker, []).append(item)
    provenance_by_marker = {
        str(row.get("marker")): row for row in (provenance or {}).get("items", [])
        if isinstance(row, Mapping)
    }
    claims: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for line in T.split_cited_sentences(answer or ""):
        markers, malformed, body = parse_citation_line(line, allow_compound=True)
        if not has_claim_body(body):
            if malformed:
                errors.extend({"kind": "MALFORMED_MARKER", "reference": marker} for marker in malformed)
            if markers or malformed:
                errors.append({"kind": "NO_CLAIM_BODY", "reference": line[:160]})
            continue
        if not markers and not malformed and is_procedural_limitation_sentence(body):
            continue
        for marker_ref in malformed:
            errors.append({"kind": "MALFORMED_MARKER", "reference": marker_ref})
        duplicates = sorted({marker for marker in markers if markers.count(marker) > 1})
        for marker in duplicates:
            errors.append({"kind": "DUPLICATE_MARKER", "marker": marker})
        if not markers:
            errors.append({"kind": "NO_EXPLICIT_CITATION", "claim": body[:160]})
        source_rows: List[Dict[str, Any]] = []
        for marker in dict.fromkeys(markers):
            mapped = by_marker.get(marker, [])
            if not valid_marker(marker):
                errors.append({"kind": "MALFORMED_MARKER", "marker": marker})
            if not mapped:
                errors.append({"kind": "DANGLING_MARKER", "marker": marker})
                continue
            if len(mapped) != 1:
                errors.append({"kind": "DUPLICATE_CONTEXT_MARKER", "marker": marker})
                continue
            item = mapped[0]
            source_provenance = provenance_by_marker.get(marker, {})
            source_valid = bool(source_provenance.get("source_object_valid"))
            if not source_valid:
                errors.append({"kind": "INVALID_SOURCE_PROVENANCE", "marker": marker,
                               "errors": list(source_provenance.get("errors") or [])})
            source_rows.append({
                "marker": marker,
                "chunk_id": getattr(item, "chunk_id", None),
                "source_ids": list(getattr(item, "source_ids", []) or []),
                "guide_id": getattr(item, "guide_id", None),
                "page_id": getattr(item, "page_id", None),
                "doc_id": getattr(item, "doc_id", None),
                "content_hash": getattr(item, "content_hash", None),
                "page_text_sha256": getattr(item, "page_text_sha256", None),
                "source_object_valid": source_valid,
                "source_url_status": source_provenance.get("url_status"),
                "lexical_screen": _screen_claim(body, str(getattr(item, "text", "") or "")),
            })
        claims.append({"claim": body, "markers": markers, "sources": source_rows,
                       "citation_valid": bool(markers) and not malformed and not duplicates and
                                          all(row["source_object_valid"] for row in source_rows) and
                                          all(len(by_marker.get(marker, [])) == 1 for marker in markers),
                       "semantic_entailment": "NOT_ASSESSED"})

    grounding_ok = bool((grounding or {}).get("ok"))
    provenance_ok = bool((provenance or {}).get("ok"))
    references_valid = bool(claims) and not errors and all(claim["citation_valid"] for claim in claims)
    checked = bool(claims)
    return {
        "checked": checked,
        "claim_count": len(claims),
        "status": "LEXICALLY_SCREENED" if checked and references_valid and grounding_ok and provenance_ok else
                  ("CITATION_OR_PROVENANCE_FAILURE" if errors or checked else "NOT_CHECKED"),
        "references_valid": references_valid,
        "grounding_verifier_ok": grounding_ok,
        "source_provenance_ok": provenance_ok,
        "claims": claims,
        "errors": errors,
        "semantic_entailment": "NOT_ASSESSED",
        "method": "explicit marker-to-source mapping, provenance consistency, verbatim span and content-term overlap only",
    }
