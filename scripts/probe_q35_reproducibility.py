#!/usr/bin/env python3
"""Offline Q35 forensics on a temporary copy, never a baseline correction.

Backend flags affect only this short-lived subprocess, not production settings.
An alternate library can be supplied through the subprocess's PYTHONPATH; never
install it over the release venv. Arithmetic-only mode does NOT rerun inference.
"""
import argparse
import contextlib
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def arithmetic(vectors):
    import numpy as np
    q = np.asarray(vectors["query"], dtype="float32")
    v = np.asarray(vectors["card"], dtype="float32")
    q64, v64 = q.astype("float64"), v.astype("float64")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): np.show_config()
    return {"numpy": np.__version__, "float32_dot": float(q @ v),
            "float64_cosine": float(q64 @ v64 / (np.linalg.norm(q64) * np.linalg.norm(v64))),
            "numpy_configuration": buf.getvalue(), "inference_rerun": False}


def worker(store, threads, mkldnn):
    import numpy as np
    import torch
    import chromadb
    from chromadb.config import Settings
    from sentence_transformers import SentenceTransformer
    from m2c_common import resolve_model
    from windows_diagnostic_policy import rounding_evidence
    torch.set_num_threads(threads)
    torch.backends.mkldnn.enabled = mkldnn
    model_dir, model_info = resolve_model()
    model = SentenceTransformer(model_dir, device="cpu")
    questions = json.loads((ROOT / "data/evaluation/card_retrieval_questions.json").read_text(encoding="utf-8"))["questions"]
    index = next(i for i, q in enumerate(questions) if q["question_id"] == "Q35")
    batch = model.encode([q["question"] for q in questions], normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
    single = model.encode([questions[index]["question"]], normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
    client = chromadb.PersistentClient(path=str(store), settings=Settings(anonymized_telemetry=False))
    col = client.get_collection("sap_m2c_card_v1")
    card = col.get(ids=["M2C-22"], include=["embeddings"])["embeddings"][0]
    reference = json.loads((ROOT / "data/evaluation/card_retrieval_results.json").read_text(encoding="utf-8"))
    row = next(r for r in reference["per_question"] if r["question_id"] == "Q35")
    recorded = next(r["cosine_similarity"] for r in row["retrieved_top5"] if r["source_id"] == "M2C-22")
    result = {"platform": sys.platform, "python": sys.version, "torch_threads": threads, "mkldnn": mkldnn,
              "cpu_capability": torch.backends.cpu.get_cpu_capability(), "torch_config": torch.__config__.show(),
              "versions": {n: importlib.metadata.version(n) for n in ("torch", "transformers", "sentence-transformers", "chromadb", "numpy")},
              "model": model_info, "recorded_score": recorded, "historical_raw_score_available": False, "scores": {}}
    for name, query in (("batch", batch[index]), ("single", single[0])):
        got = col.query(query_embeddings=[query.tolist()], n_results=col.count(), include=["distances"])
        ids, distances = got["ids"][0], got["distances"][0]
        score = 1 - distances[ids.index("M2C-22")]
        result["scores"][name] = {"chroma": rounding_evidence(score, recorded), "rank": ids.index("M2C-22") + 1,
                                  "top5": ids[:5], "query_float32_sha256": hashlib.sha256(query.astype("float32").tobytes()).hexdigest(),
                                  "arithmetic": arithmetic({"query": query.tolist(), "card": card.tolist()})}
    result["frozen_vectors_for_arithmetic_only"] = {"query": single[0].tolist(), "card": np.asarray(card, dtype="float32").tolist()}
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--card-store", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--threads", type=int, choices=[1, 2], default=1)
    ap.add_argument("--mkldnn", choices=["on", "off"], default="on")
    ap.add_argument("--store-quiesced", action="store_true")
    ap.add_argument("--arithmetic-only", type=Path)
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    output = args.out.resolve()
    if args.out.exists() or ROOT / "data" in output.parents or (args.card_store and (args.card_store.resolve() == output or args.card_store.resolve() in output.parents)):
        ap.error("Use a new scratch output outside data/")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.arithmetic_only:
        previous = json.loads(args.arithmetic_only.read_text(encoding="utf-8"))
        result = arithmetic(previous["frozen_vectors_for_arithmetic_only"])
        result["input_sha256"] = hashlib.sha256(args.arithmetic_only.read_bytes()).hexdigest()
    elif args.worker:
        if not (args.card_store.name == "store" and args.card_store.parent.name.startswith("SURA-Q35-") and (args.card_store.parent / "OWNED_PROBE").is_file()):
            raise ValueError("Internal worker requires an owned scratch copy")
        result = worker(args.card_store, args.threads, args.mkldnn == "on")
    else:
        if not args.store_quiesced or not args.card_store:
            ap.error("Stop writers; provide --store-quiesced and --card-store")
        from diagnose_windows_verification import hashes
        before = hashes(args.card_store)
        with tempfile.TemporaryDirectory(prefix="SURA-Q35-") as td:
            copy = Path(td) / "store"; shutil.copytree(args.card_store, copy)
            (Path(td) / "OWNED_PROBE").write_bytes(b"private probe copy")
            target = Path(td) / "result.json"
            env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
            proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", "--card-store", str(copy),
                                   "--threads", str(args.threads), "--mkldnn", args.mkldnn, "--out", str(target)],
                                  capture_output=True, text=True, timeout=180, env=env)
            if proc.returncode:
                raise RuntimeError(f"Q35 probe failed: {proc.stderr[-4000:]}")
            result = json.loads(target.read_text(encoding="utf-8"))
        result["source_store_unchanged"] = hashes(args.card_store) == before
        if not result["source_store_unchanged"]:
            raise RuntimeError("Source changed during probe; no result certified")
    args.out.write_bytes((json.dumps(result, indent=2, allow_nan=False) + "\n").encode())
    print(f"Probe saved: {args.out}; no score acceptance rule changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
