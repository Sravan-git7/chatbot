#!/usr/bin/env python3
"""Phase 8D - build the PAGE-CHUNK vector collection ``sap_pages_v1`` (separate from the card collection ``sap_m2c_card_v1``).

* Location: ``data/vector_store/page_collection/`` - its own Chroma persistent client / sqlite database, so the card store
  (``data/vector_store/``, collection list asserted to be exactly ``["sap_m2c_card_v1"]`` by earlier tests) is never opened for writing,
  never listed with extra collections and never rebuilt by this script. The directory is covered by the existing ``.gitignore`` entry
  ``data/vector_store/``. The legacy ``chroma_db/`` / ``sap_docs`` names are refused.
* Input: ``data/page_corpus/pages/*/*.json`` (admitted page records only) chunked with ``page_chunker`` (default strategy
  ``B_heading_200``, declared before the evaluation).
* Embedded text: each chunk's ``embedding_text`` (title > heading path + text); stored document and cited text: ``text``.
* Reproducible: same corpus + same chunk config + same model -> same ids, same documents, same ``build_fingerprint``. The float
  embedding hash is recorded but is hardware dependent.
* Manifest: ``data/page_collection_manifest.json`` (model, dimension, metric, corpus hash, chunk config, vector count, hashes).

    python scripts/build_page_collection.py [--rebuild] [--strategy B_heading_200] [--manifest PATH] [--vector-dir DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import m2c_common as C  # noqa: E402
import page_chunker as PK  # noqa: E402
import page_corpus as PC  # noqa: E402

ROOT = C.ROOT
PAGE_VECTOR_DIR = C.VECTOR_DIR / "page_collection"
PAGE_COLLECTION = "sap_pages_v1"
MANIFEST_PATH = ROOT / "data" / "page_collection_manifest.json"
DISTANCE_SPACE = "cosine"
BATCH_SIZE = 16
Embedder = Callable[[Sequence[str]], List[List[float]]]


def guard_names(collection: str, vector_dir: Path) -> None:
    if collection in (C.LEGACY_COLLECTION_NAME, C.COLLECTION_NAME):
        raise SystemExit(f"refusing: {collection!r} is the legacy RAG collection or the card collection")
    vd = Path(vector_dir).resolve()
    if vd.name == "chroma_db" or vd == (ROOT / "chroma_db").resolve():
        raise SystemExit(f"refusing: {vector_dir} is the legacy vector store directory")
    if vd == C.VECTOR_DIR.resolve():
        raise SystemExit("refusing: the card store directory itself; page chunks go to their own client directory")


def load_embedder(model_path: Optional[str] = None) -> "tuple[Embedder, Dict[str, Any]]":
    from sentence_transformers import SentenceTransformer
    model_dir, info = C.resolve_model(model_path)
    model = SentenceTransformer(model_dir, device="cpu")
    dim = int((getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension)())

    def embed(texts: Sequence[str]) -> List[List[float]]:
        return model.encode(list(texts), batch_size=BATCH_SIZE, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False).tolist()

    return embed, {"provenance": info, "dimensions": dim, "max_seq_length": int(model.max_seq_length), "model_dir": model_dir}


def chunk_metadata(c: Dict[str, Any], record_by_doc: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Scalar-only Chroma metadata that carries everything the citation layer needs."""
    rng = c.get("block_range") or [None, None]
    md = {"chunk_id": c["chunk_id"], "doc_id": f"{c['guide_id']}/{c['page_id']}", "guide_id": c["guide_id"], "page_id": c["page_id"],
          "source_ids": c["source_ids"], "source_url": c["source_url"], "title": c["title"], "heading_path": " > ".join(c["heading_path"]),
          "heading_path_json": json.dumps(c["heading_path"], ensure_ascii=False), "section_title": c["section_title"], "chunk_index": c["chunk_index"],
          "chunk_count": c["chunk_count"], "content_hash": c["content_hash"], "token_count": c["token_count"], "char_count": c["char_count"],
          "strategy": c["strategy"], "embedding_text_sha256": hashlib.sha256(c["embedding_text"].encode("utf-8")).hexdigest(),
          "page_text_sha256": record_by_doc[f"{c['guide_id']}/{c['page_id']}"]["text_sha256"]}
    if rng[0] is not None:
        md["block_start"], md["block_end"] = int(rng[0]), int(rng[1])
    return {k: v for k, v in md.items() if v is not None}


def fill_collection(collection: Any, chunks: Sequence[Dict[str, Any]], records: Sequence[Dict[str, Any]], embed: Embedder) -> str:
    by_doc = {r["doc_id"]: r for r in records}
    vecs = embed([c["embedding_text"] for c in chunks])
    import numpy as np
    emb_sha = hashlib.sha256(np.asarray(vecs, dtype="float32").tobytes()).hexdigest()
    collection.add(ids=[c["chunk_id"] for c in chunks], documents=[c["text"] for c in chunks], embeddings=vecs,
                   metadatas=[chunk_metadata(c, by_doc) for c in chunks])
    return emb_sha


def chunks_fingerprint(chunks: Sequence[Dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for c in sorted(chunks, key=lambda x: x["chunk_id"]):
        h.update(f"{c['chunk_id']}\t{c['content_hash']}\t{hashlib.sha256(c['embedding_text'].encode('utf-8')).hexdigest()}\n".encode("utf-8"))
    return h.hexdigest()


def collection_metadata(dim: int, strategy: PK.ChunkConfig, corpus_hash: str, fingerprint: str, n: int, created: str) -> Dict[str, Any]:
    return {"hnsw:space": DISTANCE_SPACE, "description": "SAP Utilities page chunks (heading-aware), one vector per chunk", "embedding_model": C.MODEL_NAME,
            "embedding_dimensions": dim, "corpus_sha256": corpus_hash, "chunks_fingerprint": fingerprint, "chunk_strategy": strategy.name,
            "chunk_config_json": json.dumps(strategy.to_dict(), sort_keys=True), "vector_count": n, "created_utc": created}


def build(vector_dir: Path, collection_name: str, strategy_name: str, rebuild: bool, model_path: Optional[str], manifest_path: Path,
          corpus_dir: Path = PC.CORPUS_DIR) -> Dict[str, Any]:
    guard_names(collection_name, vector_dir)
    records = PC.load_records(corpus_dir)
    if not records:
        raise SystemExit(f"no page records in {corpus_dir}: run scripts/page_corpus.py first")
    corpus_manifest = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    cfg = PK.STRATEGIES[strategy_name]
    embed, minfo = load_embedder(model_path)
    count, tinfo = PK.make_token_counter(minfo["model_dir"])
    if not tinfo.get("exact"):
        raise SystemExit(f"exact tokenizer unavailable: {tinfo}")
    chunks = PK.chunk_corpus(records, cfg, count)
    over = [c["chunk_id"] for c in chunks if c["exceeds_model_limit"]]
    if over:
        raise SystemExit(f"STOP: chunks exceed the model limit ({PK.MODEL_MAX_TOKENS} tokens) and would be truncated silently: {over[:5]}")
    import chromadb
    from chromadb.config import Settings
    Path(vector_dir).mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(vector_dir), settings=Settings(anonymized_telemetry=False))
    existing = [c.name if hasattr(c, "name") else c for c in client.list_collections()]
    if collection_name in existing:
        if not rebuild:
            raise SystemExit(f"collection {collection_name!r} already exists; pass --rebuild to delete and recreate ONLY that collection")
        client.delete_collection(collection_name)
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    fp = chunks_fingerprint(chunks)
    col = client.create_collection(name=collection_name, metadata=collection_metadata(minfo["dimensions"], cfg, corpus_manifest["corpus_sha256"], fp, len(chunks), created))
    emb_sha = fill_collection(col, chunks, records, embed)
    if col.count() != len(chunks):
        raise SystemExit(f"collection holds {col.count()} vectors, expected {len(chunks)}")
    manifest = {
        "collection_name": collection_name, "vector_store_dir": str(Path(vector_dir).relative_to(ROOT)) if Path(vector_dir).is_relative_to(ROOT) else str(vector_dir),
        "created_utc": created, "vector_count": col.count(), "embedding_dimensions": minfo["dimensions"], "distance_space": DISTANCE_SPACE,
        "embedding_model": C.MODEL_NAME, "embedding_model_provenance": minfo["provenance"], "max_seq_length": minfo["max_seq_length"],
        "normalize_embeddings": True, "chunk_strategy": strategy_name, "chunk_config": cfg.to_dict(), "token_counter": tinfo,
        "corpus_sha256": corpus_manifest["corpus_sha256"], "pages": len(records), "page_doc_ids": sorted(r["doc_id"] for r in records),
        "chunks_fingerprint": fp, "chunk_stats": PK.chunk_stats(chunks), "embeddings_float32_sha256": emb_sha,
        "embeddings_sha256_note": "hash of the float32 matrix as computed on this machine; may differ on other hardware/library builds",
        "card_collection_untouched": {"name": C.COLLECTION_NAME, "dir": "data/vector_store", "opened_by_this_script": False},
        "legacy_collection_untouched": {"name": C.LEGACY_COLLECTION_NAME},
        "chromadb": chromadb.__version__,
        "reproduce_with": "python scripts/page_corpus.py && python scripts/build_page_collection.py --rebuild",
    }
    Path(manifest_path).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Embed page chunks into the separate collection sap_pages_v1.")
    ap.add_argument("--vector-dir", default=str(PAGE_VECTOR_DIR))
    ap.add_argument("--collection", default=PAGE_COLLECTION)
    ap.add_argument("--strategy", default=PK.DEFAULT_STRATEGY, choices=sorted(PK.STRATEGIES))
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--model-path")
    ap.add_argument("--manifest", default=str(MANIFEST_PATH))
    a = ap.parse_args(argv)
    m = build(Path(a.vector_dir), a.collection, a.strategy, a.rebuild, a.model_path, Path(a.manifest))
    print(f"built {m['collection_name']}: {m['vector_count']} vectors, {m['embedding_dimensions']} dims, {m['distance_space']}, strategy {m['chunk_strategy']}")
    print(f"corpus_sha256 {m['corpus_sha256']}\nchunks_fingerprint {m['chunks_fingerprint']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
