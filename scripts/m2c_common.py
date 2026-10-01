"""Shared helpers for the Phase-4 M2C card retrieval scripts (units, token check, collection, evaluation).

Nothing here touches the network. The embedding model is the one the existing RAG configuration names
(`EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"` in scripts/rag_core.py); this module only finds its files locally.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = ROOT / "data" / "source_corpus.json"
UNITS_PATH = ROOT / "data" / "retrieval_units.json"
TOKEN_STATS_PATH = ROOT / "data" / "retrieval_token_stats.json"
VECTOR_DIR = ROOT / "data" / "vector_store"            # separate from the legacy chroma_db/ (collection sap_docs)
COLLECTION_NAME = "sap_m2c_card_v1"
LEGACY_COLLECTION_NAME = "sap_docs"
MODEL_NAME = "all-MiniLM-L6-v2"                        # same name as scripts/rag_core.py EMBEDDING_MODEL_NAME (not modified)
MODEL_ENV = "M2C_MODEL_DIR"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def resolve_model(model_path: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
    """Locate all-MiniLM-L6-v2 WITHOUT downloading anything.

    Order: explicit path -> $M2C_MODEL_DIR -> the pip package `gt-all-minilm-l6-v2` (third-party packaging of
    sentence-transformers/all-MiniLM-L6-v2 weights, used because huggingface.co is not reachable from the build sandbox)
    -> the Hugging Face cache (offline mode). Returns (directory, provenance description)."""
    cands = []
    if model_path:
        cands.append(("explicit --model-path", Path(model_path)))
    if os.environ.get(MODEL_ENV):
        cands.append((f"${MODEL_ENV}", Path(os.environ[MODEL_ENV])))
    try:
        import gt_all_minilm_l6_v2  # type: ignore
        cands.append(("pip package gt-all-minilm-l6-v2 (third-party re-packaging of sentence-transformers/all-MiniLM-L6-v2)",
                      Path(gt_all_minilm_l6_v2.__file__).parent / "model"))
    except ImportError:
        pass
    for label, p in cands:
        if (p / "model.safetensors").is_file() and (p / "tokenizer.json").is_file():
            info = {"model_name": MODEL_NAME, "origin": label, "directory": str(p),
                    "files_sha256": {n: sha256_file(p / n) for n in ("model.safetensors", "tokenizer.json", "vocab.txt", "config.json",
                                                                   "sentence_bert_config.json", "modules.json") if (p / n).is_file()}}
            return str(p), info
    raise FileNotFoundError(
        f"{MODEL_NAME} model files not found locally. Install `gt-all-minilm-l6-v2` or pass --model-path / set ${MODEL_ENV}. "
        "No download is attempted.")
