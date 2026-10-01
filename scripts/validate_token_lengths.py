#!/usr/bin/env python3
"""Phase 4 / stage 1: measure REAL token counts of the retrieval units with the tokenizer of the embedding model.

Loads the local tokenizer files of all-MiniLM-L6-v2 (no download). Counts include the model's special tokens ([CLS], [SEP]),
which is the length the model actually receives. Nothing is truncated: counting uses `truncation=False`.

Exit code 0: every `embedding_text` fits the model's maximum input length.  Exit code 3: at least one does not; the
embedding stage must not run (the model is NOT changed and the text is NOT truncated to hide the problem).
`full_text` is measured and reported too; it is not embedded, so it does not decide the exit code.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m2c_common import UNITS_PATH, TOKEN_STATS_PATH, MODEL_NAME, resolve_model, sha256_file  # noqa: E402


def summarise(v: Sequence[int]) -> Dict[str, Any]:
    return {"min": min(v), "median": float(statistics.median(v)), "mean": round(sum(v) / len(v), 1), "max": max(v)}


def measure(units: Sequence[Dict[str, Any]], model_dir: str) -> Dict[str, Any]:
    from transformers import AutoTokenizer  # local files only
    tok = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    st = json.loads((Path(model_dir) / "sentence_bert_config.json").read_text(encoding="utf-8"))
    cfg = json.loads((Path(model_dir) / "config.json").read_text(encoding="utf-8"))
    max_len = int(st["max_seq_length"])

    def count(text: str) -> int:
        return len(tok(text, add_special_tokens=True, truncation=False)["input_ids"])

    rows: List[Dict[str, Any]] = []
    for u in units:
        ft, et = count(u["full_text"]), count(u["embedding_text"])
        rows.append({"source_id": u["source_id"], "source_number": u["source_number"], "full_text_tokens": ft,
                     "embedding_text_tokens": et, "embedding_text_chars": len(u["embedding_text"]),
                     "full_text_truncated_by_model": ft > max_len, "embedding_text_truncated_by_model": et > max_len,
                     "embedding_text_headroom": max_len - et})
    over_e = [r["source_id"] for r in rows if r["embedding_text_truncated_by_model"]]
    over_f = [r["source_id"] for r in rows if r["full_text_truncated_by_model"]]
    return {
        "tokenizer": {"class": type(tok).__name__, "vocab_size": tok.vocab_size, "model_name": MODEL_NAME,
                      "model_max_seq_length_sentence_transformers": max_len,
                      "position_embeddings_limit": cfg.get("max_position_embeddings"),
                      "special_tokens_counted": True, "truncation_applied_when_counting": False},
        "full_text": summarise([r["full_text_tokens"] for r in rows]),
        "embedding_text": summarise([r["embedding_text_tokens"] for r in rows]),
        "max_seq_length": max_len,
        "embedding_text_over_limit": over_e,
        "full_text_over_limit": over_f,
        "sources": rows,
        "verdict": "PASS: every embedding_text fits the model input length" if not over_e else
                   f"STOP: {len(over_e)} embedding_text value(s) exceed {max_len} tokens: {over_e}",
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--units", default=str(UNITS_PATH))
    ap.add_argument("--out", default=str(TOKEN_STATS_PATH))
    ap.add_argument("--model-path", default=None)
    a = ap.parse_args(argv)
    model_dir, info = resolve_model(a.model_path)
    payload = json.loads(Path(a.units).read_text(encoding="utf-8"))
    res = measure(payload["units"], model_dir)
    res["model"] = info
    res["units_file_sha256"] = sha256_file(Path(a.units))
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"tokenizer: {res['tokenizer']['class']}  model max input: {res['max_seq_length']} tokens")
    for k in ("full_text", "embedding_text"):
        s = res[k]
        print(f"{k:15s} min={s['min']} median={s['median']} mean={s['mean']} max={s['max']}")
    print(f"full_text over limit: {res['full_text_over_limit']}")
    print(res["verdict"])
    return 0 if not res["embedding_text_over_limit"] else 3


if __name__ == "__main__":
    sys.exit(main())
