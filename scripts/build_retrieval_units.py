#!/usr/bin/env python3
"""Phase 4 / stage 2: build the 29 card-level retrieval units (strategy A) from `data/source_corpus.json`.

Offline, deterministic, no LLM, no embeddings. Two representations are kept for every card:

  full_text       the complete normalised card text, byte-for-byte the corpus `content` (provenance, citation, display, audit)
  embedding_text  the card text with ONLY the boilerplate sections `library_use` and `copyright_note` removed
                  (heading line + body of each); everything else (reference line, title, category, What it covers,
                  Meter-to-Cash relevance, Authoritative SAP Help source + URL) is kept verbatim.

`embedding_text` is built from existing corpus offsets only: the kept sections' spans, joined with the exact separator
whitespace that stood in front of each kept section in the source. Nothing is rewritten or generated. The boilerplate
keys are a fixed, documented rule; the script refuses to run if those sections are not identical in every card
(otherwise they would not be boilerplate) or if an excluded section contains anything that is not whitespace-separated
from the kept text.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m2c_common import CORPUS_PATH, UNITS_PATH, ROOT, sha256_file, sha256_text  # noqa: E402

SCHEMA_VERSION = 1
BOILERPLATE_SECTION_KEYS = ("library_use", "copyright_note")
RULE = ("embedding_text = full_text minus the heading line and body of the sections `library_use` and `copyright_note`; "
        "all other sections are kept verbatim in their original order with their original separator whitespace; "
        "no text is rewritten, added or summarised; leading/trailing whitespace is stripped.")


def section_span(doc: Dict[str, Any], sec: Dict[str, Any]):
    """(start, end) of a section INCLUDING its heading line (same rule as scripts/build_chunk_candidates.py)."""
    start, end, content = sec["char_start"], sec["char_end"], doc["content"]
    if sec.get("heading"):
        head = sec["heading"] + "\n"
        if content[start - len(head):start] != head:
            raise ValueError(f"{sec['section_id']}: heading not found in front of the section body")
        start -= len(head)
    if content[sec["char_start"]:end] != sec["text"]:
        raise ValueError(f"{sec['section_id']}: offsets do not address the section text")
    return start, end


def check_boilerplate_rule(docs: Sequence[Dict[str, Any]]) -> None:
    for key in BOILERPLATE_SECTION_KEYS:
        texts = {s["text"] for d in docs for s in d["sections"] if s["key"] == key}
        n = sum(1 for d in docs for s in d["sections"] if s["key"] == key)
        if n != len(docs) or len(texts) != 1:
            raise ValueError(f"section `{key}` is not identical boilerplate in all {len(docs)} cards "
                             f"({n} sections, {len(texts)} distinct texts); refusing to exclude it")


def build_embedding_text(doc: Dict[str, Any]) -> Dict[str, Any]:
    content = doc["content"]
    secs = sorted(doc["sections"], key=lambda s: s["order"])
    kept = [s for s in secs if s["key"] not in BOILERPLATE_SECTION_KEYS]
    dropped = [s for s in secs if s["key"] in BOILERPLATE_SECTION_KEYS]
    if not kept:
        raise ValueError(f"{doc['source_id']}: nothing left after excluding boilerplate")
    parts: List[str] = []
    prev_end: Optional[int] = None
    for s in kept:
        a, b = section_span(doc, s)
        if prev_end is not None:
            gap = content[prev_end:a]
            if gap.strip():
                raise ValueError(f"{doc['source_id']}: non-whitespace between kept sections (an excluded section sits in the middle)")
            parts.append(gap)
        parts.append(content[a:b])
        prev_end = b
    text = "".join(parts).strip()
    excluded = []
    for s in dropped:
        a, b = section_span(doc, s)
        excluded.append({"section_id": s["section_id"], "key": s["key"], "char_start": a, "char_end": b})
    return {"text": text, "excluded": excluded, "kept_section_ids": [s["section_id"] for s in kept]}


def build_units(corpus: Dict[str, Any]) -> List[Dict[str, Any]]:
    docs = sorted(corpus["documents"], key=lambda d: d["source_number"])
    check_boilerplate_rule(docs)
    units = []
    for d in docs:
        if d["extraction_status"] != "extracted" or not d["content"].strip():
            raise ValueError(f"{d['source_id']}: not extracted / empty; cannot build a retrieval unit")
        emb = build_embedding_text(d)
        prov = d["provenance"]
        units.append({
            "retrieval_unit_id": d["source_id"],
            "source_id": d["source_id"],
            "source_number": d["source_number"],
            "filename": d["filename"],
            "title": d["title"],
            "category": d["category"],
            "embedding_text": emb["text"],
            "full_text": d["content"],
            "source_status": d["status"],
            "source_url": d["authoritative_source"],
            "source_url_status": d["review"]["source_url_status"],
            "sha256": d["sha256"],
            "has_source_correction": d["source_correction"] is not None,
            "source_correction": d["source_correction"],
            "review_reasons": d["review"]["review_reasons"],
            "citation": prov["citation"],
            "provenance": {
                "corpus_document": f"data/source_corpus.json#{d['source_id']}",
                "pdf_filename": d["filename"],
                "pdf_sha256": d["sha256"],
                "page_start": min(s["page_start"] for s in d["sections"]),
                "page_end": max(s["page_end"] for s in d["sections"]),
                "page_count": d["page_count"],
            },
            "embedding_text_spec": {
                "kept_section_ids": emb["kept_section_ids"],
                "excluded_sections": emb["excluded"],
                "full_text_char_range": [0, len(d["content"])],
            },
            "embedding_text_sha256": sha256_text(emb["text"]),
            "full_text_sha256": sha256_text(d["content"]),
            "char_counts": {"full_text": len(d["content"]), "embedding_text": len(emb["text"])},
        })
    return units


def build_payload(corpus: Dict[str, Any], corpus_file_sha: str) -> Dict[str, Any]:
    units = build_units(corpus)
    fr = sum(u["char_counts"]["full_text"] for u in units)
    er = sum(u["char_counts"]["embedding_text"] for u in units)
    return {
        "schema_version": SCHEMA_VERSION,
        "strategy": "whole_document (Strategy A of data/chunk_candidates)",
        "embedding_text_rule": RULE,
        "boilerplate_section_keys": list(BOILERPLATE_SECTION_KEYS),
        "source_corpus": {"path": "data/source_corpus.json", "file_sha256": corpus_file_sha,
                          "content_fingerprint": corpus["content_fingerprint"], "manifest_sha256": corpus["manifest_sha256"]},
        "unit_count": len(units),
        "stats": {"full_text_chars_total": fr, "embedding_text_chars_total": er,
                  "excluded_chars_total_incl_separators": fr - er},
        "units": units,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", default=str(CORPUS_PATH))
    ap.add_argument("--out", default=str(UNITS_PATH))
    a = ap.parse_args(argv)
    corpus = json.loads(Path(a.corpus).read_text(encoding="utf-8"))
    payload = build_payload(corpus, sha256_file(Path(a.corpus)))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    u = payload["units"]
    print(f"retrieval units: {len(u)}   full_text chars {payload['stats']['full_text_chars_total']}   "
          f"embedding_text chars {payload['stats']['embedding_text_chars_total']}   wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
