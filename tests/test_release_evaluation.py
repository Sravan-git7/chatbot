"""Evaluation honesty, case-ID integrity, and frozen input protection (no store access)."""

import copy
import json
from pathlib import Path

import eval.release_v1.verify as RV
from eval.release_v1.verify import (ROOT, _RELEASE_CHUNK_CONFIG, _chunk_manifest_contract_errors,
                                    _pinned_canonical_chunks, _pinned_page_record,
                                    _record_structure_check, observe, validate_case_dataset,
                                    validate_inputs, validate_observation_ids)


def dataset():
    return json.loads((ROOT / "eval/release_v1/cases.json").read_bytes())


def positive_response(case, *, chunk_id=None, url=None):
    """Build a response from the locally regenerated canonical chunk, never a fabricated hash."""
    doc_id = case["reference_doc_id"].lower()
    page = _pinned_page_record(doc_id)
    canonical = _pinned_canonical_chunks()
    assert page["ok"] and canonical["ok"]
    quote = case["reference_quotes"][0]
    normalized_quote = " ".join(quote.casefold().split())
    chunks = canonical["by_doc"][doc_id]
    matching = next(chunk for chunk in chunks
                    if normalized_quote in " ".join(chunk["text"].casefold().split()))
    selected = next((chunk for chunk in chunks if chunk["chunk_id"] == chunk_id), matching) if chunk_id else matching
    guide, page_id = doc_id.split("/")
    source_id = page["source_ids"][0]
    body = {
        "status": "answered",
        "answer": quote + " [S1]",
        "sources": [{
            "type": "page", "marker": "S1", "guide_id": guide, "page_id": page_id,
            "doc_id": doc_id, "chunk_id": selected["chunk_id"],
            "source_id": source_id, "source_ids": list(page["source_ids"]),
            "content_hash": selected["content_hash"], "page_text_sha256": page["text_sha256"],
            "url": url if url is not None else page["source_urls"][source_id], "url_status": "VERIFIED",
        }],
        "metadata": {"grounded": True, "claim_grounding": {
            "checked": True, "status": "LEXICALLY_SCREENED", "claim_count": 1,
            "references_valid": True, "semantic_entailment": "NOT_ASSESSED",
        }},
    }
    return body, selected, matching


def test_new_cases_cover_required_categories_and_pinned_inputs():
    data = dataset()
    assert validate_inputs(data) == []
    assert validate_case_dataset(data)["ok"]
    assert {
        "positive", "negative", "ambiguous", "navigation", "wrong_guide",
        "version_conflict", "insufficient_evidence", "adversarial",
    } <= {c["category"] for c in data["cases"]}
    assert data["semantic_acceptance"]["independent_review_required"]
    assert not data["semantic_acceptance"]["abstention_is_substantive_correctness"]


def test_dataset_id_and_expectation_contract_fails_closed():
    data = dataset()
    duplicate = copy.deepcopy(data)
    duplicate["cases"].append(copy.deepcopy(duplicate["cases"][0]))
    assert not validate_case_dataset(duplicate)["ok"]
    missing_expectation = copy.deepcopy(data)
    missing_expectation["cases"][0].pop("reference_doc_id")
    assert not validate_case_dataset(missing_expectation)["ok"]
    for malformed_category in ("unreviewed", [], {}, None):
        malformed = copy.deepcopy(data)
        malformed["cases"][0]["category"] = malformed_category
        result = validate_case_dataset(malformed)
        assert not result["ok"]
        assert any("unknown category" in error for error in result["errors"])

    for malformed_root in (None, [], "not-an-object", {"cases": [None, [], {}]}):
        result = validate_case_dataset(malformed_root)
        assert not result["ok"] and isinstance(result["errors"], list)


def test_observation_case_ids_must_match_expected_set_exactly():
    cases = dataset()["cases"][:2]
    assert validate_observation_ids(cases, [{"id": c["id"]} for c in cases])["ok"]
    missing = validate_observation_ids(cases, [{"id": cases[0]["id"]}])
    assert not missing["ok"] and missing["missing_ids"] == [cases[1]["id"]]
    duplicate = validate_observation_ids(cases, [{"id": cases[0]["id"]}, {"id": cases[0]["id"]}])
    assert not duplicate["ok"] and duplicate["duplicate_observed_ids"] == [cases[0]["id"]]
    unexpected = validate_observation_ids(cases, [{"id": c["id"]} for c in cases] + [{"id": "unknown-case"}])
    assert not unexpected["ok"] and unexpected["unexpected_ids"] == ["unknown-case"]
    assert not validate_observation_ids(None, None)["ok"]
    assert not validate_observation_ids(cases, {"id": "not-a-list"})["ok"]


def test_page_record_structure_contract_detects_block_and_segmentation_mutations_with_same_flat_text():
    blocks = [
        {"block_index": 0, "kind": "paragraph", "text": "Repeated canonical text.", "heading_path": ["Page", "A"]},
        {"block_index": 1, "kind": "paragraph", "text": "Repeated canonical text.", "heading_path": ["Page", "B"]},
    ]
    flat_text = "\n\n".join(block["text"] for block in blocks)
    extracted = {"title": "Page", "html_title": "Page", "blocks": copy.deepcopy(blocks),
                 "headings": ["A", "B"], "text": flat_text, "stats": {"block_count": 2}}
    record = {"title": "Page", "html_title": "Page", "blocks": copy.deepcopy(blocks),
              "headings": ["A", "B"], "text": flat_text, "structure": {"block_count": 2}}
    assert _record_structure_check(record, extracted)["ok"]

    mutations = []
    kind = copy.deepcopy(record)
    kind["blocks"][0]["kind"] = "list"
    mutations.append(kind)
    order = copy.deepcopy(record)
    order["blocks"].reverse()
    mutations.append(order)
    heading_path = copy.deepcopy(record)
    heading_path["blocks"][0]["heading_path"] = ["Page", "Changed"]
    mutations.append(heading_path)
    block_index = copy.deepcopy(record)
    block_index["blocks"][1]["block_index"] = True
    mutations.append(block_index)

    for mutated in mutations:
        assert mutated["text"] == flat_text
        assert "\n\n".join(block["text"] for block in mutated["blocks"]) == flat_text
        report = _record_structure_check(mutated, extracted)
        assert not report["ok"]
        assert "blocks" in report["mismatches"]

    split_blocks = [
        {"block_index": 0, "kind": "paragraph", "text": "Alpha\n", "heading_path": ["Page", "A"]},
        {"block_index": 1, "kind": "paragraph", "text": "Beta", "heading_path": ["Page", "A"]},
    ]
    split_flat = "\n\n".join(block["text"] for block in split_blocks)
    text_extraction = {"title": "Page", "html_title": "Page", "blocks": copy.deepcopy(split_blocks),
                       "headings": ["A"], "text": split_flat, "stats": {"block_count": 2}}
    text_record = {"title": "Page", "html_title": "Page", "blocks": copy.deepcopy(split_blocks),
                   "headings": ["A"], "text": split_flat, "structure": {"block_count": 2}}
    text_record["blocks"][0]["text"] = "Alpha"
    text_record["blocks"][1]["text"] = "\nBeta"
    assert text_record["text"] == split_flat
    assert "\n\n".join(block["text"] for block in text_record["blocks"]) == split_flat
    assert not _record_structure_check(text_record, text_extraction)["ok"]


def test_chunk_configuration_mutation_is_rejected_against_fixed_release_contract():
    chunk_manifest = json.loads((ROOT / "data/page_collection_manifest.json").read_text(encoding="utf-8"))
    args = (chunk_manifest["corpus_sha256"], chunk_manifest["page_doc_ids"], chunk_manifest["pages"])
    assert _chunk_manifest_contract_errors(chunk_manifest, *args) == []

    original_flat_corpus_hash = chunk_manifest["corpus_sha256"]
    changed = copy.deepcopy(chunk_manifest)
    changed["chunk_config"]["target_tokens"] += 1
    assert changed["corpus_sha256"] == original_flat_corpus_hash
    assert any("configuration differs" in error
               for error in _chunk_manifest_contract_errors(changed, *args))
    boolean_coercion = copy.deepcopy(chunk_manifest)
    boolean_coercion["chunk_config"]["overlap_sentences"] = True
    assert any("configuration differs" in error
               for error in _chunk_manifest_contract_errors(boolean_coercion, *args))


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
            "answer": case["reference_quotes"][0] + " [S1]",
            "sources": [{"marker": "S1", "guide_id": "wrong", "page_id": "wrong",
                        "chunk_id": "wrong/wrong/000", "content_hash": "a" * 64}],
            "metadata": {"grounded": True, "claim_grounding": {
                "status": "LEXICALLY_SCREENED", "references_valid": True,
                "semantic_entailment": "NOT_ASSESSED"}},
        },
    )
    assert result["machine_status"] == "FAIL"


def test_quote_identity_candidate_still_needs_independent_review():
    case = dataset()["cases"][0]
    body, selected_chunk, matching_chunk = positive_response(case)
    assert selected_chunk["chunk_id"] == matching_chunk["chunk_id"]
    result = observe(case, 200, body)
    assert result["machine_status"] == "CANDIDATE"
    assert result["reference_quote_in_pinned_page"]
    assert result["reference_quote_in_cited_chunk"]
    assert result["canonical_chunk_index_valid"]
    assert result["chunk_tokenizer_contract_status"] == "PROPOSED_PENDING_OWNER_APPROVAL"
    assert result["independent_review_required"]
    assert result["substantive_semantic_correctness"] is None


def test_failed_canonical_rebuild_still_reports_pending_chunk_tokenizer_status(monkeypatch):
    case = dataset()["cases"][0]
    monkeypatch.setattr(RV, "_pinned_page_record", lambda _doc_id: {"ok": False})
    monkeypatch.setattr(RV, "_pinned_canonical_chunks", lambda: {"ok": False, "reason": "unavailable"})
    result = RV._reference_candidate(case, 200, {"status": "answered", "answer": "", "sources": []})
    assert result["machine_status"] == "FAIL"
    assert result["chunk_tokenizer_contract_status"] == "PROPOSED_PENDING_OWNER_APPROVAL"


def test_positive_source_url_must_match_independently_pinned_provenance():
    case = dataset()["cases"][0]
    body, _selected, _matching = positive_response(case)
    assert observe(case, 200, body)["machine_status"] == "CANDIDATE"
    body["sources"][0]["url"] = "https://evil.example/docs/unpinned.html"
    assert observe(case, 200, body)["machine_status"] == "FAIL"


def test_release_citation_contract_rejects_malformed_dangling_duplicate_and_mismatched_markers():
    case = dataset()["cases"][0]
    for answer in (case["reference_quotes"][0] + " [S0]",
                   case["reference_quotes"][0] + " [S2]",
                   case["reference_quotes"][0] + " [S1] [S1]"):
        body, _selected, _matching = positive_response(case)
        body["answer"] = answer
        assert observe(case, 200, body)["machine_status"] == "FAIL", answer
    duplicate, _selected, _matching = positive_response(case)
    duplicate["sources"].append(copy.deepcopy(duplicate["sources"][0]))
    assert observe(case, 200, duplicate)["machine_status"] == "FAIL"


def test_release_citation_contract_rejects_standalone_valid_marker_line():
    case = dataset()["cases"][0]
    for standalone in ("[S1]", "[S1] —"):
        body, _selected, _matching = positive_response(case)
        body["answer"] = standalone + "\n" + body["answer"]
        result = observe(case, 200, body)
        assert result["machine_status"] == "FAIL"
        assert result["citation_contract"]["line_citations_valid"] is False


def test_release_candidate_requires_canonical_chunk_identity_and_recomputed_hash():
    case = dataset()["cases"][0]
    fake_id, _selected, _matching = positive_response(case)
    fake_id["sources"][0]["chunk_id"] += "-forged"
    assert observe(case, 200, fake_id)["machine_status"] == "FAIL"

    fake_hash, _selected, _matching = positive_response(case)
    fake_hash["sources"][0]["content_hash"] = "a" * 64
    assert observe(case, 200, fake_hash)["machine_status"] == "FAIL"

    wrong_page_hash, _selected, _matching = positive_response(case)
    wrong_page_hash["sources"][0]["page_text_sha256"] = "b" * 64
    assert observe(case, 200, wrong_page_hash)["machine_status"] == "FAIL"


def test_release_candidate_rejects_wrong_page_identity_and_quote_only_in_another_chunk():
    case = dataset()["cases"][0]
    wrong_identity, _selected, _matching = positive_response(case)
    wrong_identity["sources"][0]["page_id"] = "f" * 32
    wrong_identity["sources"][0]["doc_id"] = f"{case['reference_doc_id'].split('/')[0]}/{'f' * 32}"
    assert observe(case, 200, wrong_identity)["machine_status"] == "FAIL"

    canonical = _pinned_canonical_chunks()
    doc_id = case["reference_doc_id"].lower()
    quote = " ".join(case["reference_quotes"][0].casefold().split())
    other = next(chunk for chunk in canonical["by_doc"][doc_id]
                 if quote not in " ".join(chunk["text"].casefold().split()))
    body, selected, matching = positive_response(case, chunk_id=other["chunk_id"])
    assert selected["chunk_id"] != matching["chunk_id"]
    result = observe(case, 200, body)
    assert result["machine_status"] == "FAIL"
    assert not result["reference_quote_in_cited_chunk"]


def test_release_candidate_requires_checked_positive_claim_review_metadata():
    case = dataset()["cases"][0]
    mutations = (("checked", None), ("checked", False), ("claim_count", None),
                 *(("claim_count", value) for value in (0, -1, "1", True, False)))
    for field, value in mutations:
        body, _selected, _matching = positive_response(case)
        claim_review = body["metadata"]["claim_grounding"]
        if value is None:
            claim_review.pop(field)
        else:
            claim_review[field] = value
        result = observe(case, 200, body)
        assert result["machine_status"] == "FAIL"
        assert not result["citation_contract"]["claim_review_valid"]

    malformed_array, _selected, _matching = positive_response(case)
    malformed_array["metadata"]["claim_grounding"]["claims"] = [None]
    result = observe(case, 200, malformed_array)
    assert result["machine_status"] == "FAIL"
    assert not result["citation_contract"]["claim_review_valid"]


def test_policy_case_requires_fixed_non_substantive_content_not_only_non_answer_status():
    case = next(c for c in dataset()["cases"] if c["category"] == "negative")
    unsafe = observe(case, 200, {"status": "unable_to_verify", "answer": "Transaction ZQ99 is the lunar tax code.",
                                "sources": [], "metadata": {"grounded": False}})
    assert unsafe["machine_status"] == "FAIL"
    safe = observe(case, 200, {"status": "unable_to_verify",
                              "answer": "I couldn't find enough verified information in the available SAP Utilities documentation to answer that specific detail.",
                              "sources": [], "metadata": {"grounded": False}})
    assert safe["machine_status"] == "REVIEW_REQUIRED"
    assert safe["substantive_semantic_correctness"] is None


def test_ambiguous_case_requires_explicit_clarification():
    case = next(c for c in dataset()["cases"] if c["category"] == "ambiguous")
    result = observe(case, 200, {"status": "unable_to_verify",
                                "answer": "Please clarify which payment process you mean, including the payment type or channel.",
                                "sources": [], "metadata": {"grounded": False, "clarification_required": True}})
    assert result["machine_status"] == "REVIEW_REQUIRED"


def test_429_is_not_a_completed_correct_case():
    assert observe(dataset()["cases"][0], 429, {})["machine_status"] == "FAIL"


def test_changed_reference_inputs_abort_instead_of_rebaseline(tmp_path):
    data = {"source_hashes": {"frozen.txt": "0" * 64}}
    (tmp_path / "frozen.txt").write_text("drift")
    assert validate_inputs(data, tmp_path) == ["frozen.txt"]


def test_source_hash_paths_reject_traversal_and_symlinks(tmp_path):
    outside = tmp_path.parent / "outside-source.txt"
    outside.write_text("not within root")
    try:
        (tmp_path / "linked.txt").symlink_to(outside)
    except (OSError, NotImplementedError):
        return
    data = {"source_hashes": {
        "../outside-source.txt": "0" * 64,
        "linked.txt": "0" * 64,
        "data/vector_store/chroma.sqlite3": "0" * 64,
        "data/vector_store/page_collection/chroma.sqlite3": "0" * 64,
    }}
    assert validate_inputs(data, tmp_path) == [
        "../outside-source.txt", "linked.txt", "data/vector_store/chroma.sqlite3",
        "data/vector_store/page_collection/chroma.sqlite3",
    ]
