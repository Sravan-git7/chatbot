"""Pure frozen-quality contract tests; never builds a service or opens a vector store."""

import copy
import hashlib
import json
from pathlib import Path

from benchmarks.run_quality import (ROOT, _PHASE12_CASE_IDS, citation_integrity,
                                    load_pinned_quality_dataset, strict_evidence_correct,
                                    validate_case_ids, validate_quality_dataset)


def valid_query():
    return {
        "id": "P12-test",
        "type": "answerable",
        "query": "What is the clearing step?",
        "gold_source_id": "M2C-21",
        "gold_doc_id": "a" * 32 + "/" + "b" * 32,
        "acceptable_source_ids": [],
        "evidence": ["The clearing proposal uses the selected clearing variant."],
    }


def valid_response(query=None):
    query = query or valid_query()
    guide, page = query["gold_doc_id"].split("/")
    text = "The clearing proposal uses the selected clearing variant."
    page_hash = "b" * 64
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    url = f"https://help.sap.com/docs/Example/{guide}/{page}.html"
    context_item = {
        "marker": "S1", "chunk_id": f"{guide}/{page}/000", "guide_id": guide, "page_id": page,
        "doc_id": f"{guide}/{page}", "source_ids": ["M2C-21"], "content_hash": content_hash,
        "page_text_sha256": page_hash, "source_url": url, "text": text,
    }
    provenance = {
        "marker": "S1", "chunk_id": context_item["chunk_id"], "doc_id": context_item["doc_id"],
        "guide_id": guide, "page_id": page, "source_ids": ["M2C-21"], "content_hash": content_hash,
        "page_text_sha256": page_hash, "source_object_valid": True, "recorded_url": url,
        "url_verified": True, "url_status": "VERIFIED",
    }
    source = {
        "marker": "S1", "chunk_id": context_item["chunk_id"], "guide_id": guide, "page_id": page,
        "doc_id": context_item["doc_id"], "source_ids": ["M2C-21"], "content_hash": content_hash,
        "page_text_sha256": page_hash, "url": url, "url_flag": None, "join": {"card_source_id": "M2C-21"},
        "provenance": provenance,
    }
    return {
        "status": "answered", "answer": text + " [S1]", "citations": {"answer_sources": [source]},
        "debug": {"context": {"items": [context_item]}, "grounding": {"ok": True},
                  "claim_review": {
                      "checked": True, "claim_count": 1, "status": "LEXICALLY_SCREENED",
                      "references_valid": True, "grounding_verifier_ok": True,
                      "source_provenance_ok": True, "semantic_entailment": "NOT_ASSESSED",
                      "claims": [{"claim": text, "markers": ["S1"], "citation_valid": True,
                                  "semantic_entailment": "NOT_ASSESSED", "sources": [{
                                      "marker": "S1", "source_object_valid": True,
                                      "chunk_id": context_item["chunk_id"],
                                      "source_ids": ["M2C-21"],
                                  }] }],
                  }},
    }


def _copy_quality_inputs(root: Path):
    for relative in ("data/evaluation/phase12_queries.json", "eval/release_v1/cases.json"):
        source = ROOT / relative
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    return root / "data/evaluation/phase12_queries.json"


def test_frozen_phase12_dataset_has_unique_ids_and_substantive_expectations():
    dataset = json.loads((ROOT / "data/evaluation/phase12_queries.json").read_bytes())
    report = validate_quality_dataset(dataset)
    assert report["ok"], report["errors"]
    assert report["expected_ids"] == list(_PHASE12_CASE_IDS)
    assert validate_quality_dataset(dataset, expected_ids=_PHASE12_CASE_IDS)["ok"]


def test_quality_dataset_missing_duplicate_unknown_and_incomplete_expectations_fail():
    dataset = json.loads((ROOT / "data/evaluation/phase12_queries.json").read_bytes())
    duplicate = copy.deepcopy(dataset)
    duplicate["queries"].append(copy.deepcopy(duplicate["queries"][0]))
    assert not validate_quality_dataset(duplicate)["ok"]
    missing = copy.deepcopy(dataset)
    missing["queries"][0].pop("id")
    assert not validate_quality_dataset(missing)["ok"]
    unknown = copy.deepcopy(dataset)
    unknown["queries"][0]["type"] = "unreviewed"
    assert not validate_quality_dataset(unknown)["ok"]
    incomplete = copy.deepcopy(dataset)
    incomplete["queries"][0]["evidence"] = []
    assert not validate_quality_dataset(incomplete)["ok"]

    changed_category = copy.deepcopy(dataset)
    changed_category["queries"][0]["category"] = "unreviewed_category"
    category_result = validate_quality_dataset(changed_category)
    assert not category_result["ok"]
    assert "declared category counts do not match the query rows" in category_result["errors"]

    changed_summary = copy.deepcopy(dataset)
    changed_summary["categories"]["direct_factual"] += 1
    changed_summary["categories"]["paraphrased"] -= 1
    summary_result = validate_quality_dataset(changed_summary)
    assert not summary_result["ok"]
    assert "declared category counts do not match the query rows" in summary_result["errors"]


def test_quality_dataset_ids_are_checked_against_independent_frozen_inventory():
    dataset = json.loads((ROOT / "data/evaluation/phase12_queries.json").read_bytes())
    missing = copy.deepcopy(dataset)
    missing["queries"].pop(0)
    missing_result = validate_quality_dataset(missing, expected_ids=_PHASE12_CASE_IDS)
    assert not missing_result["ok"]
    assert any("independently pinned inventory" in error for error in missing_result["errors"])

    extra = copy.deepcopy(dataset)
    extra["queries"].append(copy.deepcopy(extra["queries"][0]))
    extra["queries"][-1]["id"] = "P12-EXTRA"
    extra_result = validate_quality_dataset(extra, expected_ids=_PHASE12_CASE_IDS)
    assert not extra_result["ok"]
    assert any("independently pinned inventory" in error for error in extra_result["errors"])

    duplicate = copy.deepcopy(dataset)
    duplicate["queries"][1]["id"] = duplicate["queries"][0]["id"]
    duplicate_result = validate_quality_dataset(duplicate, expected_ids=_PHASE12_CASE_IDS)
    assert not duplicate_result["ok"]
    assert any("duplicate query ids" in error for error in duplicate_result["errors"])


def test_quality_runner_input_requires_release_pinned_sha_and_fixed_dataset_path(tmp_path):
    dataset_path = _copy_quality_inputs(tmp_path)
    valid = load_pinned_quality_dataset(dataset_path, root=tmp_path)
    assert valid["ok"], valid["errors"]
    assert valid["dataset_sha256"] == "3c5a9ddd2d62e9cb1919a4fbb7c81cd5239994ff230abbbe6440fb6fa5c132ac"
    assert valid["expected_sha256"] == valid["dataset_sha256"]
    assert valid["case_id_inventory_status"] == "PROPOSED_PENDING_OWNER_APPROVAL"
    assert valid["dataset_validation"]["expected_ids"] == list(_PHASE12_CASE_IDS)

    unpinned_path = tmp_path / "unapproved-phase12.json"
    unpinned_path.write_bytes(dataset_path.read_bytes())
    unpinned = load_pinned_quality_dataset(unpinned_path, root=tmp_path)
    assert not unpinned["ok"]
    assert unpinned["case_id_inventory_status"] == "PROPOSED_PENDING_OWNER_APPROVAL"
    assert "not the release-pinned Phase-12 file" in unpinned["errors"][0]


def test_quality_runner_rejects_modified_baseline_bytes_labels_and_evidence(tmp_path):
    original = json.loads((ROOT / "data/evaluation/phase12_queries.json").read_bytes())
    mutations = {
        "bytes": lambda _data, raw: raw + b" ",
        "labels": lambda data, _raw: (data["queries"][0].update(type="not_ingested") or
                                       json.dumps(data).encode("utf-8")),
        "evidence": lambda data, _raw: (data["queries"][0].update(evidence=["changed evidence"]) or
                                         json.dumps(data).encode("utf-8")),
    }
    for name, mutate in mutations.items():
        root = tmp_path / name
        dataset_path = _copy_quality_inputs(root)
        raw = dataset_path.read_bytes()
        changed = copy.deepcopy(original)
        dataset_path.write_bytes(mutate(changed, raw))
        result = load_pinned_quality_dataset(dataset_path, root=root)
        assert not result["ok"], name
        assert any("SHA-256 differs" in error for error in result["errors"]), result["errors"]


def test_quality_runner_blocks_unavailable_or_unauthorized_baseline_pin(tmp_path):
    dataset_path = _copy_quality_inputs(tmp_path)
    cases_path = tmp_path / "eval/release_v1/cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    cases["source_hashes"]["data/evaluation/phase12_queries.json"] = "0" * 64
    cases_path.write_text(json.dumps(cases), encoding="utf-8")
    unauthorized = load_pinned_quality_dataset(dataset_path, root=tmp_path)
    assert not unauthorized["ok"]
    assert any("approved baseline pin" in error for error in unauthorized["errors"])

    missing_root = tmp_path / "missing"
    missing_root.mkdir()
    missing = load_pinned_quality_dataset(root=missing_root)
    assert not missing["ok"]
    assert missing["case_id_inventory_status"] == "PROPOSED_PENDING_OWNER_APPROVAL"
    assert not missing["dataset_validation"]["ok"]


def test_quality_observation_ids_require_exact_one_to_one_reconciliation():
    expected = ["a", "b"]
    assert validate_case_ids(expected, [{"id": "a"}, {"id": "b"}])["ok"]
    assert validate_case_ids(expected, [{"id": "a"}])["missing_ids"] == ["b"]
    assert validate_case_ids(expected, [{"id": "a"}, {"id": "a"}])["duplicate_observed_ids"] == ["a"]
    assert validate_case_ids(expected, [{"id": "a"}, {"id": "b"}, {"id": "x"}])["unexpected_ids"] == ["x"]
    assert not validate_case_ids(["a", "a"], [{"id": "a"}])["ok"]
    assert not validate_case_ids([""], [{"id": ""}])["ok"]


def test_quality_contract_binds_each_answer_marker_to_its_source_object_and_quote():
    query = valid_query()
    raw = valid_response(query)
    assert citation_integrity(query, raw)["ok"]
    assert strict_evidence_correct(query, raw)

    wrong_chunk = copy.deepcopy(raw)
    wrong_chunk["citations"]["answer_sources"][0]["chunk_id"] = f"{query['gold_doc_id']}/009"
    assert not citation_integrity(query, wrong_chunk)["ok"]
    assert not strict_evidence_correct(query, wrong_chunk)


def test_quality_claim_review_requires_checked_positive_count_and_valid_claim_references():
    query = valid_query()
    mutations = (("checked", None), ("checked", False), ("claim_count", None),
                 *(("claim_count", value) for value in (0, -1, "1", True, False)))
    for field, value in mutations:
        raw = valid_response(query)
        review = raw["debug"]["claim_review"]
        if value is None:
            review.pop(field, None)
        else:
            review[field] = value
        assert not citation_integrity(query, raw)["ok"], (field, value)

    for malformed_claims in (None, [], "claims", [None], [{"claim": "x", "markers": ["S1"]}]
                             ):
        raw = valid_response(query)
        raw["debug"]["claim_review"]["claims"] = malformed_claims
        assert not citation_integrity(query, raw)["ok"], malformed_claims


def test_quality_gate_rejects_standalone_valid_marker_line_with_cited_sentence():
    query = valid_query()
    for standalone in ("[S1]", "[S1] —"):
        raw = valid_response(query)
        raw["answer"] = standalone + "\n" + raw["answer"]
        result = citation_integrity(query, raw)
        assert not result["ok"]
        assert "MARKER_ONLY_CITATION_LINE" in result["failures"]


def test_quality_contract_fails_closed_for_bad_markers_uncited_claims_and_unverified_urls():
    query = valid_query()
    for answer in (
        "The clearing step is documented. [S0]",
        "The clearing step is documented. [S1,]",
        "The clearing step is documented. [S1] [S1]",
        "The clearing step is documented.",
    ):
        raw = valid_response(query)
        raw["answer"] = answer
        assert not citation_integrity(query, raw)["ok"], answer

    bad_url = valid_response(query)
    bad_url["citations"]["answer_sources"][0]["url"] = "https://help.sap.com/docs/foreign/page.html"
    assert not citation_integrity(query, bad_url)["ok"]

    bad_claim = valid_response(query)
    bad_claim["debug"]["claim_review"]["status"] = "NOT_CHECKED"
    assert not citation_integrity(query, bad_claim)["ok"]
