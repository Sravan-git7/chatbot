#!/usr/bin/env python3
"""Phase 8A/8B - build the page corpus for the M2C cards from local, verified material (no network).

For every one of the 29 cards this decides, explicitly and with a recorded reason, whether a page record is admitted:

* the Phase 7C identity layer must give an effective guide id and page id (``identified_not_local``, ``corrected_identity`` or
  ``resolved_local_page``). ``conflicting_identity`` (M2C-18) and ``card_identity_only`` (guide unverified) are NOT admitted;
* the content must come from a source whose own identifiers agree with the card's effective identity:
    - a saved SAP Help ``pagecontent`` response whose ``currentPage.loio`` equals the effective page id and whose
      ``deliverable.loio`` equals the effective guide id (``captured_responses/`` or ``data/page_corpus/fetched/``), or
    - the validated local page record that Phase 7C already resolved (M2C-17, legacy local copy, flat text);
* the response must be ``OK`` and not a fallback page, must have a body, and the extraction must pass validation (no error page,
  not empty, not too short).

A URL is never content, raw HTML is never page text, a TOC is never a page and an unresolved identity is never a resolved page.
Phase 7C results are not changed: this module reads them and records its own admission decision next to them.

Output (``data/page_corpus/``): ``pages/<guide_id>/<page_id>.json`` (one record per admitted page), ``manifest.json`` (deterministic: no
timestamps), ``fetch_plan.json`` (what would have to be fetched for the other cards). ``retrieved_at`` is ``null`` for saved responses:
the capture files carry no timestamp, and none is invented.

    python scripts/page_corpus.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import m2c_common as C  # noqa: E402
import m2c_page_identity as pid  # noqa: E402
import page_extract as pe  # noqa: E402

ROOT = C.ROOT
CORPUS_DIR = ROOT / "data" / "page_corpus"
CAPTURE_DIRS = (ROOT / "captured_responses", CORPUS_DIR / "fetched")
SCHEMA_VERSION = "8.1"
_CAPTURE_NAME = re.compile(r"^(?P<n>\d+)_(?P<numeric>\d+)_(?P<page>[0-9a-fA-F]{32})\.json$")

ADMITTED_STATUSES = (pid.IDENTIFIED_NOT_LOCAL, pid.CORRECTED_IDENTITY, pid.RESOLVED_LOCAL_PAGE)

# corpus_status values (every card gets exactly one)
S_INGESTED = "ingested"
S_NOT_INGESTED = "not_ingested_no_local_content"
S_CONFLICT = "excluded_conflicting_identity"
S_IDENTITY_ONLY = "excluded_card_identity_only"
S_REJECTED = "rejected_invalid_content"
S_UNRESOLVED = "excluded_unresolved_identity"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------------------------------------------- captures


def _toc_path(nodes: Sequence[Mapping[str, Any]], page_file: str, trail: Tuple[str, ...] = ()) -> Optional[List[str]]:
    for n in nodes or []:
        here = trail + (str(n.get("t") or ""),)
        if str(n.get("u") or "").lower().split("#")[0] == page_file.lower():
            return list(here)
        sub = _toc_path(n.get("c") or [], page_file, here)
        if sub:
            return sub
    return None


def load_captures(dirs: Sequence[Path] = CAPTURE_DIRS, root: Path = ROOT) -> List[Dict[str, Any]]:
    """Every saved ``pagecontent`` response, parsed. Unreadable / malformed files are listed with a reason, never skipped silently."""
    summary_build: Dict[Tuple[str, str], str] = {}
    sp = root / "captured_responses" / "summary.json"
    if sp.is_file():
        for e in json.loads(sp.read_text(encoding="utf-8")):
            if e.get("deliverable_id") and e.get("file_path") and e.get("buildNo"):
                summary_build[(str(e["deliverable_id"]), str(e["file_path"]).lower().removesuffix(".html"))] = str(e["buildNo"])
    out: List[Dict[str, Any]] = []
    for d in dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            m = _CAPTURE_NAME.match(p.name)
            if not m:
                continue                                    # summary.json, repair reports
            rel = str(p.relative_to(root)).replace("\\", "/")
            rec: Dict[str, Any] = {"file": rel, "file_sha256": sha256_file(p), "numeric_deliverable_id": m["numeric"], "file_page_id": m["page"].lower(),
                                   "build_no": summary_build.get((m["numeric"], m["page"].lower())), "ok": False, "reasons": []}
            try:
                env = json.loads(p.read_text(encoding="utf-8"))
            except ValueError as e:
                rec["reasons"].append(f"MALFORMED_JSON: {e}")
                out.append(rec)
                continue
            data = env.get("data") if isinstance(env, dict) else None
            rec["envelope_status"] = env.get("status") if isinstance(env, dict) else None
            if rec["envelope_status"] != "OK":
                rec["reasons"].append(f"ENVELOPE_STATUS_{rec['envelope_status']}")
            if not isinstance(data, dict):
                rec["reasons"].append("NO_DATA")
                out.append(rec)
                continue
            rec["fallback"] = bool(data.get("fallback"))
            if rec["fallback"]:
                rec["reasons"].append("FALLBACK_PAGE")
            cp, dl = data.get("currentPage") or {}, data.get("deliverable") or {}
            rec.update({"page_id": str(cp.get("loio") or "").lower().removesuffix(".html"), "page_file": cp.get("u"), "page_title_api": cp.get("t"),
                        "guide_id": str(dl.get("loio") or "").lower(), "deliverable_title": dl.get("title"), "version": dl.get("version"),
                        "language": dl.get("languageCode"), "state": dl.get("state"), "body": data.get("body") or "",
                        "breadcrumb": _toc_path(dl.get("fullToc") or [], str(cp.get("u") or ""))})
            if not rec["body"].strip():
                rec["reasons"].append("EMPTY_BODY")
            if rec["page_id"] != rec["file_page_id"]:
                rec["reasons"].append("FILE_NAME_PAGE_ID_DIFFERS_FROM_RESPONSE")
            rec["ok"] = not rec["reasons"]
            out.append(rec)
    return out


# ---------------------------------------------------------------------------------------------------- records


def _card_view(identity: "pid.PageIdentity") -> Dict[str, Any]:
    return {"card_title": identity.card_title, "card_url": identity.card_url, "card_guide_id": identity.card_guide_id, "card_page_id": identity.card_page_id,
            "card_source_status": identity.card_source_status, "card_source_url_status": identity.card_source_url_status,
            "review_flag": bool(identity.card_needs_review)}


def _record(identity: "pid.PageIdentity", ex: Dict[str, Any], acquisition: Dict[str, Any], breadcrumb: Optional[List[str]], validation: Dict[str, Any]) -> Dict[str, Any]:
    text = ex["text"]
    return {
        "schema_version": SCHEMA_VERSION,
        "doc_id": f"{identity.effective_guide_id}/{identity.effective_page_id}",
        "source_ids": [identity.source_id],
        "guide_id": identity.effective_guide_id, "page_id": identity.effective_page_id,
        "source_url": identity.card_url,                       # the card's URL, byte-identical; never rewritten
        "title": ex["title"], "html_title": ex.get("html_title"), "breadcrumb": breadcrumb or ([ex["title"]] if ex["title"] else []),
        "card": _card_view(identity),
        "identity": {"status": identity.resolution_status, "basis": identity.resolution_basis,
                     "effective_guide_id_differs_from_card": identity.effective_guide_id != identity.card_guide_id},
        "acquisition": acquisition, "validation": validation, "structure": ex["stats"],
        "blocks": ex["blocks"], "headings": ex["headings"], "text": text, "text_sha256": sha256_text(text),
    }


def _admit_from_capture(identity: "pid.PageIdentity", caps: Sequence[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    notes: List[Dict[str, Any]] = []
    for c in caps:
        if c.get("page_id") != identity.effective_page_id:
            continue
        if not c["ok"]:
            notes.append({"file": c["file"], "outcome": "rejected", "reasons": c["reasons"]})
            continue
        if c["guide_id"] != identity.effective_guide_id:
            notes.append({"file": c["file"], "outcome": "rejected", "reasons": [f"RESPONSE_GUIDE_{c['guide_id']}_DIFFERS_FROM_EFFECTIVE_GUIDE_{identity.effective_guide_id}"]})
            continue
        ex = pe.extract_html(c["body"])
        val = pe.validate_extraction(ex)
        if not val["ok"]:
            notes.append({"file": c["file"], "outcome": "rejected", "reasons": val["reasons"]})
            continue
        acq = {"type": "saved_sap_help_pagecontent_response", "file": c["file"], "file_sha256": c["file_sha256"], "envelope_status": c["envelope_status"],
               "fallback_page": False, "http_status": None, "http_status_note": "the saved response records the API envelope status only; the HTTP status was not saved",
               "retrieved_at": None, "retrieved_at_note": "the capture file carries no timestamp; none is invented",
               "numeric_deliverable_id": c["numeric_deliverable_id"], "build_no": c["build_no"], "language": c["language"], "version": c["version"],
               "deliverable_title": c["deliverable_title"], "body_sha256": sha256_text(c["body"]), "html_chars": len(c["body"]), "response_state": c["state"]}
        notes.append({"file": c["file"], "outcome": "admitted", "reasons": []})
        return _record(identity, ex, acq, c["breadcrumb"], val), notes
    return None, notes


def _admit_from_local_record(identity: "pid.PageIdentity", root: Path) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    if not (identity.local_page_available and identity.local_page_path):
        return None, []
    check = pid.validate_local_page(identity, root)
    if not check.get("ok"):
        return None, [{"file": identity.local_page_path, "outcome": "rejected", "reasons": ["LOCAL_RECORD_FAILED_7C_VALIDATION", str(check)[:200]]}]
    path = root / identity.local_page_path
    raw = json.loads(path.read_text(encoding="utf-8"))
    ex = pe.extract_flat_text(raw.get("text") or "", raw.get("page_title"))
    val = pe.validate_extraction(ex)
    if not val["ok"]:
        return None, [{"file": identity.local_page_path, "outcome": "rejected", "reasons": val["reasons"]}]
    acq = {"type": "legacy_local_copy", "file": identity.local_page_path, "file_sha256": sha256_file(path), "envelope_status": raw.get("status"),
           "fallback_page": False, "http_status": None, "http_status_note": "legacy local copy of a page saved by the earlier project; no HTTP metadata",
           "retrieved_at": raw.get("retrieved_at"), "retrieved_at_note": "not recorded for the legacy local copy",
           "numeric_deliverable_id": raw.get("numeric_deliverable_id"), "build_no": raw.get("build_no"), "language": None, "version": None,
           "deliverable_title": None, "record_source_type": raw.get("source_type"), "record_fetched_via": raw.get("fetched_via"),
           "structure_note": "flat cleaned text without markup: headings are detected heuristically"}
    return _record(identity, ex, acq, [raw.get("page_title")] if raw.get("page_title") else None, val), [{"file": identity.local_page_path, "outcome": "admitted", "reasons": []}]


def build_corpus(root: Path = ROOT, out_dir: Path = CORPUS_DIR, write: bool = True, ctx: Optional["pid.IdentityContext"] = None,
                 capture_dirs: Optional[Sequence[Path]] = None) -> Dict[str, Any]:
    ctx = ctx or pid.IdentityContext.from_root(root)
    caps = load_captures(capture_dirs or (root / "captured_responses", out_dir / "fetched"), root)
    identities = pid.resolve_all(ctx)
    entries: List[Dict[str, Any]] = []
    records: Dict[str, Dict[str, Any]] = {}
    plan: List[Dict[str, Any]] = []
    pairs = {c["guide_id"]: (c["numeric_deliverable_id"], c["build_no"]) for c in caps if c["ok"] and c.get("guide_id")}
    used_files = set()
    for ident in sorted(identities, key=lambda i: pid._num(i.source_id)):
        e: Dict[str, Any] = {"source_id": ident.source_id, "title": ident.card_title, "identity_status_7c": ident.resolution_status,
                             "review_flag": bool(ident.card_needs_review), "card_url": ident.card_url,
                             "effective_guide_id": ident.effective_guide_id, "effective_page_id": ident.effective_page_id}
        if ident.resolution_status == pid.CONFLICTING_IDENTITY:
            e.update(corpus_status=S_CONFLICT, reason="conflicting identity: no effective page is chosen, so no page content is admitted (a capture of another guide exists and is not used)")
        elif ident.resolution_status == pid.CARD_IDENTITY_ONLY:
            e.update(corpus_status=S_IDENTITY_ONLY, reason="the card's guide is not verified by any saved response or TOC; nothing may be admitted for it")
        elif ident.resolution_status not in ADMITTED_STATUSES:
            e.update(corpus_status=S_UNRESOLVED, reason=f"identity status {ident.resolution_status}")
        else:
            rec, notes = (None, [])
            if ident.resolution_status == pid.RESOLVED_LOCAL_PAGE:
                rec, notes = _admit_from_local_record(ident, root)
            if rec is None:
                rec, n2 = _admit_from_capture(ident, caps)
                notes += n2
            e["source_checks"] = notes
            if rec is not None:
                records[rec["doc_id"]] = rec
                e.update(corpus_status=S_INGESTED, doc_id=rec["doc_id"], record=f"pages/{rec['guide_id']}/{rec['page_id']}.json", text_sha256=rec["text_sha256"],
                         text_chars=rec["validation"]["text_chars"], acquisition_type=rec["acquisition"]["type"])
                used_files.add(rec["acquisition"]["file"])
            elif any(n["outcome"] == "rejected" for n in notes):
                e.update(corpus_status=S_REJECTED, reason="a candidate source exists but was rejected: " + "; ".join(sorted({r for n in notes for r in n["reasons"]})))
            else:
                num, build = pairs.get(ident.effective_guide_id or "", (None, None))
                e.update(corpus_status=S_NOT_INGESTED, reason="no local content for this page; it was not fetched")
                plan.append({"source_id": ident.source_id, "guide_id": ident.effective_guide_id, "page_id": ident.effective_page_id,
                             "numeric_deliverable_id": num, "build_no": build,
                             "fetchable_with_recorded_ids": bool(num and build),
                             "blocker": None if (num and build) else "numeric deliverable id / build number not recorded for this guide (never guessed)",
                             "request": (f"GET https://help.sap.com/http.svc/pagecontent?deliverableInfo=1&deliverable_id={num}&buildNo={build}&file_path={ident.effective_page_id}.html"
                                         if (num and build) else None)})
        entries.append(e)
    unused = [{"file": c["file"], "guide_id": c.get("guide_id"), "page_id": c.get("page_id"), "reasons": c["reasons"], "numeric_deliverable_id": c["numeric_deliverable_id"],
               "reason_not_used": ("capture is invalid: " + ", ".join(c["reasons"])) if not c["ok"] else
               "no admitted card has this page as its effective page in this guide (e.g. the response belongs to a different guide than the conflicting card)"}
              for c in caps if c["file"] not in used_files]
    counts: Dict[str, int] = {}
    for e in entries:
        counts[e["corpus_status"]] = counts.get(e["corpus_status"], 0) + 1
    corpus_hash = sha256_text("\n".join(f"{d} {records[d]['text_sha256']}" for d in sorted(records)))
    manifest = {
        "schema_version": SCHEMA_VERSION, "kind": "m2c_page_corpus_manifest",
        "scope": {"network_used": False, "content_sources": ["captured_responses/*.json (saved SAP Help pagecontent responses)", "Phase 7C resolved local page record (M2C-17)"],
                  "legacy_corpus_modified": False, "data_sap_help_modified": False,
                  "note": "page records are written under data/page_corpus/, not data/sap_help/: the Phase 7A join reads data/sap_help/pages and its results are pinned"},
        "totals": {"cards": len(entries), "pages_ingested": len(records), "guides": len({r["guide_id"] for r in records.values()}),
                   "cards_not_ingested": len(entries) - len(records), "status_counts": dict(sorted(counts.items())),
                   "captures_found": len(caps), "captures_unused": len(unused)},
        "corpus_sha256": corpus_hash, "cards": entries, "unused_captures": unused,
        "inputs": {"card_identity_cards_sha256": sha256_text(canonical_json([i.to_dict() for i in identities])),
                   "captures": {c["file"]: c["file_sha256"] for c in caps}},
    }
    result = {"manifest": manifest, "records": records, "fetch_plan": {"schema_version": SCHEMA_VERSION, "pages_to_fetch": plan,
              "network_default": "off", "robots_note": "help.sap.com/robots.txt has Disallow: / for generic agents (saved copy audit_out/robots.txt, 2025-10-17); fetching is a deliberate human decision (scripts/page_fetch.py --allow-network)",
              "fetchable_with_recorded_ids": sum(1 for p in plan if p["fetchable_with_recorded_ids"]), "not_fetchable_without_new_ids": sum(1 for p in plan if not p["fetchable_with_recorded_ids"])}}
    if write:
        write_corpus(result, out_dir)
    return result


def write_corpus(result: Mapping[str, Any], out_dir: Path = CORPUS_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = out_dir / "pages"
    keep = set()
    for rec in result["records"].values():
        p = pages / rec["guide_id"] / f"{rec['page_id']}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(canonical_json(rec), encoding="utf-8")
        keep.add(p)
    if pages.is_dir():                                           # records of pages no longer admitted are removed (derived output only)
        for old in pages.glob("*/*.json"):
            if old not in keep:
                old.unlink()
    (out_dir / "manifest.json").write_text(canonical_json(result["manifest"]), encoding="utf-8")
    (out_dir / "fetch_plan.json").write_text(canonical_json(result["fetch_plan"]), encoding="utf-8")


def load_records(out_dir: Path = CORPUS_DIR) -> List[Dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((out_dir / "pages").glob("*/*.json"))]


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Build the page corpus manifest and records from local verified material (no network).")
    ap.add_argument("--out-dir", default=str(CORPUS_DIR))
    a = ap.parse_args(argv)
    res = build_corpus(out_dir=Path(a.out_dir))
    t = res["manifest"]["totals"]
    print(f"pages ingested: {t['pages_ingested']} in {t['guides']} guides; cards not ingested: {t['cards_not_ingested']}; status counts: {t['status_counts']}")
    print(f"corpus_sha256: {res['manifest']['corpus_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
