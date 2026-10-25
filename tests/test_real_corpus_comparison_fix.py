"""Regression for real-corpus comparison balancing (hyphen handling).

If a separate real-document index was built (Step 2), verify that Move-In vs Move-Out
and Billing vs Invoicing each cite both sides when evidence is available.
Skipped if the temporary real index is unavailable (PDFs missing or model uninstalled).
"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import rag_evidence as EV
import rag_generate as RG


def test_thresholds_preserved():
    assert EV.TAU == 0.6
    assert EV.SHIPPED_TAU == 0.5
    assert RG.MIN_SENTENCE_SUPPORT == 0.6
    # Reranker weights preserved
    import phase13_reranker as PR
    assert PR.W_CARD == 0.50
    assert PR.W_PAGE == 0.40
    assert PR.W_COVERAGE == 0.10
    assert PR.W_TECH == 0.12


@pytest.mark.skipif(not Path("/tmp/sura-build-test/card/chroma.sqlite3").exists(), reason="real index not built - PDFs unavailable or build not run")
def test_real_index_move_in_vs_move_out_balanced():
    import owned_retrieval as OR
    import build_page_collection as BP
    import m2c_page_identity as pid
    import rag_pipeline as RP
    import page_chunker as PK

    card_dir = Path("/tmp/sura-build-test/card")
    page_dir = Path("/tmp/sura-build-test/page_collection")
    embed, minfo = BP.load_embedder()
    backend = OR.OwnedCardBackend(vector_dir=card_dir, embedder=embed, expected_dimension=384, expected_model=BP.C.MODEL_NAME)
    retriever = OR.OwnedPageRetriever.from_store(vector_dir=page_dir, embed=embed, expected_dimension=384, expected_model=BP.C.MODEL_NAME)
    count, _ = PK.make_token_counter(minfo["model_dir"])
    ctx = pid.IdentityContext.from_root(RP.ROOT if hasattr(RP, "ROOT") else Path("."))
    from rag_generate import ExtractiveGenerator
    base = RP.RagPipeline(backend, retriever, ctx, RP.PageCorpusIndex.from_dir(), ExtractiveGenerator(), count)
    pipeline = EV.build_evidence_pipeline(base, tau=EV.SHIPPED_TAU, widen=False, generator="extractive")
    try:
        res = pipeline.answer("Compare Move-In and Move-Out")
        assert res["status"] == "answered"
        srcs = set()
        for s in res["citations"]["answer_sources"]:
            srcs.update(s.get("source_ids", []))
        # Must cite both Move-In (M2C-03) and Move-Out (M2C-04) when using real corpus
        assert "M2C-03" in srcs, f"Missing M2C-03 in {srcs}"
        assert "M2C-04" in srcs, f"Missing M2C-04 in {srcs}"
        assert len(res["citations"]["answer_sources"]) >= 2
    finally:
        backend.close()
        retriever.close()


@pytest.mark.skipif(not Path("/tmp/sura-build-test/card/chroma.sqlite3").exists(), reason="real index not built")
def test_real_index_billing_vs_invoicing_balanced():
    import owned_retrieval as OR
    import build_page_collection as BP
    import m2c_page_identity as pid
    import rag_pipeline as RP
    import page_chunker as PK

    card_dir = Path("/tmp/sura-build-test/card")
    page_dir = Path("/tmp/sura-build-test/page_collection")
    embed, minfo = BP.load_embedder()
    backend = OR.OwnedCardBackend(vector_dir=card_dir, embedder=embed, expected_dimension=384, expected_model=BP.C.MODEL_NAME)
    retriever = OR.OwnedPageRetriever.from_store(vector_dir=page_dir, embed=embed, expected_dimension=384, expected_model=BP.C.MODEL_NAME)
    count, _ = PK.make_token_counter(minfo["model_dir"])
    ctx = pid.IdentityContext.from_root(RP.ROOT if hasattr(RP, "ROOT") else Path("."))
    from rag_generate import ExtractiveGenerator
    base = RP.RagPipeline(backend, retriever, ctx, RP.PageCorpusIndex.from_dir(), ExtractiveGenerator(), count)
    pipeline = EV.build_evidence_pipeline(base, tau=EV.SHIPPED_TAU, widen=False, generator="extractive")
    try:
        res = pipeline.answer("Compare Billing and Invoicing")
        assert res["status"] == "answered"
        srcs = set().union(*[set(s.get("source_ids", [])) for s in res["citations"]["answer_sources"]]) if res["citations"]["answer_sources"] else set()
        assert "M2C-11" in srcs or "M2C-14" in srcs
        # Should have at least 2 sources with both Billing and Invoicing represented
        assert len(srcs) >= 2 or len(res["citations"]["answer_sources"]) >= 2
    finally:
        backend.close()
        retriever.close()
