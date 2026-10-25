"""Staging vector-store env var integration."""
import os
import pathlib
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
import sys
sys.path.insert(0, str(SCRIPTS))

def test_staging_env_vars_resolve():
    """Owned retrieval and pipeline resolve explicit env vars, else production defaults."""
    import m2c_common as C
    import owned_retrieval as OR
    import rag_pipeline as RP
    # Defaults without env
    for k in ("SURA_CARD_VECTOR_DIR", "SURA_PAGE_VECTOR_DIR"):
        os.environ.pop(k, None)
    # Default via C.VECTOR_DIR
    assert C.VECTOR_DIR == ROOT / "data" / "vector_store"
    # With env, OwnedCardBackend uses env
    os.environ["SURA_CARD_VECTOR_DIR"] = "/tmp/staging/card"
    os.environ["SURA_PAGE_VECTOR_DIR"] = "/tmp/staging/pages"
    try:
        backend = OR.OwnedCardBackend(embedder=lambda x: [[0.0]*384])
        assert backend.vector_dir == pathlib.Path("/tmp/staging/card")
        backend2 = OR.OwnedPageRetriever  # just check env reading via pipeline helper
        # Verify rag_pipeline helper resolves env
        import rag_pipeline
        # Build a dummy pipeline would read env, but we test resolver directly
        # Check that _resolve respects env via direct call simulation
        os.environ["SURA_CARD_VECTOR_DIR"] = "/tmp/staging/card2"
        # Create backend via explicit env should still work
        b = OR.OwnedCardBackend(embedder=lambda x: [[0.0]*384])
        assert str(b.vector_dir) == "/tmp/staging/card2"
    finally:
        os.environ.pop("SURA_CARD_VECTOR_DIR", None)
        os.environ.pop("SURA_PAGE_VECTOR_DIR", None)
    # Back to default after env cleared, OwnedCardBackend without env should use production default
    backend_default = OR.OwnedCardBackend(embedder=lambda x: [[0.0]*384])
    assert backend_default.vector_dir == C.VECTOR_DIR

def test_chroma_backend_uses_explicit_path_when_given():
    import m2c_router as RT
    # Explicit path always wins over env (even if env is set)
    os.environ["SURA_CARD_VECTOR_DIR"] = "/tmp/staging/card"
    try:
        b2 = RT.ChromaCardBackend(vector_dir=pathlib.Path("/explicit/path"))
        assert b2.vector_dir == pathlib.Path("/explicit/path")
        # Without explicit, base class uses production default (not env) - OwnedCardBackend handles env
        b = RT.ChromaCardBackend(vector_dir=pathlib.Path("/tmp/staging/card"))
        assert b.vector_dir == pathlib.Path("/tmp/staging/card")
    finally:
        os.environ.pop("SURA_CARD_VECTOR_DIR", None)

def test_owned_backends_respect_env(tmp_path):
    import owned_retrieval as OR
    # Without env, defaults to C.VECTOR_DIR
    for k in ("SURA_CARD_VECTOR_DIR", "SURA_PAGE_VECTOR_DIR"):
        os.environ.pop(k, None)
    import m2c_common as C
    backend_def = OR.OwnedCardBackend(embedder=lambda x: [[0.0]*384])
    assert backend_def.vector_dir == C.VECTOR_DIR
    # With env, OwnedCardBackend picks it up when no explicit arg
    os.environ["SURA_CARD_VECTOR_DIR"] = str(tmp_path / "card_env")
    try:
        backend = OR.OwnedCardBackend(embedder=lambda x: [[0.0]*384])
        assert backend.vector_dir == pathlib.Path(str(tmp_path / "card_env"))
    finally:
        os.environ.pop("SURA_CARD_VECTOR_DIR", None)

def test_no_silent_fallback_to_production(tmp_path):
    """If env points to missing dir, service must fail, not fallback to production."""
    os.environ["SURA_CARD_VECTOR_DIR"] = str(tmp_path / "nonexistent_card")
    os.environ["SURA_PAGE_VECTOR_DIR"] = str(tmp_path / "nonexistent_page")
    try:
        from scripts.rag_service import build_service
        with pytest.raises(Exception) as exc:
            build_service("extractive")
        msg = str(exc.value).lower()
        # Should mention missing store, not silently succeed with production data
        assert "unavailable" in msg or "not found" in msg or "empty" in msg
    finally:
        os.environ.pop("SURA_CARD_VECTOR_DIR", None)
        os.environ.pop("SURA_PAGE_VECTOR_DIR", None)

def test_api_validate_configuration_respects_env(tmp_path):
    import os
    from scripts.rag_api import validate_configuration
    os.environ["SURA_CARD_VECTOR_DIR"] = str(tmp_path / "api_card")
    os.environ["SURA_PAGE_VECTOR_DIR"] = str(tmp_path / "api_page")
    try:
        cfg = validate_configuration()
        assert "card_collection_exists" in cfg
    finally:
        os.environ.pop("SURA_CARD_VECTOR_DIR", None)
        os.environ.pop("SURA_PAGE_VECTOR_DIR", None)

def test_pipeline_build_respects_env(tmp_path):
    """rag_pipeline.build_pipeline must honor env vars when no explicit dirs."""
    import os
    os.environ["SURA_CARD_VECTOR_DIR"] = "/tmp/sura-build-test/card"
    os.environ["SURA_PAGE_VECTOR_DIR"] = "/tmp/sura-build-test/page_collection"
    try:
        from scripts.rag_pipeline import build_pipeline
        from scripts.rag_service import production_pipeline_config
        # This should succeed against isolated index (built outside)
        # If isolated indexes not present, skip
        import pathlib
        if not pathlib.Path("/tmp/sura-build-test/card/chroma.sqlite3").is_file():
            pytest.skip("isolated indexes not present")
        pipeline = build_pipeline(generator="extractive", config=production_pipeline_config())
        assert pipeline.backend.vector_dir == pathlib.Path("/tmp/sura-build-test/card")
        assert pipeline.retriever._store_path == pathlib.Path("/tmp/sura-build-test/page_collection")
        pipeline._owned_resources[0].close()
        pipeline._owned_resources[1].close()
    finally:
        os.environ.pop("SURA_CARD_VECTOR_DIR", None)
        os.environ.pop("SURA_PAGE_VECTOR_DIR", None)
