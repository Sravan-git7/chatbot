#!/usr/bin/env python3
"""Repair malformed captured SAP pagecontent responses, OFFLINE (no network).

    python scripts/repair_captured_response.py [--dir captured_responses] [FILE ...] [--dry-run]

Only top-level ``*.json`` files that are NOT valid JSON are touched. The original bytes are kept in
``<dir>/_malformed_originals/<name>`` (+ ``<name>.repair.json`` provenance); the repaired, valid
JSON replaces ``<name>``. The HTML ``data.body`` is preserved exactly (see sap_resolver/repair.py).
Exit: 0 all fine | 1 a file could not be repaired safely (nothing is written for it).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sap_resolver.intake import strip_bom  # noqa: E402
from sap_resolver.repair import RepairError, repair_pagecontent_text  # noqa: E402

NAME = re.compile(r"^(?P<n>\d+)_(?P<numeric>\d+)_(?P<page>[0-9a-f]{32})\.json$")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--dir", default="captured_responses")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    folder = Path(a.dir)
    files = [Path(f) for f in a.files] or sorted(p for p in folder.glob("*.json") if p.name != "summary.json")
    rc = 0
    for f in files:
        raw = f.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else None
        if text is None:
            print(f"FAIL   {f.name}: not UTF-8/UTF-16 text"); rc = 1; continue
        text = strip_bom(text)
        try:
            json.loads(text)
            print(f"OK     {f.name}: already valid JSON"); continue
        except ValueError:
            pass
        try:
            resp, rep = repair_pagecontent_text(text)
            m = NAME.match(f.name)
            cur = ((resp.get("data") or {}).get("currentPage") or {}).get("loio")
            deliv = ((resp.get("data") or {}).get("deliverable") or {})
            if m and cur != m.group("page"):
                raise RepairError(f"currentPage.loio {cur} != page in file name {m.group('page')}")
            json.loads(json.dumps(resp))            # round-trip sanity
        except RepairError as e:
            print(f"FAIL   {f.name}: {e} (nothing written)"); rc = 1; continue
        rep.update(source_file=f.name, original_sha256=hashlib.sha256(raw).hexdigest(),
                   response_loio=deliv.get("loio"), current_page_loio=cur,
                   toc_roots=len(deliv.get("fullToc") or []), title=(resp["data"].get("currentPage") or {}).get("t"))
        print(f"REPAIR {f.name}: loio={rep['response_loio']} currentPage={cur} bare_quotes={rep['bare_quotes_escaped']} "
              f"body_chars={rep['body_chars']} toc_roots={rep['toc_roots']}" + ("  [dry-run]" if a.dry_run else ""))
        if a.dry_run:
            continue
        keep = f.parent / "_malformed_originals"
        keep.mkdir(exist_ok=True)
        if not (keep / f.name).exists():
            (keep / f.name).write_bytes(raw)
        (keep / (f.name + ".repair.json")).write_text(json.dumps(rep, indent=2), encoding="utf-8")
        out = json.dumps(resp, ensure_ascii=False, separators=(",", ":"))
        f.write_text(out, encoding="utf-8")
        json.load(open(f, encoding="utf-8"))        # must load
    return rc


if __name__ == "__main__":
    sys.exit(main())
