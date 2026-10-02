#!/usr/bin/env python3
"""Phase 12 (C1) - exact corpus status for the 29 cards + the import manifest for the part that cannot be fetched here.

Everything is derived (nothing hand-edited) from: ``data/retrieval_units.json`` (card title/category/official URL), ``data/m2c_page_identity.json`` (Phase 7C identity),
``data/page_corpus/manifest.json`` (Phase 8 admission), ``data/page_corpus/fetch_plan.json`` (recorded ids), the Phase 9 and Phase 12 fetch logs, and (optional) the page store for chunk counts.
Identity vocabulary of Phase 7C is preserved (``resolved_local_page``, ``identified_not_local``, ``corrected_identity``, ``card_identity_only``, ``conflicting_identity``); a card without an
effective guide/page id is additionally flagged ``unresolved``. Nothing under Phase 7/8/9 is written.

    python scripts/phase12_corpus_status.py [--probe]       # --probe runs the DNS / TCP / TLS probe (sockets only; no HTTP request)
"""
from __future__ import annotations

import argparse
import json
import socket
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT_DIR = ROOT / "data" / "phase12"
PROBE_HOSTS = ("help.sap.com", "ollama.com", "registry.ollama.ai", "huggingface.co", "github.com", "pypi.org")


def _load(path: str) -> Any:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def probe_host(host: str, timeout: float = 8.0) -> Dict[str, Any]:
    """DNS -> TCP:443 -> TLS handshake. Reports the first stage that fails (no HTTP request is made, nothing is bypassed)."""
    rec: Dict[str, Any] = {"host": host, "dns": None, "tcp_443": None, "tls": None, "failed_stage": None, "error": None}
    try:
        addrs = sorted({a[4][0] for a in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)})
        rec["dns"] = addrs[:3]
    except Exception as e:                                                  # noqa: BLE001
        rec.update(failed_stage="dns", error=f"{type(e).__name__}: {e}"[:200])
        return rec
    try:
        raw = socket.create_connection((host, 443), timeout=timeout)
        rec["tcp_443"] = True
    except Exception as e:                                                  # noqa: BLE001
        rec.update(tcp_443=False, failed_stage="tcp", error=f"{type(e).__name__}: {e}"[:200])
        return rec
    try:
        with raw:
            ctx = ssl.create_default_context()
            with ctx.wrap_socket(raw, server_hostname=host) as tls:
                rec["tls"] = {"ok": True, "version": tls.version()}
    except Exception as e:                                                  # noqa: BLE001
        rec.update(tls={"ok": False}, failed_stage="tls_handshake", error=f"{type(e).__name__}: {e}"[:200])
    return rec


def chunk_counts() -> Optional[Dict[str, int]]:
    try:
        import build_page_collection as BP
        import page_retriever as PR
        embed, _ = BP.load_embedder()
        r = PR.PageRetriever.from_store(embed=embed)
        out: Dict[str, int] = {}
        for doc in _load("data/page_collection_manifest.json")["page_doc_ids"]:
            g, p = doc.split("/")
            out[doc] = len(r.page_chunks(g, p))
        return out
    except Exception:                                                       # noqa: BLE001 - the page store is optional for this report
        return None


def last_fetch_attempt() -> Optional[Dict[str, Any]]:
    path = OUT_DIR / "fetch_attempt_log.json"
    if not path.is_file():
        return None
    log = json.loads(path.read_text(encoding="utf-8"))[-1]
    return {"started_at": log.get("started_at"), "robots": log.get("robots"), "stopped_reason": log.get("stopped_reason"), "saved": len(log.get("saved") or []),
            "attempted": [{"source_id": a["source_id"], "ok": a["ok"], "http_status": a["http_status"], "error": (a.get("error") or "")[:160], "reasons": a.get("reasons")} for a in log.get("attempts", [])]}


def build(probe: bool = False, with_chunks: bool = True) -> Dict[str, Any]:
    units = {u["source_id"]: u for u in (lambda d: d["units"] if isinstance(d, dict) else d)(_load("data/retrieval_units.json"))}
    ident = {c["source_id"]: c for c in _load("data/m2c_page_identity.json")["cards"]}
    corpus = {c["source_id"]: c for c in _load("data/page_corpus/manifest.json")["cards"]}
    plan = {e["source_id"]: e for e in _load("data/page_corpus/fetch_plan.json")["pages_to_fetch"]}
    counts = chunk_counts() if with_chunks else None
    cards: List[Dict[str, Any]] = []
    for sid in sorted(units):
        u, i, c = units[sid], ident[sid], corpus[sid]
        ingested = c["corpus_status"] == "ingested"
        has_ids = bool(c.get("effective_guide_id") and c.get("effective_page_id"))
        n_chunks = None if counts is None or not c.get("doc_id") else counts.get(c["doc_id"])
        if ingested:
            need = "none (page present)"
        elif sid in plan:
            need = "official pagecontent response (recorded ids; see import_manifest.json)"
        else:
            need = "NOT fetchable: " + ("identity conflict (M2C-18 stays a protected conflict)" if i["resolution_status"] == "conflicting_identity" else "no verified guide/page id for this card (card_identity_only)")
        cards.append({
            "source_id": sid, "title": u["title"], "category": u["category"], "official_card_url": u["source_url"], "card_url_status": u.get("source_url_status"),
            "identity_status": i["resolution_status"], "unresolved": not has_ids, "review_flag": bool(c.get("review_flag")),
            "effective_guide_id": c.get("effective_guide_id"), "effective_page_id": c.get("effective_page_id"),
            "corpus_status": c["corpus_status"], "local_page": ingested, "page_chunks": n_chunks, "answerable_content": bool(ingested and (n_chunks or 0) > 0) if counts is not None else ingested,
            "acquisition": c.get("acquisition_type"), "needed_to_complete": need, "fetchable_with_recorded_ids": sid in plan})
    by_id: Dict[str, int] = {}
    for c in cards:
        by_id[c["identity_status"]] = by_id.get(c["identity_status"], 0) + 1
    out: Dict[str, Any] = {
        "schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "totals": {"cards": len(cards), "local_pages": sum(c["local_page"] for c in cards), "answerable_content": sum(c["answerable_content"] for c in cards),
                   "identified_not_local_without_page": sum(1 for c in cards if c["fetchable_with_recorded_ids"]), "not_fetchable": sum(1 for c in cards if not c["local_page"] and not c["fetchable_with_recorded_ids"]),
                   "identity_status_counts": by_id},
        "corpus_complete": all(c["local_page"] for c in cards),
        "statement": "Corpus is NOT complete: 7 of 29 cards have a local page. The 18 fetchable pages are BLOCKED by the network (see fetch_attempt); the 4 others cannot be fetched without a new verified identity.",
        "fetch_attempt": last_fetch_attempt(), "cards": cards}
    if probe:
        out["network_probe"] = [probe_host(h) for h in PROBE_HOSTS]
    return out


def import_manifest() -> Dict[str, Any]:
    plan = _load("data/page_corpus/fetch_plan.json")
    units = {u["source_id"]: u for u in (lambda d: d["units"] if isinstance(d, dict) else d)(_load("data/retrieval_units.json"))}
    items = []
    for n, e in enumerate(plan["pages_to_fetch"], 1):
        url = (f"https://help.sap.com/http.svc/pagecontent?deliverableInfo=1&deliverable_id={e['numeric_deliverable_id']}"
               f"&buildNo={e['build_no']}&file_path={e['page_id']}.html")
        items.append({"order": n, "source_id": e["source_id"], "title": units[e["source_id"]]["title"], "guide_id": e["guide_id"], "page_id": e["page_id"], "request_url": url,
                      "save_as": f"data/page_corpus/fetched/{n}_{e['numeric_deliverable_id']}_{e['page_id']}.json",
                      "accept_if": {"envelope.status": "OK", "data.fallback": "absent/false", "data.currentPage.loio": e["page_id"], "data.deliverable.loio": e["guide_id"], "data.body": "non-empty"}})
    return {"schema_version": 1, "purpose": "pages that must be copied from an environment that can reach help.sap.com; saved by a human decision (robots.txt of help.sap.com was last saved as Disallow: / for generic agents)",
            "count": len(items), "validator": "python scripts/phase12_import_pages.py --from-dir <folder>", "items": items}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--no-chunks", action="store_true")
    a = ap.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    status = build(probe=a.probe, with_chunks=not a.no_chunks)
    (OUT_DIR / "corpus_status.json").write_text(json.dumps(status, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT_DIR / "import_manifest.json").write_text(json.dumps(import_manifest(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    t = status["totals"]
    print(f"cards={t['cards']} local_pages={t['local_pages']} fetchable_blocked={t['identified_not_local_without_page']} not_fetchable={t['not_fetchable']} complete={status['corpus_complete']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
