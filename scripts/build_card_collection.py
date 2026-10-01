#!/usr/bin/env python3
"""Phase 4 / stage 4-5: embed the 29 retrieval units into a NEW ChromaDB collection (`sap_m2c_card_v1`).

Safety rules (enforced in code):
  * refuses to run unless `data/retrieval_token_stats.json` says PASS for exactly the current `data/retrieval_units.json`
    (no silent truncation, model unchanged);
  * never touches the legacy `chroma_db/` directory or the `sap_docs` collection: the new collection lives in its own
    persistent directory `data/vector_store/`; the names `sap_docs` and `chroma_db` are rejected outright;
  * verifies the collection does not exist yet (or, with --rebuild, deletes ONLY that collection) and is empty before inserting;
  * offline: HF hub/transformers offline mode is forced and ChromaDB telemetry is disabled;
  * the store is fully reproducible from `data/retrieval_units.json` with this script; `data/card_collection_manifest.json`
    records what was built (model, dimension, hashes, configuration, creation timestamp).

The text that is embedded is each unit's `embedding_text`. The vector record keeps readable provenance metadata.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from m2c_common import (COLLECTION_NAME, LEGACY_COLLECTION_NAME, MODEL_NAME, ROOT, TOKEN_STATS_PATH, UNITS_PATH, VECTOR_DIR,  # noqa: E402
                        resolve_model, sha256_file)

MANIFEST_PATH = ROOT / "data" / "card_collection_manifest.json"
BATCH_SIZE = 16
DISTANCE_SPACE = "cosine"


def guard_names(collection: str, vector_dir: Path) -> None:
    if collection == LEGACY_COLLECTION_NAME:
        raise SystemExit(f"refusing: collection name {collection!r} is the legacy RAG collection")
    if vector_dir.resolve() == (ROOT / "chroma_db").resolve() or vector_dir.name == "chroma_db":
        raise SystemExit(f"refusing: {vector_dir} is the legacy vector store directory")


def metadata_for(u: Dict[str, Any]) -> Dict[str, Any]:
    """Scalar-only metadata (ChromaDB requirement). Full text stays in data/retrieval_units.json (same retrieval_unit_id)."""
    return {
        "retrieval_unit_id": u["retrieval_unit_id"], "source_id": u["source_id"], "source_number": u["source_number"],
        "title": u["title"], "category": u["category"], "filename": u["filename"], "source_url": u["source_url"],
        "source_status": u["source_status"], "source_url_status": u["source_url_status"],
        "has_source_correction": bool(u["has_source_correction"]), "citation": u["citation"], "sha256": u["sha256"],
        "corpus_document": u["provenance"]["corpus_document"], "page_start": u["provenance"]["page_start"],
        "page_end": u["provenance"]["page_end"], "embedding_text_sha256": u["embedding_text_sha256"],
        "full_text_sha256": u["full_text_sha256"],
    }


def check_token_stats(units_path: Path, stats_path: Path) -> Dict[str, Any]:
    if not stats_path.is_file():
        raise SystemExit(f"{stats_path} missing: run scripts/validate_token_lengths.py first")
    st = json.loads(stats_path.read_text(encoding="utf-8"))
    if st.get("units_file_sha256") != sha256_file(units_path):
        raise SystemExit("token statistics are stale (units file changed): re-run scripts/validate_token_lengths.py")
    if st["embedding_text_over_limit"]:
        raise SystemExit(f"STOP: embedding_text over the model limit for {st['embedding_text_over_limit']}; not embedding")
    return st


def build(units_path: Path, vector_dir: Path, collection_name: str, rebuild: bool, model_path: Optional[str],
          manifest_path: Path, stats_path: Path) -> Dict[str, Any]:
    guard_names(collection_name, vector_dir)
    stats = check_token_stats(units_path, stats_path)
    payload = json.loads(units_path.read_text(encoding="utf-8"))
    units = payload["units"]
    if len(units) != 29 or len({u["retrieval_unit_id"] for u in units}) != 29:
        raise SystemExit("expected exactly 29 unique retrieval units")
    model_dir, model_info = resolve_model(model_path)

    import chromadb
    from chromadb.config import Settings
    from sentence_transformers import SentenceTransformer

    client = chromadb.PersistentClient(path=str(vector_dir), settings=Settings(anonymized_telemetry=False))
    existing = [c.name if hasattr(c, "name") else c for c in client.list_collections()]
    if LEGACY_COLLECTION_NAME in existing:
        print(f"note: {LEGACY_COLLECTION_NAME} exists in this directory; it will not be touched")
    if collection_name in existing:
        if not rebuild:
            raise SystemExit(f"collection {collection_name!r} already exists; pass --rebuild to delete and recreate ONLY that collection")
        client.delete_collection(collection_name)
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    model = SentenceTransformer(model_dir, device="cpu")
    if int(model.max_seq_length) != int(stats["max_seq_length"]):
        raise SystemExit("model max_seq_length differs from the validated token statistics")
    dim = int((getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension)())
    texts = [u["embedding_text"] for u in units]
    vecs = model.encode(texts, batch_size=BATCH_SIZE, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
    if vecs.shape != (len(units), dim):
        raise SystemExit(f"unexpected embedding shape {vecs.shape}")
    emb_sha = hashlib.sha256(vecs.astype("float32").tobytes()).hexdigest()

    config = {"collection": collection_name, "distance_space": DISTANCE_SPACE, "embedding_model": MODEL_NAME, "normalize_embeddings": True,
              "batch_size": BATCH_SIZE, "max_seq_length": int(model.max_seq_length), "truncation": "none needed (validated)",
              "document_embedded": "embedding_text", "strategy": "whole_document (one vector per card)", "device": "cpu",
              "chromadb": chromadb.__version__}
    col_meta = {"hnsw:space": DISTANCE_SPACE, "description": "SAP Utilities M2C reference cards, one vector per card (embedding_text)",
                "embedding_model": MODEL_NAME, "embedding_dimensions": dim, "source_corpus_file_sha256": payload["source_corpus"]["file_sha256"],
                "retrieval_units_file_sha256": sha256_file(units_path), "created_utc": created, "unit_count": len(units),
                "config_json": json.dumps(config, sort_keys=True)}
    collection = client.create_collection(name=collection_name, metadata=col_meta)
    if collection.count() != 0:
        raise SystemExit("new collection is not empty")
    collection.add(ids=[u["retrieval_unit_id"] for u in units], documents=texts, embeddings=vecs.tolist(),
                   metadatas=[metadata_for(u) for u in units])
    if collection.count() != len(units):
        raise SystemExit(f"collection holds {collection.count()} vectors, expected {len(units)}")

    manifest = {
        "collection_name": collection_name, "vector_store_dir": str(vector_dir.relative_to(ROOT)) if vector_dir.is_relative_to(ROOT) else str(vector_dir),
        "created_utc": created, "vector_count": collection.count(), "embedding_dimensions": dim,
        "embedding_model": MODEL_NAME, "embedding_model_provenance": model_info, "configuration": config,
        "source_corpus_file_sha256": payload["source_corpus"]["file_sha256"],
        "source_corpus_content_fingerprint": payload["source_corpus"]["content_fingerprint"],
        "retrieval_units_file_sha256": sha256_file(units_path),
        "token_stats_file_sha256": sha256_file(stats_path),
        "embeddings_float32_sha256": emb_sha,
        "embeddings_sha256_note": "hash of the float32 matrix as computed on this machine; may differ on other hardware/library builds",
        "legacy_collection_untouched": {"name": LEGACY_COLLECTION_NAME, "present_in_this_store": LEGACY_COLLECTION_NAME in existing},
        "reproduce_with": "python scripts/build_retrieval_units.py && python scripts/validate_token_lengths.py && python scripts/build_card_collection.py --rebuild",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--units", default=str(UNITS_PATH))
    ap.add_argument("--vector-dir", default=str(VECTOR_DIR))
    ap.add_argument("--collection", default=COLLECTION_NAME)
    ap.add_argument("--rebuild", action="store_true", help="delete and recreate ONLY the named new collection")
    ap.add_argument("--model-path", default=None)
    ap.add_argument("--manifest", default=str(MANIFEST_PATH))
    ap.add_argument("--token-stats", default=str(TOKEN_STATS_PATH))
    a = ap.parse_args(argv)
    m = build(Path(a.units), Path(a.vector_dir), a.collection, a.rebuild, a.model_path, Path(a.manifest), Path(a.token_stats))
    print(f"collection {m['collection_name']}: {m['vector_count']} vectors, {m['embedding_dimensions']} dimensions, model {m['embedding_model']}")
    print(f"manifest: {a.manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
