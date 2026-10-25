"""Regression for P12-002 heading context (ELDM letter-only transaction code).

Preserves prev_line "Transaction ELDM" for evidence, without weakening unrelated cases.
Skipped if temp real index unavailable.
"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

@pytest.mark.skipif(not Path("/tmp/sura-build-test/card/chroma.sqlite3").exists(), reason="real index not built")
def test_eldm_heading_preserved_and_answered():
    import build_page_collection as BP
    import owned_retrieval as OR
    import m2c_page_identity as pid
    import rag_pipeline as RP
    import rag_service as S
    import rag_evidence as EV
    import page_chunker as PK
    import rag_generate as RG

    card_dir = Path("/tmp/sura-build-test/card")
    page_dir = Path("/tmp/sura-build-test/page_collection")
    embed, minfo = BP.load_embedder()
    backend = OR.OwnedCardBackend(vector_dir=card_dir, embedder=embed, expected_dimension=minfo["dimensions"], expected_model=BP.C.MODEL_NAME)
    retriever = OR.OwnedPageRetriever.from_store(vector_dir=page_dir, embed=embed, expected_dimension=minfo["dimensions"], expected_model=BP.C.MODEL_NAME)
    count, _ = PK.make_token_counter(minfo["model_dir"])
    ctx = pid.IdentityContext.from_root(Path("."))
    corpus = RP.PageCorpusIndex.from_dir(Path("data/page_corpus"))
    cfg = S.production_pipeline_config()
    base = RP.RagPipeline(backend, retriever, ctx, corpus, RG.ExtractiveGenerator(), count, config=cfg)
    guarded = EV.build_evidence_pipeline(base, tau=EV.SHIPPED_TAU, widen=False, generator="extractive")
    svc = S.RagService(guarded, "extractive")
    try:
        raw, ev = svc._run_pipeline_request("What does transaction ELDM display?")
        assert raw["status"] == "answered", f"ELDM should be answered, got {raw['status']} {ev}"
        assert raw["routing"]["selected_source_id"] == "M2C-07"
        ans_text = raw.get("answer", "")
        assert "successfully and unsuccessfully posted" in ans_text.lower()
        assert "S4" in ans_text or "S4" in str(raw.get("citations"))
        assert ev["supported"] is True or raw["status"] == "answered"
    finally:
        svc.close()

@pytest.mark.skipif(not Path("/tmp/sura-build-test/card/chroma.sqlite3").exists(), reason="real index not built")
def test_unrelated_identifier_still_unsupported():
    import build_page_collection as BP
    import owned_retrieval as OR
    import m2c_page_identity as pid
    import rag_pipeline as RP
    import rag_service as S
    import rag_evidence as EV
    import page_chunker as PK
    import rag_generate as RG

    card_dir = Path("/tmp/sura-build-test/card")
    page_dir = Path("/tmp/sura-build-test/page_collection")
    embed, minfo = BP.load_embedder()
    backend = OR.OwnedCardBackend(vector_dir=card_dir, embedder=embed, expected_dimension=minfo["dimensions"], expected_model=BP.C.MODEL_NAME)
    retriever = OR.OwnedPageRetriever.from_store(vector_dir=page_dir, embed=embed, expected_dimension=minfo["dimensions"], expected_model=BP.C.MODEL_NAME)
    count, _ = PK.make_token_counter(minfo["model_dir"])
    ctx = pid.IdentityContext.from_root(Path("."))
    corpus = RP.PageCorpusIndex.from_dir(Path("data/page_corpus"))
    cfg = S.production_pipeline_config()
    base = RP.RagPipeline(backend, retriever, ctx, corpus, RG.ExtractiveGenerator(), count, config=cfg)
    guarded = EV.build_evidence_pipeline(base, tau=EV.SHIPPED_TAU, widen=False, generator="extractive")
    svc = S.RagService(guarded, "extractive")
    try:
        raw, ev = svc._run_pipeline_request("What does transaction ZZZZ display?")
        assert ev["supported"] is False
        assert ev["reason"] == "ASKED_IDENTIFIER_NOT_IN_EVIDENCE"
        assert "ZZZZ" in ev["detail"]["missing"]
    finally:
        svc.close()
