"""Malformed sampled-vector rejection and owned cleanup, without passing NaNs to native HNSW."""

import hashlib
from unittest.mock import Mock, patch

import owned_retrieval as OWN
import pytest


@pytest.mark.parametrize(
    "values",
    [[float("nan"), 1.0], [float("inf"), 1.0], [-float("inf"), 1.0], [0.0, 0.0]],
)
@pytest.mark.parametrize("owner", ["page", "card"])
def test_invalid_sampled_cosine_vector_rejected_and_only_new_client_closed(
    tmp_path, values, owner
):
    sentinel = tmp_path / "chroma.sqlite3"
    sentinel.write_bytes(b"synthetic SDK-mock sentinel, never opened as SQLite")
    before = hashlib.sha256(sentinel.read_bytes()).hexdigest()
    collection = Mock()
    collection.metadata = {
        "hnsw:space": "cosine",
        "vector_count": 1,
        "unit_count": 1,
        "embedding_model": "fixture",
        "embedding_dimensions": 2,
    }
    collection.get.return_value = {"embeddings": [values]}
    collection.count.return_value = 1
    client = Mock()
    client.get_collection.return_value = collection
    with patch.object(OWN, "_client", return_value=client):
        error_type = (
            OWN.PR.PageStoreUnavailable if owner == "page" else OWN.RT.RouterConfigError
        )
        with pytest.raises(error_type, match="finite nonzero"):
            if owner == "page":
                OWN.OwnedPageRetriever.from_store(
                    tmp_path,
                    embed=Mock(),
                    expected_dimension=2,
                    expected_model="fixture",
                )
            else:
                backend = OWN.OwnedCardBackend(
                    vector_dir=tmp_path,
                    embedder=Mock(),
                    expected_dimension=2,
                    expected_model="fixture",
                )
                backend._open()
    collection.get.assert_called_once_with(limit=1, include=["embeddings"])
    collection.add.assert_not_called()
    collection.update.assert_not_called()
    collection.delete.assert_not_called()
    client.close.assert_called_once()
    assert hashlib.sha256(sentinel.read_bytes()).hexdigest() == before
    assert list(tmp_path.iterdir()) == [sentinel]


def test_finite_nonzero_sample_preserves_existing_dimension_and_model_contract():
    collection = Mock()
    collection.metadata = {"embedding_model": "fixture", "embedding_dimensions": 2}
    collection.get.return_value = {"embeddings": [[1.0, 0.0]]}
    OWN._validate_vector_contract(collection, 2, "fixture", RuntimeError)
    collection.get.assert_called_once_with(limit=1, include=["embeddings"])
