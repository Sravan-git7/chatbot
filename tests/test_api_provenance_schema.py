"""API model schema tests only; importing rag_api does not create a service or store."""

from tests.phase8_support import SCRIPTS  # noqa: F401 - adds scripts to sys.path without touching a store
import rag_api


def test_public_source_and_metadata_models_expose_provenance_and_claim_review():
    source_fields = set(rag_api.Source.model_fields)
    assert {"url_status", "source_id", "source_ids", "chunk_id", "doc_id", "guide_id", "page_id",
            "content_hash", "page_text_sha256"} <= source_fields
    assert "claim_grounding" in rag_api.Metadata.model_fields

    source = rag_api.Source(
        type="page", marker="S1", source_id="M2C-21", source_ids=["M2C-21"],
        chunk_id="a" * 32 + "/" + "b" * 32 + "/000", doc_id="a" * 32 + "/" + "b" * 32,
        guide_id="a" * 32, page_id="b" * 32, content_hash="c" * 64,
        page_text_sha256="d" * 64, url_status="VERIFIED",
    )
    dumped = source.model_dump()
    assert dumped["source_ids"] == ["M2C-21"]
    assert dumped["url_status"] == "VERIFIED"
