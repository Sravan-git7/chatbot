"""Production client ownership without editing checkpoint-pinned router code.

Only clients created here are closed. Shared Chroma refcounts, not global cache
clearing, protect other owners. A close failure is terminal until process restart.
The factory lock coordinates SURA-owned clients; unrelated SDK users must not
concurrently reopen the same path during shutdown.
"""

import math
import sys
from pathlib import Path
from threading import RLock

import m2c_router as RT
import page_retriever as PR
import build_page_collection as BP

_FACTORY_LOCK = RLock()
_FAILED_CLIENTS = {}


def assert_path_reusable(path):
    root = Path(path).resolve()
    temporary = sys.modules.get("chroma_temp")
    if temporary is not None:
        temporary.assert_shutdown_safe(root)
    for failed, client in _FAILED_CLIENTS.items():
        if root == failed or root in failed.parents or failed in root.parents:
            raise RuntimeError(
                "Owned Chroma close failed; restart process before reuse"
            )


def _release_client(client, path):
    with _FACTORY_LOCK:
        assert_path_reusable(path)
        try:
            client.close()
        except BaseException:
            _FAILED_CLIENTS[Path(path).resolve()] = client
            raise


def _client(path):
    import chromadb
    from chromadb.config import Settings

    with _FACTORY_LOCK:
        assert_path_reusable(path)
        try:
            return chromadb.PersistentClient(
                path=str(path), settings=Settings(anonymized_telemetry=False)
            )
        except BaseException:
            _FAILED_CLIENTS[Path(path).resolve()] = (
                None  # Constructor may have partly registered a native system.
            )
            raise


def _validate_vector_contract(
    collection, expected_dimension, expected_model, error_type
):
    metadata = collection.metadata or {}
    if expected_model is not None and metadata.get("embedding_model") != expected_model:
        raise error_type(
            "Stored embedding model differs from the loaded model contract"
        )
    if expected_dimension is None:
        return  # Generic resource-only callers; production factory always supplies its loaded dimension.
    vectors = collection.get(limit=1, include=["embeddings"])["embeddings"]
    if (
        vectors is None
        or len(vectors) != 1
        or vectors[0] is None
        or len(vectors[0]) != expected_dimension
    ):
        raise error_type(
            "Stored vector dimension differs from the loaded embedding model"
        )
    # Shape/metadata agreement is insufficient for cosine search: NaN/Inf and zero vectors have no
    # usable cosine direction. Validate the existing sampled vector, never rewrite/normalise the store.
    values = [float(value) for value in vectors[0]]
    if not all(math.isfinite(value) for value in values) or not any(
        value != 0.0 for value in values
    ):
        raise error_type("Stored cosine vector must be finite nonzero")
    declared = metadata.get("embedding_dimensions")
    if declared is not None and declared != expected_dimension:
        raise error_type(
            "Declared vector dimension differs from the loaded embedding model"
        )


class _Owner:
    def close(self):
        with _FACTORY_LOCK:
            if getattr(self, "_close_failed", False):
                raise RuntimeError(
                    "Owned Chroma close previously failed; restart process"
                )
            client = getattr(self, "_client", None)
            if client is None:
                return
            try:
                _release_client(client, self._store_path)
            except BaseException:
                self._close_failed = True
                raise
            self._client = None
            self._closed = True


class OwnedCardBackend(_Owner, RT.ChromaCardBackend):
    def __init__(self, *args, expected_dimension=None, expected_model=None, **kwargs):
        # Support SURA_CARD_VECTOR_DIR staging override without silent fallback
        if not args and "vector_dir" not in kwargs:
            import os as _os
            _v = _os.environ.get("SURA_CARD_VECTOR_DIR")
            if _v and _v.strip():
                kwargs["vector_dir"] = Path(_v.strip())
        super().__init__(*args, **kwargs)
        self.expected_dimension = expected_dimension
        self.expected_model = expected_model

    def _open(self):
        with _FACTORY_LOCK:
            assert_path_reusable(self.vector_dir)
            if getattr(self, "_closed", False):
                raise RT.CardStoreUnavailable("Owned card backend is closed")
            if self._collection is not None:
                return self._collection
            if not (
                self.vector_dir.is_dir()
                and (self.vector_dir / "chroma.sqlite3").is_file()
            ):
                raise RT.CardStoreUnavailable("Card store is unavailable")
            client = _client(self.vector_dir)
            self._store_path = Path(self.vector_dir)
            self._client = client
            try:
                collection = client.get_collection(self.collection_name)
                if (collection.metadata or {}).get("hnsw:space") != RT.DISTANCE_METRIC:
                    raise RT.RouterConfigError("Unexpected card distance metric")
                _validate_vector_contract(
                    collection,
                    self.expected_dimension,
                    self.expected_model,
                    RT.RouterConfigError,
                )
            except BaseException:
                self.close()
                raise
            self._client = client
            self._collection = collection
            return collection


class OwnedPageRetriever(_Owner, PR.PageRetriever):
    @property
    def collection(self):
        if getattr(self, "_closed", False):
            raise PR.PageStoreUnavailable("Owned page retriever is closed")
        path = getattr(self, "_store_path", None)
        if path is not None:
            assert_path_reusable(path)
        return self._owned_collection

    @collection.setter
    def collection(self, value):
        self._owned_collection = value

    @classmethod
    def from_store(
        cls,
        vector_dir=None,
        collection=BP.PAGE_COLLECTION,
        embed=None,
        expected_dimension=None,
        expected_model=None,
    ):
        if vector_dir is None:
            import os as _os
            _v = _os.environ.get("SURA_PAGE_VECTOR_DIR")
            if _v and _v.strip():
                vector_dir = Path(_v.strip())
            else:
                vector_dir = BP.PAGE_VECTOR_DIR
        BP.guard_names(collection, Path(vector_dir))
        if not (
            Path(vector_dir).is_dir()
            and (Path(vector_dir) / "chroma.sqlite3").is_file()
        ):
            raise FileNotFoundError(
                "Page store is unavailable; implicit database creation is forbidden"
            )
        client = _client(vector_dir)
        try:
            col = client.get_collection(collection)
            metadata = col.metadata or {}
            if metadata.get("hnsw:space") != BP.DISTANCE_SPACE:
                raise PR.PageStoreUnavailable("Unexpected page distance metric")
            count = int(col.count())
            if count < 1 or (
                metadata.get("vector_count") is not None
                and int(metadata["vector_count"]) != count
            ):
                raise PR.PageStoreUnavailable(
                    "Page vector count is empty or differs from metadata"
                )
            _validate_vector_contract(
                col, expected_dimension, expected_model, PR.PageStoreUnavailable
            )
            result = cls(col, embed or BP.load_embedder()[0])
        except BaseException:
            _release_client(client, vector_dir)
            raise
        result._store_path = Path(vector_dir)
        result._client = client
        return result


def release_pipeline(pipeline):
    """Only build_pipeline-created resources, never injected fixture/third-party clients."""
    resources = getattr(pipeline, "_owned_resources", [])
    while resources:
        resources[-1].close()
        resources.pop()  # Remove only after successful close; failure remains retry-visible.
