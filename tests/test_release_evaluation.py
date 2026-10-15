"""Evaluation honesty and frozen input protection, not SAP semantic gold."""

import json
from pathlib import Path
from eval.release_v1.verify import ROOT, observe, validate_inputs


def dataset():
    return json.loads((ROOT / "eval/release_v1/cases.json").read_bytes())


def test_new_cases_cover_required_categories_and_pinned_inputs():
    data = dataset()
    assert validate_inputs(data) == []
    assert {
        "positive",
        "negative",
        "ambiguous",
        "navigation",
        "wrong_guide",
        "version_conflict",
        "insufficient_evidence",
        "adversarial",
    } <= {c["category"] for c in data["cases"]}
    assert data["semantic_acceptance"]["independent_review_required"]
    assert not data["semantic_acceptance"]["abstention_is_substantive_correctness"]


def test_positive_abstention_is_not_substantive_success():
    case = dataset()["cases"][0]
    result = observe(case, 200, {"status": "unable_to_verify", "answer": ""})
    assert result["machine_status"] == "FAIL"
    assert result["substantive_semantic_correctness"] is None


def test_correct_quote_wrong_identity_is_not_candidate():
    case = dataset()["cases"][0]
    result = observe(
        case,
        200,
        {
            "status": "answered",
            "answer": case["reference_quotes"][0],
            "sources": [{"guide_id": "wrong", "page_id": "wrong"}],
        },
    )
    assert result["machine_status"] == "FAIL"


def test_quote_identity_candidate_still_needs_independent_review():
    case = dataset()["cases"][0]
    guide, page = case["reference_doc_id"].split("/")
    result = observe(
        case,
        200,
        {
            "status": "answered",
            "answer": case["reference_quotes"][0],
            "sources": [{"guide_id": guide, "page_id": page}],
        },
    )
    assert result["machine_status"] == "CANDIDATE"
    assert result["independent_review_required"]
    assert result["substantive_semantic_correctness"] is None


def test_429_is_not_a_completed_correct_case():
    assert observe(dataset()["cases"][0], 429, {})["machine_status"] == "FAIL"


def test_changed_reference_inputs_abort_instead_of_rebaseline(tmp_path):
    data = {"source_hashes": {"frozen.txt": "0" * 64}}
    (tmp_path / "frozen.txt").write_text("drift")
    assert validate_inputs(data, tmp_path) == ["frozen.txt"]
