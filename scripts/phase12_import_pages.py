#!/usr/bin/env python3
"""Phase 12 (C1) - validate (and optionally import) SAP Help ``pagecontent`` responses that were saved on a machine that CAN reach help.sap.com.

This tool NEVER fetches. It reads JSON files from a folder, matches each to a plan entry by ``data.currentPage.loio`` (the page id recorded in ``data/page_corpus/fetch_plan.json``),
applies exactly the checks of ``page_fetch.check_response`` (envelope OK, not a fallback page, page id and guide id equal the plan entry, non-empty body) and only then, with ``--apply``,
writes the envelope to ``data/page_corpus/fetched/<n>_<numeric id>_<page id>.json`` - the location and name ``page_corpus.py`` already ingests. Anything that does not pass is reported and ignored.

    python scripts/phase12_import_pages.py --from-dir C:\\saved_pages            # dry run: report only
    python scripts/phase12_import_pages.py --from-dir C:\\saved_pages --apply    # copy accepted files

After an import run ``python scripts/page_corpus.py`` and rebuild the page collection (see data/phase12/IMPORT_INSTRUCTIONS.md). Tests that pin the 7-page corpus will then fail on purpose
and must be reviewed, not auto-updated.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import page_fetch as PF  # noqa: E402

PLAN = ROOT / "data" / "page_corpus" / "fetch_plan.json"


def plan_entries(plan_path: Path = PLAN) -> List[Dict[str, Any]]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    return [dict(e, order=n) for n, e in enumerate(plan["pages_to_fetch"], 1)]


def classify_file(path: Path, entries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    rec: Dict[str, Any] = {"file": path.name, "ok": False, "source_id": None, "reasons": []}
    try:
        body = path.read_bytes()
        env = json.loads(body.decode("utf-8-sig"))
    except (OSError, ValueError) as e:
        rec["reasons"].append(f"UNREADABLE_OR_NOT_JSON: {type(e).__name__}")
        return rec
    page = str(((env.get("data") or {}).get("currentPage") or {}).get("loio") or "").lower().removesuffix(".html") if isinstance(env, dict) else ""
    entry = next((e for e in entries if e["page_id"] == page), None)
    if entry is None:
        rec["reasons"].append("PAGE_ID_NOT_IN_PLAN")
        return rec
    rec["source_id"] = entry["source_id"]
    chk = PF.check_response(entry, 200, body)
    rec["ok"], rec["reasons"] = chk["ok"], chk["reasons"]
    rec["entry"] = entry
    return rec


def run(folder: Path, apply: bool = False, plan_path: Path = PLAN, out_dir: Optional[Path] = None) -> Dict[str, Any]:
    entries = plan_entries(plan_path)
    out_dir = out_dir or PF.FETCHED_DIR
    results = [classify_file(p, entries) for p in sorted(folder.glob("*.json"))]
    accepted: Dict[str, Dict[str, Any]] = {}
    for r in results:
        if r["ok"]:
            if r["source_id"] in accepted:
                r["ok"], r["reasons"] = False, ["DUPLICATE_FOR_SAME_PAGE"]
            else:
                accepted[r["source_id"]] = r
    written = []
    if apply:
        out_dir.mkdir(parents=True, exist_ok=True)
        for r in accepted.values():
            e = r["entry"]
            target = out_dir / f"{e['order']}_{e['numeric_deliverable_id']}_{e['page_id']}.json"
            target.write_bytes((folder / r["file"]).read_bytes())
            written.append(str(target))
    missing = [e["source_id"] for e in entries if e["source_id"] not in accepted]
    return {"folder": str(folder), "applied": apply, "files_seen": len(results), "accepted": sorted(accepted), "rejected": [{"file": r["file"], "reasons": r["reasons"]} for r in results if not r["ok"]],
            "written": written, "still_missing": missing}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Validate / import saved SAP Help pagecontent responses (never fetches).")
    ap.add_argument("--from-dir", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    folder = Path(a.from_dir)
    if not folder.is_dir():
        print(f"not a folder: {folder}", file=sys.stderr)
        return 2
    rep = run(folder, apply=a.apply)
    print(json.dumps(rep, indent=1))
    return 0 if not rep["rejected"] else 1


if __name__ == "__main__":
    sys.exit(main())
