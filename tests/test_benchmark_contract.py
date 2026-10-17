"""Pure benchmark workload/response contract checks; never builds a service or opens a vector store."""

import copy
import json

import pytest

from benchmarks import run_benchmark as RB
from benchmarks.run_benchmark import evaluate_response_contract, validate_observation_ids, validate_workload


def workload():
    return json.loads(open("benchmarks/workload_v2.json", encoding="utf-8").read())


def valid_answered_case():
    return {
        "id": "positive-one", "category": "supported", "expected_status": "answered",
        "expected_card_id": "M2C-11", "turns": [{"message": "What is billing?"}],
    }


def valid_answer_body():
    guide = "a" * 32
    page = "b" * 32
    return {
        "status": "answered",
        "answer": "Billing is performed from the billing document. [S1]\nThe document is then reviewed. [S1]",
        "sources": [{
            "type": "page", "marker": "S1", "guide_id": guide, "page_id": page,
            "doc_id": f"{guide}/{page}", "chunk_id": f"{guide}/{page}/000",
            "source_id": "M2C-11", "source_ids": ["M2C-11"],
            "content_hash": "c" * 64, "page_text_sha256": "d" * 64,
        }],
        "metadata": {"card_id": "M2C-11", "grounded": True, "claim_grounding": {
            "checked": True, "status": "LEXICALLY_SCREENED", "claim_count": 2,
            "references_valid": True, "semantic_entailment": "NOT_ASSESSED",
        }},
    }


def test_versioned_workloads_have_unique_explicit_cases():
    assert validate_workload(workload())["ok"]
    legacy = json.loads(open("benchmarks/workload_v1.json", encoding="utf-8").read())
    assert validate_workload(legacy)["ok"]


def test_workload_duplicate_or_incomplete_case_ids_fail_closed():
    data = workload()
    duplicated = copy.deepcopy(data)
    duplicated["items"].append(copy.deepcopy(duplicated["items"][0]))
    assert not validate_workload(duplicated)["ok"]
    missing_id = copy.deepcopy(data)
    missing_id["items"][0].pop("id")
    assert not validate_workload(missing_id)["ok"]
    missing_status = copy.deepcopy(data)
    missing_status["items"][0]["expected_status"] = "unknown"
    assert not validate_workload(missing_status)["ok"]


def test_benchmark_status_vocabulary_is_authoritative_not_self_declared():
    invented = copy.deepcopy(workload())
    invented["items"][0]["expected_status"] = "fabricated_status"
    invented["status_vocabulary"].append("fabricated_status")
    result = validate_workload(invented)
    assert not result["ok"]
    assert any("authoritative" in error for error in result["errors"])
    assert any("API expected_status" in error for error in result["errors"])

    for mutate in (
        lambda data: data["status_vocabulary"].pop(),
        lambda data: data["status_vocabulary"].append(data["status_vocabulary"][0]),
        lambda data: data["status_vocabulary"].append("unexpected_status"),
    ):
        malformed = copy.deepcopy(workload())
        mutate(malformed)
        assert not validate_workload(malformed)["ok"]


def test_benchmark_validator_returns_errors_for_malformed_structures():
    for malformed in (None, [], "workload", {"workload_version": {}, "items": []}):
        result = validate_workload(malformed)
        assert not result["ok"] and isinstance(result["errors"], list)

    for mutation in (
        lambda data: data.update(items=None),
        lambda data: data.update(items=[None]),
        lambda data: data["items"][0].update(category=[]),
        lambda data: data["items"][0].update(turns=None),
        lambda data: data["items"][0].update(expected_card_id={"id": "M2C-11"}),
        lambda data: data.update(status_vocabulary=["answered", {"invented": True}]),
    ):
        malformed = copy.deepcopy(workload())
        mutation(malformed)
        result = validate_workload(malformed)
        assert not result["ok"] and isinstance(result["errors"], list)


def test_benchmark_observation_ids_require_exact_one_to_one_set():
    items = [{"id": "a"}, {"id": "b"}]
    assert validate_observation_ids(items, [{"id": "a"}, {"id": "b"}])["ok"]
    assert validate_observation_ids(items, [{"id": "a"}])["missing_ids"] == ["b"]
    assert validate_observation_ids(items, [{"id": "a"}, {"id": "a"}])["duplicate_observed_ids"] == ["a"]
    assert validate_observation_ids(items, [{"id": "a"}, {"id": "b"}, {"id": "x"}])["unexpected_ids"] == ["x"]
    assert not validate_observation_ids(None, None)["ok"]
    assert not validate_observation_ids(items, {"id": "unknown"})["ok"]


def test_answered_response_requires_explicit_markers_unique_provenance_and_review_metadata():
    result = evaluate_response_contract(valid_answered_case(), valid_answer_body())
    assert result["ok"]
    assert result["semantic_correctness"] is None


def test_repeated_marker_across_claims_is_valid_but_duplicate_within_claim_fails():
    item = valid_answered_case()
    body = valid_answer_body()
    assert evaluate_response_contract(item, body)["ok"]
    body["answer"] = "Billing is performed. [S1] [S1]"
    body["metadata"]["claim_grounding"]["claim_count"] = 1
    result = evaluate_response_contract(item, body)
    assert not result["ok"]
    assert "DUPLICATE_CITATION_MARKER" in result["failures"]


def test_malformed_dangling_and_duplicate_source_markers_fail_closed():
    item = valid_answered_case()
    for answer in ("Billing is performed. [S0]", "Billing is performed. [S2]", "Billing is performed. [S1"):
        body = valid_answer_body()
        body["answer"] = answer
        body["metadata"]["claim_grounding"]["claim_count"] = 1
        assert not evaluate_response_contract(item, body)["ok"]
    duplicate_source = valid_answer_body()
    duplicate_source["sources"].append(copy.deepcopy(duplicate_source["sources"][0]))
    assert not evaluate_response_contract(item, duplicate_source)["ok"]


def test_standalone_valid_marker_line_is_rejected_even_with_a_cited_sentence():
    for standalone in ("[S1]", "[S1] —"):
        body = valid_answer_body()
        body["answer"] = standalone + "\nBilling is performed from the billing document. [S1]"
        result = evaluate_response_contract(valid_answered_case(), body)
        assert not result["ok"]
        assert "MARKER_ONLY_CITATION_LINE" in result["failures"]


def test_claim_review_requires_checked_and_exact_positive_integer_count():
    invalid_values = (0, -1, "1", True, False)
    for key, value in (("checked", False), ("checked", None), ("claim_count", None),
                       *(("claim_count", value) for value in invalid_values)):
        body = valid_answer_body()
        review = body["metadata"]["claim_grounding"]
        if value is None:
            review.pop(key, None)
        else:
            review[key] = value
        assert not evaluate_response_contract(valid_answered_case(), body)["ok"], (key, value)

    for malformed_claims in (None, [], "claims", [None], [{"markers": ["S1"], "sources": []}]
                             ):
        body = valid_answer_body()
        review = body["metadata"]["claim_grounding"]
        review["claims"] = malformed_claims
        assert not evaluate_response_contract(valid_answered_case(), body)["ok"], malformed_claims


def test_source_identity_card_and_hash_mismatches_fail_closed():
    item = valid_answered_case()
    for key, value in (("page_id", "e" * 32), ("source_id", "M2C-27"), ("content_hash", "not-a-hash"),
                       ("page_text_sha256", "not-a-hash")):
        body = valid_answer_body()
        body["sources"][0][key] = value
        assert not evaluate_response_contract(item, body)["ok"], key


def test_positive_http_success_does_not_override_failed_citation_or_identity():
    body = valid_answer_body()
    body["metadata"]["grounded"] = False
    result = evaluate_response_contract(valid_answered_case(), body, 200)
    assert not result["ok"]
    assert "NOT_GROUNDED" in result["failures"]
    assert not evaluate_response_contract(valid_answered_case(), valid_answer_body(), 503)["ok"]


def test_nonanswer_status_requires_safe_fixed_response_empty_sources_and_ungrounded_metadata():
    item = {"id": "negative", "category": "negative", "expected_status": "unable_to_verify",
            "expected_card_id": "M2C-07", "turns": [{"message": "unsupported detail?"}]}
    body = {"status": "unable_to_verify",
            "answer": "I couldn't find enough verified information in the available SAP Utilities documentation to answer that specific detail.",
            "sources": [], "metadata": {"card_id": "M2C-07", "grounded": False}}
    assert evaluate_response_contract(item, body)["ok"]
    body["answer"] = "A made-up unsupported SAP instruction."
    assert not evaluate_response_contract(item, body)["ok"]


def test_benchmark_cli_invalid_input_is_structured_and_never_orchestrates(tmp_path, monkeypatch):
    monkeypatch.setattr(RB, "run_stages", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("service path reached")))
    monkeypatch.setattr(RB, "run_e2e", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("HTTP path reached")))
    monkeypatch.setattr(RB, "capture_environment", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("environment capture reached")))
    monkeypatch.setattr(RB, "_git_state", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Git environment capture reached")))

    malformed_rows = workload()
    malformed_rows["items"] = [None]
    inputs = [
        ("list-root", json.dumps([])),
        ("null-root", json.dumps(None)),
        ("scalar-root", json.dumps(7)),
        ("malformed-json", "{"),
        ("deeply-nested-json", "[" * 2000 + "0" + "]" * 2000),
        ("malformed-row", json.dumps(malformed_rows)),
    ]
    for name, contents in inputs:
        workload_path = tmp_path / f"{name}.json"
        workload_path.write_text(contents, encoding="utf-8")
        out_path = tmp_path / f"{name}-result.json"
        exit_code = RB.main(["--workload", str(workload_path), "--mode", "stages",
                             "--repeat", "1", "--warmup", "0", "--out", str(out_path)])
        result = json.loads(out_path.read_text(encoding="utf-8"))
        assert exit_code == 2
        assert result["results"]["status"] == "INVALID"
        assert result["results"]["workload_validation"]["ok"] is False
        assert result["results"]["workload_validation"]["errors"]
        assert result["source_commit"] is None
        assert result["environment"]["capture_skipped"] is True
        assert "git" not in result["environment"]


def test_benchmark_cli_rejects_malformed_sweep_and_endpoint_options_before_side_effects(tmp_path, monkeypatch):
    for name in ("run_stages", "run_e2e", "capture_environment", "_git_state"):
        monkeypatch.setattr(RB, name, lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError(f"{name} side-effect path reached")))

    invalid_options = (
        ("text-level", ["--concurrency-levels", "one"]),
        ("empty-level", ["--concurrency-levels", "1,,2"]),
        ("negative-level", ["--concurrency-levels", "1,-2"]),
        ("zero-requests", ["--concurrency-requests", "0"]),
        ("invalid-port", ["--spawn", "70000"]),
        ("zero-admission", ["--admission-cap", "0"]),
        ("empty-url", ["--url", ""]),
        ("not-url", ["--url", "not-a-url"]),
        ("missing-source-root", ["--source-root", str(tmp_path / "missing-source-root")]),
    )
    for name, options in invalid_options:
        with pytest.raises(SystemExit) as exc_info:
            RB.main(["--mode", "e2e", "--out", str(tmp_path / f"{name}.json"), *options])
        assert exc_info.value.code == 2
