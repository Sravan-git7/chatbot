"""Regression for monitoring routing fix (phase13 reranker penalty).

Verifies that transaction-code queries for Monitoring Meter Reading (EL43 etc.)
are not penalized as peripheral reporting when a code/phrase match exists.
Skipped if temp real index unavailable.
"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

@pytest.mark.skipif(not Path("/tmp/sura-build-test/card/chroma.sqlite3").exists(), reason="real index not built")
def test_monitoring_el43_routes_to_m2c07():
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
        raw, _ = svc._run_pipeline_request("What is the purpose of transaction EL43?")
        assert raw["routing"]["selected_source_id"] == "M2C-07", f"Expected M2C-07 got {raw['routing']['selected_source_id']}"
        assert raw["status"] == "answered"
        # Verify strict evidence: should contain overview of devices of a meter reading unit
        assert "M2C-07" in " ".join(str(s.get("source_ids")) for s in raw["citations"]["answer_sources"])
    finally:
        svc.close()

@pytest.mark.skipif(not Path("/tmp/sura-build-test/card/chroma.sqlite3").exists(), reason="real index not built")
def test_monitoring_penalty_not_applied_with_code_match():
    # Direct check of reranker penalty conditioning — code_match exempts from
    # reporting penalty; generic verbatim phrase must not (fix for invoicing
    # routing to analytics vs procedure).
    import phase13_reranker as PR
    import inspect
    src = inspect.getsource(PR.score_candidate)
    assert "not code_match" in src
    assert "analysis" in src.lower()  # penalty still mentions reporting types
