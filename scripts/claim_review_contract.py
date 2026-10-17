"""Shared fail-closed contract for screened answer-claim metadata.

These checks validate the shape and reference integrity of a lexical review only. They do
not assess semantic entailment or SAP correctness.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict, List, Tuple

from citation_markers import valid_marker


def validate_claim_review_metadata(
    review: Any,
    answer_text: Any,
    *,
    require_claims: bool = False,
) -> Tuple[bool, List[str]]:
    """Validate API-summary or internal claim-review metadata for a non-empty answer.

    Empty/non-answer cases are intentionally not required to fabricate a screened claim
    count. Answered responses must have a literal boolean ``checked=True`` and an exact
    positive ``int`` count (``bool`` is explicitly not accepted as an integer).
    """
    if not isinstance(answer_text, str) or not answer_text.strip():
        return True, []

    errors: List[str] = []
    if not isinstance(review, Mapping):
        return False, ["CLAIM_REVIEW_NOT_OBJECT"]
    if review.get("checked") is not True:
        errors.append("CLAIM_REVIEW_NOT_CHECKED")
    if review.get("status") != "LEXICALLY_SCREENED":
        errors.append("CLAIM_REVIEW_STATUS_INVALID")
    if review.get("references_valid") is not True:
        errors.append("CLAIM_REVIEW_REFERENCES_INVALID")
    if review.get("semantic_entailment") != "NOT_ASSESSED":
        errors.append("CLAIM_REVIEW_SEMANTIC_STATUS_INVALID")

    claim_count = review.get("claim_count")
    if type(claim_count) is not int or claim_count <= 0:
        errors.append("CLAIM_REVIEW_COUNT_INVALID")

    claims_present = "claims" in review or require_claims
    if claims_present:
        claims = review.get("claims")
        if not isinstance(claims, list) or not claims:
            errors.append("CLAIM_REVIEW_CLAIMS_INVALID")
        else:
            if type(claim_count) is int and claim_count != len(claims):
                errors.append("CLAIM_REVIEW_COUNT_MISMATCH")
            for index, claim in enumerate(claims):
                if not isinstance(claim, Mapping):
                    errors.append(f"CLAIM_REVIEW_CLAIM_{index}_NOT_OBJECT")
                    continue
                text = claim.get("claim")
                markers = claim.get("markers")
                sources = claim.get("sources")
                if not isinstance(text, str) or not text.strip():
                    errors.append(f"CLAIM_REVIEW_CLAIM_{index}_TEXT_INVALID")
                if (not isinstance(markers, list) or not markers
                        or not all(valid_marker(marker) for marker in markers)
                        or len(markers) != len(set(markers))):
                    errors.append(f"CLAIM_REVIEW_CLAIM_{index}_MARKERS_INVALID")
                    marker_set = set()
                else:
                    marker_set = set(markers)
                if claim.get("citation_valid") is not True:
                    errors.append(f"CLAIM_REVIEW_CLAIM_{index}_CITATION_INVALID")
                if claim.get("semantic_entailment") != "NOT_ASSESSED":
                    errors.append(f"CLAIM_REVIEW_CLAIM_{index}_SEMANTIC_STATUS_INVALID")
                if not isinstance(sources, list) or not sources:
                    errors.append(f"CLAIM_REVIEW_CLAIM_{index}_SOURCES_INVALID")
                    continue
                source_markers = set()
                source_marker_rows = []
                for source in sources:
                    if not isinstance(source, Mapping):
                        errors.append(f"CLAIM_REVIEW_CLAIM_{index}_SOURCE_NOT_OBJECT")
                        continue
                    marker = source.get("marker")
                    source_ids = source.get("source_ids")
                    if not valid_marker(marker):
                        errors.append(f"CLAIM_REVIEW_CLAIM_{index}_SOURCE_MARKER_INVALID")
                    else:
                        source_markers.add(marker)
                        source_marker_rows.append(marker)
                    if source.get("source_object_valid") is not True:
                        errors.append(f"CLAIM_REVIEW_CLAIM_{index}_SOURCE_INVALID")
                    if not isinstance(source.get("chunk_id"), str) or not source["chunk_id"].strip():
                        errors.append(f"CLAIM_REVIEW_CLAIM_{index}_SOURCE_CHUNK_INVALID")
                    if (not isinstance(source_ids, list) or not source_ids
                            or not all(isinstance(source_id, str) and source_id.strip() for source_id in source_ids)
                            or len(source_ids) != len(set(source_ids))):
                        errors.append(f"CLAIM_REVIEW_CLAIM_{index}_SOURCE_IDS_INVALID")
                if len(source_marker_rows) != len(source_markers):
                    errors.append(f"CLAIM_REVIEW_CLAIM_{index}_SOURCE_MARKER_DUPLICATE")
                if marker_set and source_markers != marker_set:
                    errors.append(f"CLAIM_REVIEW_CLAIM_{index}_REFERENCE_MISMATCH")

        if require_claims:
            if review.get("grounding_verifier_ok") is not True:
                errors.append("CLAIM_REVIEW_GROUNDING_INVALID")
            if review.get("source_provenance_ok") is not True:
                errors.append("CLAIM_REVIEW_PROVENANCE_INVALID")

    return not errors, errors
