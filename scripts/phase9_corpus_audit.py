#!/usr/bin/env python3
"""Phase 9A - 29-card corpus status table (read-only over Phase 7C identity, the Phase 8 page corpus and the card units).

Writes ``data/phase9/corpus_status.json`` and ``data/phase9/corpus_status.md``. Nothing is fetched here and no identity is re-derived or
rewritten: the 7C identity statuses and review flags are copied as recorded, the corpus status is copied from the Phase 8 corpus manifest, and
``fetched_in_phase9`` is taken from the Phase 9 fetch attempt log (``data/phase9/fetch_attempt_log.json``; 0 pages saved => False for all).

    python scripts/phase9_corpus_audit.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
import page_corpus as PC  # noqa: E402

ROOT = PC.ROOT
OUT_JSON = ROOT / "data" / "phase9" / "corpus_status.json"
OUT_MD = ROOT / "data" / "phase9" / "corpus_status.md"
FETCH_LOG = ROOT / "data" / "phase9" / "fetch_attempt_log.json"


def load(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def verification_for(status: str, rec: Dict[str, Any], mcard: Dict[str, Any]) -> str:
    if status == "ingested":
        if mcard.get("acquisition_type") == "saved_sap_help_pagecontent_response":
            return "page_verified_from_saved_official_response (response page loio and guide loio match the card identity; admission checks passed)"
        return "page_text_from_local_flat_record (identity resolved_local_page in 7C; heading structure is a heuristic)"
    if status == "not_ingested_no_local_content":
        return "identity_only_no_page_content (guide/page known from saved TOC membership; the page body has never been seen locally)"
    if status == "excluded_card_identity_only":
        return "unverified (the card's guide is not verified by any saved response or TOC)"
    if status == "excluded_conflicting_identity":
        return "conflicting_identity (protected; never resolved)"
    return "unknown"


def main() -> int:
    units = {u["source_id"]: u for u in load(ROOT / "data" / "retrieval_units.json")["units"]}
    ident = {c["source_id"]: c for c in load(ROOT / "data" / "m2c_page_identity.json")["cards"]}
    manifest = load(PC.CORPUS_DIR / "manifest.json")
    mcards = {c["source_id"]: c for c in manifest["cards"]}
    recs = {r["source_ids"][0]: r for r in PC.load_records()}
    attempts = load(FETCH_LOG) if FETCH_LOG.is_file() else []
    saved_ids = sorted({s for run in attempts for s in run.get("saved", [])})
    tried = sorted({a["source_id"] for run in attempts for a in run.get("attempts", [])})
    rows: List[Dict[str, Any]] = []
    for sid in sorted(units):
        u, i, m = units[sid], ident[sid], mcards[sid]
        rec = recs.get(sid)
        status = m["corpus_status"]
        rows.append({
            "card_id": sid, "title": u["title"], "category": u["category"], "source_url": i["card_url"],
            "identity_status_7c": i["resolution_status"], "card_guide_id": i["card_guide_id"], "card_page_id": i["card_page_id"],
            "effective_guide_id": i["effective_guide_id"], "effective_page_id": i["effective_page_id"],
            "page_url": rec["source_url"] if rec else None,
            "local_page_available": bool(rec), "corpus_status": status,
            "page_provenance": ({"acquisition_type": m.get("acquisition_type"), "source": (m.get("source_checks") or [{}])[0].get("file") if m.get("source_checks") else rec["acquisition"].get("file")} if rec else None),
            "page_hash_sha256": rec["text_sha256"] if rec else None, "page_text_chars": m.get("text_chars"),
            "review_flag": bool(i["card_needs_review"]), "card_source_status": i["card_source_status"], "card_source_url_status": i["card_source_url_status"],
            "corrected_identity": i["resolution_status"] == "corrected_identity",
            "previously_present_in_phase8_corpus": bool(rec), "fetched_in_phase9": sid in saved_ids, "fetch_attempted_in_phase9": sid in tried,
            "verification_status": verification_for(status, rec or {}, m),
        })
    summary = {
        "cards": len(rows), "pages_available": sum(1 for r in rows if r["local_page_available"]), "pages_missing": sum(1 for r in rows if not r["local_page_available"]),
        "by_corpus_status": {k: sum(1 for r in rows if r["corpus_status"] == k) for k in sorted({r["corpus_status"] for r in rows})},
        "by_identity_status_7c": {k: sum(1 for r in rows if r["identity_status_7c"] == k) for k in sorted({r["identity_status_7c"] for r in rows})},
        "review_flag_cards": [r["card_id"] for r in rows if r["review_flag"]],
        "fetched_in_phase9": saved_ids, "fetch_attempts_in_phase9": len(tried), "corpus_sha256": manifest["corpus_sha256"],
        "pending_external_retrieval": [r["card_id"] for r in rows if r["corpus_status"] == "not_ingested_no_local_content"],
        "protected_unresolved": [r["card_id"] for r in rows if r["corpus_status"].startswith("excluded")],
    }
    payload = {"schema_version": 1, "kind": "phase9_corpus_status", "note": "identity statuses are the Phase 7C statuses, copied as recorded; 'identified_not_local' for a card whose page is in the Phase 8 corpus refers to data/sap_help only",
               "summary": summary, "cards": rows}
    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    lines = ["# Phase 9 corpus status (29 cards)", "", f"corpus sha256 `{manifest['corpus_sha256'][:16]}...` | pages available {summary['pages_available']} | missing {summary['pages_missing']} | fetched in Phase 9: {len(saved_ids)}", "",
             "| card | title | identity (7C) | corpus status | page | review | page hash | verification |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['card_id']} | {r['title']} | {r['identity_status_7c']} | {r['corpus_status']} | {'yes' if r['local_page_available'] else 'no'} | {'FLAG' if r['review_flag'] else ''} | "
                     f"{(r['page_hash_sha256'] or '-')[:10]} | {r['verification_status'].split(' (')[0]} |")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
