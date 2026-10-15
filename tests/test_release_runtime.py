"""Release regressions. Injected RAG is not real-model/semantic certification."""

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

import rag_api as API
import owned_retrieval as OWN
import chroma_temp as TEMP
from tests.test_predeployment_hardening import service
from tests.test_phase11_service import Q_PLAN

PRODUCTION = {
    "SURA_PROFILE": "production",
    "SURA_API_TOKEN": "fixture-only-not-a-secret-0123456789abcdef",
    "SURA_ALLOWED_HOSTS": "testserver",
    "RAG_ENABLE_DEBUG": "0",
    "SURA_LOG_QUERIES": "0",
    "SURA_INTENT_AWARE": "0",
    "SURA_SECTION_SELECTION": "0",
    "SURA_ADDITIONAL_EVIDENCE": "0",
    "RAG_CORS_ORIGINS": "",
    "SURA_RATE_LIMIT_PER_MINUTE": "60",
}
AUTH = {"Authorization": "Bearer " + PRODUCTION["SURA_API_TOKEN"]}


def app(**kwargs):
    return API.create_app(static_dir=Path("/nonexistent"), **kwargs)


def test_production_authentication_and_stateless_conversation_recovery():
    with patch.dict(os.environ, PRODUCTION):
        svc = service()
        with TestClient(app(service=svc)) as client:
            for headers in (
                {},
                {"Authorization": "Bearer wrong"},
                {"Authorization": "Basic " + PRODUCTION["SURA_API_TOKEN"]},
                {"Authorization": "Bearer " + "x" * 1000},
            ):
                response = client.post(
                    "/api/chat", json={"message": Q_PLAN}, headers=headers
                )
                assert response.status_code == 401
                assert response.headers["Cache-Control"] == "no-store"
                assert response.headers["WWW-Authenticate"] == "Bearer"
                assert svc._conversations == {}
                assert client.app.state.rag["active_requests"] == 0
            response = client.post(
                "/api/chat",
                json={"message": Q_PLAN, "conversation_id": "guessed-victim"},
                headers=AUTH,
            )
            assert response.status_code == 200
            cid = response.json()["conversation_id"]
            assert cid != "guessed-victim"
            assert svc._conversations == {}
            second = client.post(
                "/api/chat",
                json={"message": "explain more", "conversation_id": cid},
                headers=AUTH,
            )
            assert second.status_code == 200
            assert second.json()["conversation_id"] != cid
            assert second.json()["status"] != "answered"
            assert svc._conversations == {}
            assert client.get("/health").status_code == 200
            assert client.get("/ready").status_code == 200
            assert client.get("/api/health").status_code == 401
            assert client.get("/api/health", headers=AUTH).status_code == 200
            assert (
                client.get("/health", headers={"Host": "hostile.example"}).status_code
                == 400
            )


@pytest.mark.parametrize(
    "override",
    [
        {"SURA_API_TOKEN": ""},
        {"SURA_API_TOKEN": "short"},
        {"SURA_API_TOKEN": "é" * 40},
        {"SURA_ALLOWED_HOSTS": "*"},
        {"SURA_ALLOWED_HOSTS": ""},
        {"SURA_LOG_QUERIES": "1"},
        {"RAG_ENABLE_DEBUG": "1"},
        {"SURA_INTENT_AWARE": "1"},
        {"RAG_CORS_ORIGINS": "*"},
    ],
)
def test_unsafe_production_fails_closed_and_valid_new_app_recovers(override):
    with patch.dict(os.environ, {**PRODUCTION, **override}):
        client = TestClient(app(service=service()))  # No lifespan: still fail closed.
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
        assert (
            client.post("/api/chat", json={"message": Q_PLAN}, headers=AUTH).status_code
            == 503
        )
    with patch.dict(os.environ, PRODUCTION):
        assert TestClient(app(service=service())).get("/ready").status_code == 200


def test_explicit_debug_and_cors_overrides_cannot_bypass_production():
    with patch.dict(os.environ, PRODUCTION):
        for kwargs in ({"enable_debug": True}, {"cors_origins": ["*"]}):
            assert (
                TestClient(app(service=service(), **kwargs)).get("/ready").status_code
                == 503
            )


def test_startup_and_dependency_exception_messages_are_private():
    secret = "private-question-/operator/model/path-secret"
    with patch.object(API.logger, "error") as log:
        with TestClient(
            app(service_factory=Mock(side_effect=RuntimeError(secret)))
        ) as client:
            for path in ("/ready", "/api/health"):
                assert secret not in client.get(path).text
            assert client.get("/ready").status_code == 503
        assert secret not in repr(log.call_args_list)
    svc = service()
    svc.pipeline.retriever.count = Mock(side_effect=RuntimeError(secret))
    with patch.object(API.logger, "error") as log:
        client = TestClient(app(service=svc))
        assert secret not in client.get("/ready").text
        assert client.get("/ready").status_code == 503
        assert secret not in repr(log.call_args_list)
    svc.pipeline.retriever.count = lambda: 1
    assert TestClient(app(service=svc)).get("/ready").status_code == 200


def test_oversized_chunk_is_rejected_before_copy_and_slots_recover():
    class CheckedBuffer(bytearray):
        def extend(self, chunk):
            assert len(chunk) <= API.MAX_BODY_BYTES, (
                "Oversized chunk copied before checking limit"
            )
            super().extend(chunk)

    client = TestClient(app(service=service()))
    with patch.object(API, "bytearray", CheckedBuffer, create=True):
        response = client.post(
            "/api/chat",
            content=b"x" * (API.MAX_BODY_BYTES + 1),
            headers={"Content-Length": "1"},
        )
    assert response.status_code == 413
    assert response.headers["Cache-Control"] == "no-store"
    assert client.app.state.rag["active_requests"] == 0
    assert client.post("/api/chat", json={"message": Q_PLAN}).status_code == 200


def test_ip_bucket_capacity_is_bounded_and_expired_buckets_recover():
    client = TestClient(app(service=service()))
    state = client.app.state.rag
    with patch.object(API, "MAX_IP_BUCKETS", 2):
        import time

        state["ip_request_history"].update({"a": [time.time()], "b": [time.time()]})
        assert client.post("/api/chat", json={"message": Q_PLAN}).status_code == 429
        assert len(state["ip_request_history"]) == 2
        state["ip_request_history"]["a"] = [0]
        assert client.post("/api/chat", json={"message": Q_PLAN}).status_code == 200
        assert len(state["ip_request_history"]) == 2


def test_production_log_hash_is_not_a_public_dictionary_hash():
    with (
        patch.dict(os.environ, PRODUCTION),
        patch.object(API.structured_logger, "info") as log,
    ):
        client = TestClient(app(service=service()))
        assert (
            client.post("/api/chat", json={"message": Q_PLAN}, headers=AUTH).status_code
            == 200
        )
        record = json.loads(log.call_args.args[0])
        assert record["query"] != hashlib.sha256(Q_PLAN.encode()).hexdigest()[:16]
        assert Q_PLAN not in repr(log.call_args)
        assert PRODUCTION["SURA_API_TOKEN"] not in repr(log.call_args)


def test_only_factory_owned_service_is_closed_after_lifespan():
    injected = service()
    injected.close = Mock()
    with TestClient(app(service=injected)):
        pass
    injected.close.assert_not_called()
    factory_owned = service()
    factory_owned.close = Mock()
    with TestClient(app(service_factory=lambda _: factory_owned)) as client:
        assert client.get("/ready").status_code == 200
    factory_owned.close.assert_called_once()
    assert client.app.state.rag["shutting_down"]


def test_real_linux_owned_clients_preserve_external_owner_and_unrelated_store():
    import chromadb
    from chromadb.config import Settings

    with TEMP.ChromaTemporaryDirectory(prefix="owned-sdk-") as td:
        root = Path(td)
        store = root / "store"
        external = chromadb.PersistentClient(
            path=str(store), settings=Settings(anonymized_telemetry=False)
        )
        cards = external.create_collection(
            "sap_m2c_card_v1", metadata={"hnsw:space": "cosine", "unit_count": 1}
        )
        cards.add(ids=["fixture"], embeddings=[[1.0, 0.0]], documents=["fixture"])
        pages = external.create_collection(
            "sap_pages_v1", metadata={"hnsw:space": "cosine", "vector_count": 1}
        )
        pages.add(ids=["fixture-page"], embeddings=[[1.0, 0.0]], documents=["fixture"])
        outside = chromadb.PersistentClient(
            path=str(root / "other"), settings=Settings(anonymized_telemetry=False)
        )
        other = outside.create_collection("unrelated")
        other.add(ids=["fixture"], embeddings=[[1.0, 0.0]])
        backend = OWN.OwnedCardBackend(vector_dir=store, embedder=lambda _: [1.0, 0.0])
        retriever = OWN.OwnedPageRetriever.from_store(
            store, collection="sap_pages_v1", embed=lambda _: [1.0, 0.0]
        )
        assert backend.health_check() == 1
        pipeline = SimpleNamespace(_owned_resources=[backend, retriever])
        OWN.release_pipeline(pipeline)
        OWN.release_pipeline(pipeline)  # Idempotent successful close.
        assert cards.count() == pages.count() == other.count() == 1
        external.close()
        assert other.count() == 1
        outside.close()


def test_partial_owned_close_retains_diagnostic_state_blocks_cleanup_and_retry(
    tmp_path,
):
    client = Mock()
    client.close.side_effect = RuntimeError("partial native close")
    owner = OWN._Owner()
    owner._client, owner._store_path = client, tmp_path
    pipeline = SimpleNamespace(_owned_resources=[owner])
    try:
        with pytest.raises(RuntimeError, match="partial native close"):
            OWN.release_pipeline(pipeline)
        with pytest.raises(RuntimeError, match="restart process"):
            OWN.release_pipeline(pipeline)
        with pytest.raises(RuntimeError, match="restart process"):
            TEMP.close_systems_under(tmp_path)
        assert pipeline._owned_resources == [owner]
        assert OWN._FAILED_CLIENTS[tmp_path.resolve()] is client
        client.close.assert_called_once()
        assert tmp_path.exists()
    finally:
        OWN._FAILED_CLIENTS.pop(
            tmp_path.resolve(), None
        )  # Synthetic injected client only.


def test_partial_page_initialization_closes_only_new_client(tmp_path):
    client = Mock()
    client.get_collection.side_effect = RuntimeError("missing fixture collection")
    with patch.object(OWN, "_client", return_value=client):
        with pytest.raises(RuntimeError, match="missing fixture collection"):
            OWN.OwnedPageRetriever.from_store(tmp_path, embed=lambda _: [1.0, 0.0])
    client.close.assert_called_once()


def test_reranker_public_type_hints_resolve_without_model_load():
    from typing import get_type_hints
    import phase13_reranker as reranker

    assert get_type_hints(reranker.score_candidate)["query_code_tokens"]


def test_constructor_failure_is_quarantined_and_not_retried(tmp_path):
    import chromadb

    try:
        with patch.object(
            chromadb,
            "PersistentClient",
            side_effect=RuntimeError("partial fixture constructor"),
        ) as factory:
            with pytest.raises(RuntimeError, match="partial fixture constructor"):
                OWN._client(tmp_path)
            with pytest.raises(RuntimeError, match="restart process"):
                OWN._client(tmp_path)
            with pytest.raises(RuntimeError, match="restart process"):
                TEMP.close_systems_under(tmp_path)
            factory.assert_called_once()
    finally:
        OWN._FAILED_CLIENTS.pop(tmp_path.resolve(), None)  # Synthetic constructor only.


def test_build_service_failed_health_releases_only_builder_owned_resources():
    import rag_service as S
    import rag_pipeline as RP

    backend = Mock()
    backend.health_check.side_effect = RuntimeError("fixture startup health failure")
    page = Mock()
    pipeline = SimpleNamespace(backend=backend, _owned_resources=[backend, page])
    with patch.object(RP, "build_pipeline", return_value=pipeline):
        with pytest.raises(RuntimeError, match="fixture startup health failure"):
            S.build_service("extractive")
    backend.close.assert_called_once()
    page.close.assert_called_once()
    assert pipeline._owned_resources == []


def test_nonloopback_local_cli_does_not_start_listening():
    with patch.dict(os.environ, {"SURA_PROFILE": "local"}), patch("uvicorn.run") as run:
        with pytest.raises(SystemExit) as exit:
            API.main(["--host", "0.0.0.0"])
        assert exit.value.code == 2
        run.assert_not_called()


def test_shutdown_close_failure_is_visible_not_success():
    svc = service()
    svc.close = Mock(side_effect=RuntimeError("fixture close failed"))
    with pytest.raises(RuntimeError, match="fixture close failed"):
        with TestClient(app(service_factory=lambda _: svc)):
            pass
    svc.close.assert_called_once()


def test_stateless_error_retains_no_conversation_and_recovers():
    svc = service()
    original = svc.ask

    def partial(question, conversation_id, **kwargs):
        with svc._lock:
            svc._conversations[conversation_id] = {"fixture": "private"}
        raise RuntimeError("fixture partial request")

    with patch.object(svc, "ask", side_effect=partial):
        with pytest.raises(RuntimeError, match="fixture partial request"):
            svc.ask_stateless(Q_PLAN)
    assert svc._conversations == {}
    svc.ask = original
    assert svc.ask_stateless(Q_PLAN)["status"] == "answered"
    assert svc._conversations == {}


def test_evidence_pipeline_wrapper_transfers_owned_resource_list():
    import rag_service as S
    import rag_pipeline as RP

    base = service().pipeline
    first, second = Mock(), Mock()
    base._owned_resources = [first, second]
    with patch.object(RP, "build_pipeline", return_value=base):
        svc = S.build_service("extractive")
    assert svc.pipeline is not base
    assert svc.pipeline._owned_resources is base._owned_resources
    svc.close()
    svc.close()
    first.close.assert_called_once()
    second.close.assert_called_once()
    assert base._owned_resources == []
