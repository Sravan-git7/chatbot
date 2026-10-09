"""Phase 7A - M2C card router (topic identification only).

What this module does
---------------------
Given a user query it asks the ``sap_m2c_card_v1`` collection (built by ``scripts/build_card_collection.py``) for the
nearest M2C cards and returns them, in the order the collection returned them, as a stable application-level structure
(``CardCandidate``).

What this module deliberately does NOT do
-----------------------------------------
* It is not the SAP-page retriever and does not replace it. A card is a short description of what an SAP topic covers
  plus its SAP Help URL; it does not contain the SAP page text.
* It has no confidence / refusal threshold. The legacy ``MAX_DISTANCE = 1.0`` in ``scripts/rag_core.py`` is a
  squared-L2 cut-off (cosine >= 0.5) calibrated on page chunks; it is not calibrated for cards and is not used here.
  Any cut-off is a caller-side policy (see ``scripts/m2c_orchestrator.py``).
* It does not import ``rag_core``/``rag_chat``/``retrieve``, does not touch ``sap_docs`` or ``chroma_db/``, never writes
  to the card store, never calls an LLM and never uses the network.

Metadata contract
-----------------
The canonical URL field is ``source_url`` (the card collection's key). The legacy collection used ``url``; this module
never reads or emits ``url``. A record that only has the legacy ``url`` key is rejected (``CardMetadataError``), not
silently accepted.

Distance semantics
------------------
``distance`` is passed through unchanged from the collection, which is built with the cosine space: ``distance = 1 - cosine``
(0 = identical direction). It is NOT the legacy squared-L2 value (``2 - 2*cosine``) and the two must not be compared or
thresholded interchangeably. A backend that does not declare the ``cosine`` metric is refused.

Importing this module imports no third-party package. ``chromadb`` / ``sentence_transformers`` are imported lazily, only
inside ``ChromaCardBackend`` when it is actually used.
"""
from __future__ import annotations

import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, List, Mapping, Optional, Protocol, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m2c_common import COLLECTION_NAME, LEGACY_COLLECTION_NAME, VECTOR_DIR  # noqa: E402

DISTANCE_METRIC = "cosine"
DEFAULT_TOP_K = 5

# Metadata keys every card record must carry (missing key -> CardMetadataError, never a silent default).
REQUIRED_METADATA_KEYS: Tuple[str, ...] = (
    "source_id", "title", "category", "source_url", "source_status", "source_url_status",
    "has_source_correction", "citation",
)
# Provenance keys passed through when present; ``None`` (explicit) when a collection does not carry them.
OPTIONAL_METADATA_KEYS: Tuple[str, ...] = (
    "retrieval_unit_id", "source_number", "filename", "sha256", "corpus_document", "page_start", "page_end",
)


class RouterError(Exception):
    """Base class for router failures (all are explicit; nothing is swallowed)."""


class CardStoreUnavailable(RouterError):
    """The card vector store or collection is not available (for example ``data/vector_store/`` is absent)."""


class CardMetadataError(RouterError):
    """A collection record does not have the card metadata contract."""


class RouterConfigError(RouterError):
    """Invalid arguments, or a backend that is not a cosine card backend."""


class CardBackend(Protocol):
    """Anything that can answer a nearest-card query in the Chroma result shape.

    ``query`` returns ``{"ids": [[...]], "metadatas": [[...]], "distances": [[...]]}`` (one query row, ascending distance).
    ``distance_metric`` must be ``"cosine"``.
    """

    distance_metric: str

    def query(self, query: str, n_results: int) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class CardCandidate:
    """One ranked M2C card. ``source_url`` is canonical; there is deliberately no ``url`` attribute."""

    rank: int                      # 1-based position in the backend's order
    source_id: str                 # e.g. "M2C-17"
    title: str
    category: str
    source_url: str
    source_status: str             # "verified" | "needs_review"
    source_url_status: str         # "ok" | "needs_review"
    has_source_correction: bool
    citation: str
    distance: float                # cosine distance as returned by the collection (1 - cosine)
    distance_metric: str           # always "cosine"
    retrieval_unit_id: Optional[str] = None
    source_number: Optional[int] = None
    filename: Optional[str] = None
    sha256: Optional[str] = None
    corpus_document: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RouterResult:
    query: str
    top_k: int
    distance_metric: str
    candidates: Tuple[CardCandidate, ...]

    def to_dict(self) -> dict:
        return {"query": self.query, "top_k": self.top_k, "distance_metric": self.distance_metric,
                "candidates": [c.to_dict() for c in self.candidates]}


# --------------------------------------------------------------------------------------------------- normalisation

def normalize_candidate(rank: int, chroma_id: Optional[str], metadata: Mapping[str, Any], distance: Any) -> CardCandidate:
    """Convert one raw collection record into a ``CardCandidate`` (strict: no guessing, no key aliasing)."""
    if not isinstance(metadata, Mapping):
        raise CardMetadataError(f"rank {rank}: metadata is not a mapping")
    missing = [k for k in REQUIRED_METADATA_KEYS if k not in metadata]
    if missing:
        legacy_hint = " (legacy key 'url' is not accepted as a substitute for 'source_url')" if "url" in metadata and "source_url" in missing else ""
        raise CardMetadataError(f"rank {rank}: missing metadata key(s) {missing}{legacy_hint}")
    if chroma_id is not None and str(chroma_id) != str(metadata["source_id"]):
        raise CardMetadataError(f"rank {rank}: collection id {chroma_id!r} differs from metadata source_id {metadata['source_id']!r}")
    if isinstance(distance, bool) or not isinstance(distance, (int, float)) or not math.isfinite(float(distance)):
        raise CardMetadataError(f"rank {rank}: distance {distance!r} is not a finite number")
    if not isinstance(metadata["has_source_correction"], bool):
        raise CardMetadataError(f"rank {rank}: has_source_correction is not a boolean")
    extras = {k: metadata.get(k) for k in OPTIONAL_METADATA_KEYS}
    return CardCandidate(
        rank=rank,
        source_id=str(metadata["source_id"]),
        title=str(metadata["title"]),
        category=str(metadata["category"]),
        source_url=str(metadata["source_url"]),
        source_status=str(metadata["source_status"]),
        source_url_status=str(metadata["source_url_status"]),
        has_source_correction=metadata["has_source_correction"],
        citation=str(metadata["citation"]),
        distance=float(distance),
        distance_metric=DISTANCE_METRIC,
        **extras,
    )


def _validate_top_k(top_k: Any) -> int:
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise RouterConfigError(f"top_k must be an integer >= 1, got {top_k!r}")
    return top_k


def route(query: str, backend: CardBackend, top_k: int = DEFAULT_TOP_K) -> RouterResult:
    """Return up to ``top_k`` ranked card candidates for ``query``.

    * Order is exactly the backend's order (ascending cosine distance for Chroma); nothing is re-sorted or filtered.
    * No threshold is applied: a far-away card is still returned, with its distance, and the caller decides.
    * An empty / whitespace-only query returns no candidates and does not query the backend.
    """
    top_k = _validate_top_k(top_k)
    if not isinstance(query, str):
        raise RouterConfigError("query must be a string")
    metric = getattr(backend, "distance_metric", None)
    if metric != DISTANCE_METRIC:
        raise RouterConfigError(f"backend distance metric is {metric!r}; the card router requires {DISTANCE_METRIC!r} "
                                f"(the legacy sap_docs store uses squared L2 and is not interchangeable)")
    if not query.strip():
        return RouterResult(query=query, top_k=top_k, distance_metric=DISTANCE_METRIC, candidates=())

    raw = backend.query(query.strip(), top_k)
    try:
        ids, metas, dists = raw["ids"][0], raw["metadatas"][0], raw["distances"][0]
    except (KeyError, IndexError, TypeError) as e:
        raise CardMetadataError(f"backend result does not have the Chroma shape (ids/metadatas/distances): {e!r}") from e
    if not (len(ids) == len(metas) == len(dists)):
        raise CardMetadataError("backend result lists have different lengths")
    candidates: List[CardCandidate] = [
        normalize_candidate(i, cid, meta, dist) for i, (cid, meta, dist) in enumerate(zip(ids, metas, dists), start=1)
    ]
    return RouterResult(query=query, top_k=top_k, distance_metric=DISTANCE_METRIC, candidates=tuple(candidates[:top_k]))


# --------------------------------------------------------------------------------------------------- default backend

Embedder = Callable[[Sequence[str]], Sequence[Sequence[float]]]


class ChromaCardBackend:
    """Read-only access to ``sap_m2c_card_v1`` in ``data/vector_store/`` (lazy imports; nothing happens at import time).

    * Refuses the legacy names (collection ``sap_docs``; any directory called ``chroma_db``).
    * Never creates a store: a missing directory / database file raises ``CardStoreUnavailable``.
    * Never calls add / upsert / delete. (ChromaDB itself may update its own bookkeeping files when a store is opened.)
    * ``embedder`` is injectable (tests). The default loads the same ``all-MiniLM-L6-v2`` weights that built the collection,
      via ``m2c_common.resolve_model`` (no download), and encodes with ``normalize_embeddings=True``.
    """

    distance_metric = DISTANCE_METRIC

    def __init__(self, vector_dir: Path = VECTOR_DIR, collection_name: str = COLLECTION_NAME,
                 embedder: Optional[Embedder] = None, model_path: Optional[str] = None) -> None:
        if collection_name == LEGACY_COLLECTION_NAME:
            raise RouterConfigError(f"refusing: {collection_name!r} is the legacy page collection, not a card collection")
        vector_dir = Path(vector_dir)
        if vector_dir.name == "chroma_db":
            raise RouterConfigError(f"refusing: {vector_dir} is the legacy vector store directory")
        self.vector_dir = vector_dir
        self.collection_name = collection_name
        self._embedder = embedder
        self._model_path = model_path
        self._collection = None

    def _open(self):
        if self._collection is not None:
            return self._collection
        if not (self.vector_dir.is_dir() and (self.vector_dir / "chroma.sqlite3").is_file()):
            raise CardStoreUnavailable(f"card vector store not found at {self.vector_dir} (build it with scripts/build_card_collection.py)")
        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError as e:  # pragma: no cover - depends on the environment
            raise CardStoreUnavailable(f"chromadb is not installed: {e}") from e
        client = chromadb.PersistentClient(path=str(self.vector_dir), settings=Settings(anonymized_telemetry=False))
        try:
            collection = client.get_collection(self.collection_name)
        except Exception as e:
            raise CardStoreUnavailable(f"collection {self.collection_name!r} not found in {self.vector_dir}: {e}") from e
        space = (collection.metadata or {}).get("hnsw:space")
        if space != DISTANCE_METRIC:
            raise RouterConfigError(f"collection {self.collection_name!r} reports distance space {space!r}; expected {DISTANCE_METRIC!r}")
        self._collection = collection
        return collection

    def health_check(self) -> int:
        """Open and validate the read-only card collection without running a query or loading another model."""
        try:
            collection = self._open()
            count = int(collection.count())
        except CardStoreUnavailable:
            raise
        except Exception as e:
            raise CardStoreUnavailable(f"card collection {self.collection_name!r} could not be counted: {e}") from e
        if count < 1:
            raise CardStoreUnavailable(f"collection {self.collection_name!r} is empty")
        metadata = getattr(collection, "metadata", None) or {}
        declared_count = metadata.get("unit_count", metadata.get("vector_count"))
        if declared_count is not None:
            try:
                declared_count = int(declared_count)
            except (TypeError, ValueError) as e:
                raise CardStoreUnavailable(f"card collection {self.collection_name!r} has invalid declared unit_count {declared_count!r}") from e
            if count != declared_count:
                raise CardStoreUnavailable(f"card collection {self.collection_name!r} has {count} vectors, but metadata records {declared_count}")
        return count

    def _embed(self, text: str) -> List[float]:
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:  # pragma: no cover - depends on the environment
                raise CardStoreUnavailable(f"sentence-transformers is not installed: {e}") from e
            from m2c_common import resolve_model
            model_dir, _info = resolve_model(self._model_path)
            model = SentenceTransformer(model_dir, device="cpu")

            def _encode(texts: Sequence[str]):
                return model.encode(list(texts), normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False).tolist()

            self._embedder = _encode
        vec = self._embedder([text])[0]
        return [float(x) for x in vec]

    def query(self, query: str, n_results: int) -> Mapping[str, Any]:
        collection = self._open()
        n = min(int(n_results), int(collection.count()))
        if n < 1:
            raise CardStoreUnavailable(f"collection {self.collection_name!r} is empty")
        return collection.query(query_embeddings=[self._embed(query)], n_results=n, include=["metadatas", "distances"])
