"""Regression for P12-006/007/045 wrong-page fixes.

Verifies the three expected documents are retrieved with evidence-supported phrases
and that billing safeguard (P12-020) remains intact.
Skipped if temp index unavailable.
"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

@pytest.mark.skipif(not Path("/tmp/sura-build-test/card/chroma.sqlite3").exists(), reason="real index not built")
def test_p12_006_equipment_records_routes_to_m2c05():
    import build_page_collection as BP, owned_retrieval as OR, m2c_page_identity as pid, rag_pipeline as RP, rag_service as S, rag_evidence as EV, page_chunker as PK, rag_generate as RG
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
        raw, _ = svc._run_pipeline_request("When are equipment records created?")
        assert raw["routing"]["selected_source_id"] == "M2C-05", f"expected M2C-05 got {raw['routing']['selected_source_id']}"
        assert raw["status"] == "answered"
        assert "equipment records are created automatically during goods receipt" in raw["answer"].lower()
    finally:
        svc.close()

@pytest.mark.skipif(not Path("/tmp/sura-build-test/card/chroma.sqlite3").exists(), reason="real index not built")
def test_p12_007_clearing_priority_routes_to_m2c24():
    import build_page_collection as BP, owned_retrieval as OR, m2c_page_identity as pid, rag_pipeline as RP, rag_service as S, rag_evidence as EV, page_chunker as PK, rag_generate as RG
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
        raw, _ = svc._run_pipeline_request("Which indicator sets the clearing priority of original items?")
        assert raw["routing"]["selected_source_id"] == "M2C-24", f"expected M2C-24 got {raw['routing']['selected_source_id']}"
        assert raw["status"] == "answered"
        assert "clrg priority" in raw["answer"].lower()
    finally:
        svc.close()

@pytest.mark.skipif(not Path("/tmp/sura-build-test/card/chroma.sqlite3").exists(), reason="real index not built")
def test_p12_045_save_installment_routes_to_m2c24():
    import build_page_collection as BP, owned_retrieval as OR, m2c_page_identity as pid, rag_pipeline as RP, rag_service as S, rag_evidence as EV, page_chunker as PK, rag_generate as RG
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
        raw, _ = svc._run_pipeline_request("In which step of the procedure do I save the installment plan?")
        assert raw["routing"]["selected_source_id"] == "M2C-24", f"expected M2C-24 got {raw['routing']['selected_source_id']}"
        assert raw["status"] == "answered"
    finally:
        svc.close()

@pytest.mark.skipif(not Path("/tmp/sura-build-test/card/chroma.sqlite3").exists(), reason="real index not built")
def test_billing_safeguard_still_m2c14():
    import build_page_collection as BP, owned_retrieval as OR, m2c_page_identity as pid, rag_pipeline as RP, rag_service as S, rag_evidence as EV, page_chunker as PK, rag_generate as RG
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
        raw, _ = svc._run_pipeline_request("Which function creates an offsetting document when a bill turns out to be wrong?")
        assert raw["routing"]["selected_source_id"] == "M2C-14", f"billing safeguard broken, got {raw['routing']['selected_source_id']}"
    finally:
        svc.close()
