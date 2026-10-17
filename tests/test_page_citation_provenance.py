"""Store-free provenance validation and claim-reference integrity tests."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import page_citations as PCIT
import rag_claim_review as CRV
import rag_generate as RG

GUIDE = "a" * 32
PAGE = "b" * 32
DOC_ID = f"{GUIDE}/{PAGE}"
TEXT = "The clearing proposal uses the selected clearing variant."
PAGE_TEXT = "The clearing proposal uses the selected clearing variant. A separate page passage follows."
SOURCE_ID = "M2C-21"
PAGE_URL = f"https://help.sap.com/docs/Example/{GUIDE}/{PAGE}.html"


def _chunk(marker="S1", **changes):
    fields = {
        "marker": marker,
        "chunk_id": f"{DOC_ID}/000",
        "doc_id": DOC_ID,
        "guide_id": GUIDE,
        "page_id": PAGE,
        "chunk_index": 0,
        "text": TEXT,
        "content_hash": hashlib.sha256(TEXT.encode("utf-8")).hexdigest(),
        "page_text_sha256": hashlib.sha256(PAGE_TEXT.encode("utf-8")).hexdigest(),
        "source_ids": [SOURCE_ID],
        "source_url": PAGE_URL,
        "title": "Clearing Type",
        "heading_path": ["Clearing Type"],
        "section_title": "Clearing Type",
        "rank": 1,
        "similarity": 1.0,
        "rendered_text": TEXT,
    }
    fields.update(changes)
    return SimpleNamespace(**fields)


def _identity(**changes):
    fields = {"source_id": SOURCE_ID, "effective_guide_id": GUIDE, "effective_page_id": PAGE}
    fields.update(changes)
    return SimpleNamespace(**fields)


def _identity_context():
    return SimpleNamespace(registrations={}, registry={}, stale_final_manifest={})


def _corpus_entry(**changes):
    fields = {"corpus_status": "ingested", "doc_id": DOC_ID,
              "text_sha256": hashlib.sha256(PAGE_TEXT.encode("utf-8")).hexdigest()}
    fields.update(changes)
    return fields


def _validate(*items, identity=None, corpus_entry=None):
    context = SimpleNamespace(items=list(items))
    result = PCIT.validate_context_provenance(
        context, identity or _identity(), _identity_context(), corpus_entry or _corpus_entry())
    return result, context


def test_real_chunk_object_and_manifest_provenance_pass_with_recorded_url():
    provenance, _ = _validate(_chunk())
    assert provenance["ok"]
    row = provenance["items"][0]
    assert row["source_object_valid"]
    assert row["url_verified"]
    assert row["url_status"] == "VERIFIED"
    assert row["semantic_entailment"] == "NOT_ASSESSED"


def test_url_mismatch_is_retained_but_not_verified_or_exposed_as_source():
    wrong_url = f"https://help.sap.com/docs/Example/{'c' * 32}/{PAGE}.html"
    provenance, _ = _validate(_chunk(source_url=wrong_url))
    assert provenance["ok"]
    assert provenance["items"][0]["source_object_valid"]
    assert not provenance["items"][0]["url_verified"]
    assert provenance["items"][0]["url_status"] == "URL_GUIDE_RELATION_NOT_ESTABLISHED"


def test_source_marker_must_be_unique_well_formed_and_bound_to_chunk():
    cases = (
        (_chunk(marker="S0"), "INVALID_MARKER"),
        (_chunk(marker="S1", chunk_id=f"{DOC_ID}/009"), "CHUNK_ID_MISMATCH"),
        (_chunk(marker="S1", source_ids=["M2C-22"]), "SOURCE_ID_MISSING_OR_MISMATCHED"),
        (_chunk(marker="S1", guide_id="c" * 32), "CONTEXT_IDENTITY_MISMATCH"),
        (_chunk(marker="S1", doc_id=f"{'c' * 32}/{PAGE}"), "DOC_ID_MISMATCH"),
        (_chunk(marker="S1", content_hash="0" * 64), "CONTENT_HASH_MISMATCH"),
        (_chunk(marker="S1", page_text_sha256="0" * 64), "PAGE_TEXT_HASH_MISMATCH"),
    )
    for item, expected_error in cases:
        provenance, _ = _validate(item)
        assert not provenance["ok"]
        assert expected_error in {row["kind"] for row in provenance["errors"]}

    duplicate, _ = _validate(_chunk(), _chunk())
    assert not duplicate["ok"]
    assert "DUPLICATE_MARKER" in {row["kind"] for row in duplicate["errors"]}


def test_source_requires_an_ingested_manifest_entry_with_matching_page_hash_and_doc_id():
    for entry, expected_error in (
        (_corpus_entry(corpus_status="not_ingested_no_local_content"), "CORPUS_ENTRY_NOT_INGESTED"),
        (_corpus_entry(text_sha256="missing"), "PAGE_MANIFEST_HASH_MISSING_OR_INVALID"),
        (_corpus_entry(doc_id=f"{'c' * 32}/{PAGE}"), "CORPUS_DOC_ID_MISMATCH"),
    ):
        provenance, _ = _validate(_chunk(), corpus_entry=entry)
        assert not provenance["ok"]
        assert expected_error in {row["kind"] for row in provenance["errors"]}

    empty, _ = _validate()
    assert not empty["ok"]


def test_claim_review_fails_closed_for_malformed_dangling_duplicate_and_uncited_claims():
    valid_provenance, context = _validate(_chunk())
    answer = f"{TEXT} [S1]"
    grounding = RG.verify_grounding(answer, context).to_dict()
    review = CRV.review_answer_claims(answer, context, grounding, valid_provenance)
    assert review["status"] == "LEXICALLY_SCREENED"
    assert review["references_valid"]
    assert review["semantic_entailment"] == "NOT_ASSESSED"
    assert review["checked"] is True and review["claim_count"] == 1

    for invalid_answer, error_kind in (
        (f"{TEXT} [S0]", "MALFORMED_MARKER"),
        (f"{TEXT} [S2]", "DANGLING_MARKER"),
        (f"{TEXT} [S1] [S1]", "DUPLICATE_MARKER"),
        (TEXT, "NO_EXPLICIT_CITATION"),
    ):
        grounding = RG.verify_grounding(invalid_answer, context).to_dict()
        review = CRV.review_answer_claims(invalid_answer, context, grounding, valid_provenance)
        assert review["status"] == "CITATION_OR_PROVENANCE_FAILURE"
        assert not review["references_valid"]
        assert error_kind in {row["kind"] for row in review["errors"]}


def test_claim_review_rejects_standalone_valid_marker_alongside_a_cited_claim():
    provenance, context = _validate(_chunk())
    answer = f"[S1]\n{TEXT} [S1]"
    grounding = RG.verify_grounding(answer, context).to_dict()
    review = CRV.review_answer_claims(answer, context, grounding, provenance)
    assert not grounding["ok"]
    assert review["checked"] is True and review["claim_count"] == 1
    assert review["status"] == "CITATION_OR_PROVENANCE_FAILURE"
    assert any(row["kind"] == "NO_CLAIM_BODY" for row in review["errors"])


def test_claim_review_does_not_treat_lexical_overlap_as_semantic_entailment():
    provenance, context = _validate(_chunk())
    answer = "The clearing proposal uses the selected clearing variant. [S1]"
    grounding = RG.verify_grounding(answer, context).to_dict()
    review = CRV.review_answer_claims(answer, context, grounding, provenance)
    claim = review["claims"][0]
    assert claim["sources"][0]["lexical_screen"]["category"] == "VERBATIM_NORMALIZED_SPAN"
    assert claim["semantic_entailment"] == "NOT_ASSESSED"
    assert review["semantic_entailment"] == "NOT_ASSESSED"


def test_claim_review_rejects_invalid_source_provenance_even_when_words_match():
    invalid_provenance, context = _validate(_chunk(content_hash="0" * 64))
    answer = f"{TEXT} [S1]"
    grounding = RG.verify_grounding(answer, context).to_dict()
    review = CRV.review_answer_claims(answer, context, grounding, invalid_provenance)
    assert not review["references_valid"]
    assert "INVALID_SOURCE_PROVENANCE" in {row["kind"] for row in review["errors"]}
