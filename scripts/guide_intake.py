"""Register the six missing SAP Help guides (no code changes, no guessing).

    python scripts/guide_intake.py status                      # what is known / missing per guide
    python scripts/guide_intake.py template                    # add fill-in skeletons to data/guide_registrations.json
    python scripts/guide_intake.py add --pagecontent-url "<browser request URL>" --guide-id <32hex>
    python scripts/guide_intake.py add --guide-id <32hex> --numeric-id 12345678 --build-no 1234
    python scripts/guide_intake.py add --toc-file saved_response.json --numeric-id 12345678 --build-no 1234
    python scripts/guide_intake.py check                       # validate every registration (offline)
    python scripts/guide_intake.py capture                     # map captured browser URLs (data/captured_pagecontent_urls.txt)
    python scripts/guide_intake.py capture --allow-network     # ...replaying each URL: the RESPONSE loio decides, TOC saved
    python scripts/guide_intake.py capture --responses-dir captured_responses   # same, from responses saved by capture_responses.py

Then:  python scripts/build_corpus.py --allow-network --require-complete
(with ids registered and no saved TOC, that command downloads one TOC per guide, verifies its loio == guide_id,
saves it to data/toc/<guide_id>.json and continues with the normal pipeline).

What you need per guide: the numeric ``deliverable_id`` and ``buildNo`` of the ``http.svc/pagecontent`` request
the browser sends for that guide's pages (the same two parameters fetch_sap_pages.py uses), and optionally a saved
copy of that response (``toc_file``) instead of letting the pipeline download it.
Never made up here: values come only from your arguments; conflicting values are refused.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from sap_resolver import events as ev                                                                # noqa: E402
from sap_resolver.fetch import SapHelpApiFetcher                                                      # noqa: E402
from sap_resolver.intake import SavedResponses, capture_mapping, capture_markdown, clean_url_line, read_url_lines                                     # noqa: E402
from sap_resolver.registry import (GuideRegistry, RegistrationError, apply_registrations_ex, default_toc_path,  # noqa: E402
                                   load_registrations, normalise_registration, parse_pagecontent_request, refresh_registry)
from sap_resolver.toc import TocError, TocTree                                                        # noqa: E402

REG_FILE = ROOT / "data" / "guide_registrations.json"
README = ("Declarative guide registrations; one object per guide, no code change needed. Fill numeric_id + build_no "
          "(or paste the browser's pagecontent request URL into pagecontent_url). toc_file is optional: if omitted the "
          "pipeline uses data/toc/<guide_id>.json, downloading it with --allow-network when missing. Keys starting with "
          "'_' are notes and ignored. How to get the two numbers: open the guide's card URL (_example_card_url) in a "
          "browser, DevTools > Network, reload, find the request to http.svc/pagecontent and copy its URL "
          "(deliverable_id=<numeric>&buildNo=<n>). Nothing is guessed: invalid or conflicting entries are reported "
          "and skipped; empty skeletons just leave the guide UNRESOLVED_GUIDE.")


def load_manifest():
    p = ROOT / "data" / "topic_manifest.json"
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    from sap_resolver.pdf_cards import build_topic_manifest
    return build_topic_manifest(ROOT)


def load_file():
    if REG_FILE.is_file():
        return json.loads(REG_FILE.read_text(encoding="utf-8"))
    return {"registrations": []}


def save_file(doc):
    doc["_readme"] = README
    doc["registrations"] = sorted(doc["registrations"], key=lambda r: str(r.get("guide_id")))
    REG_FILE.parent.mkdir(parents=True, exist_ok=True)
    REG_FILE.write_text(json.dumps({"_readme": doc["_readme"], "registrations": doc["registrations"]}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def evaluate(manifest):
    regs = load_registrations(REG_FILE)
    reg0 = refresh_registry(manifest, ROOT, None)
    reg, errors, pending = apply_registrations_ex(reg0, manifest, regs, ROOT)
    return reg, errors, pending


def cmd_status(a):
    manifest = load_manifest()
    reg, errors, pending = evaluate(manifest)
    pend = {p["guide_id"]: p for p in pending}
    print(f"{'guide':10} {'topics':22} {'numeric':10} {'build':6} {'TOC':5} state")
    for g in manifest["guides"]:
        e = reg["guides"].get(g["guide_id"], {})
        toc = bool(e.get("toc_file"))
        ids = bool(e.get("numeric_deliverable_id") and e.get("build_no"))
        state = "READY (TOC + ids)" if toc and ids else "TOC saved, ids unknown (cannot fetch pages)" if toc else \
            "ids known, TOC will be downloaded with --allow-network" if ids else "NEEDS numeric_id + build_no"
        print(f"{g['guide_id'][:8]:10} {str(g['topic_ids']):22} {str(e.get('numeric_deliverable_id') or '-'):10} "
              f"{str(e.get('build_no') or '-'):6} {'yes' if toc else 'no':5} {state}")
    for er in errors:
        print("INVALID:", er)
    # topic resolution with the per-topic corrections (data/topic_corrections.json) applied
    from sap_resolver.corrections import apply_corrections, load_corrections
    from sap_resolver.registry import GuideRegistry
    from sap_resolver.resolver import RESOLVED, resolve_topics
    topics, applied, rejected = apply_corrections(manifest["topics"], load_corrections(ROOT / "data" / "topic_corrections.json"), ROOT)
    res, gstat, _ = resolve_topics(topics, GuideRegistry(reg, ROOT))
    ok = [r for r in res if r.status == RESOLVED]
    print(f"\nguides with a verified TOC: {sum(g.status == RESOLVED for g in gstat)}/{len(manifest['guides'])}   "
          f"topics resolved: {len(ok)}/{len(res)}")
    for c in applied:
        r = next(x for x in res if x.topic_id == c["topic_id"])
        print(f"  correction: topic {c['topic_id']} card guide {c['card_guide_id'][:8]} -> {c['resolved_guide_id'][:8]} "
              f"({'RESOLVED' if r.status == RESOLVED else 'UNRESOLVED: ' + str(r.reason)}; {len(c['evidence'])} evidence record(s))")
    for rj in rejected:
        print("  CORRECTION REJECTED:", rj)
    for r in res:
        if r.status != RESOLVED:
            print(f"  unresolved: topic {r.topic_id:>2} {r.title[:38]:38} guide {r.guide_id[:8]} {r.reason}")
    return 1 if errors or rejected else 0


def cmd_template(a):
    manifest = load_manifest()
    reg, errors, pending = evaluate(manifest)
    doc = load_file()
    have = {str(r.get("guide_id")).lower() for r in doc["registrations"]}
    first = {t["topic_id"]: t for t in manifest["topics"]}
    added = []
    for g in manifest["guides"]:
        gid = g["guide_id"]
        e = reg["guides"].get(gid, {})
        if gid in have or e.get("toc_file"):
            continue
        t0 = first[min(g["topic_ids"])]
        doc["registrations"].append({"guide_id": gid, "_topics": g["topic_ids"], "_product": g["product"],
                                     "_example_card_url": t0.get("url_as_given"), "numeric_id": None, "build_no": None,
                                     "pagecontent_url": None, "toc_file": None, "evidence": ""})
        added.append(gid[:8])
    save_file(doc)
    print(f"added {len(added)} skeleton(s) to {REG_FILE.relative_to(ROOT)}: {', '.join(added) or '-'}")
    return 0


def cmd_add(a):
    if a.pagecontent_url:
        a.pagecontent_url = clean_url_line(a.pagecontent_url)       # BOM (incl. mojibake) stripped before any parsing
    manifest = load_manifest()
    guide_ids = {g["guide_id"] for g in manifest["guides"]}
    gid = (a.guide_id or "").lower() or None
    toc_resp = None
    try:
        if a.toc_file:
            toc_resp = json.loads(Path(a.toc_file).read_text(encoding="utf-8"))
            tree = TocTree.from_pagecontent_response(toc_resp)
            if gid and gid != tree.guide_id:
                raise RegistrationError(f"--guide-id {gid} but the TOC file is guide {tree.guide_id}")
            gid = tree.guide_id
        if a.pagecontent_url and not toc_resp:
            rows = capture_mapping([a.pagecontent_url], manifest, ROOT)
            r0 = rows[0]
            if r0["guide_id"]:
                if gid and gid != r0["guide_id"]:
                    raise RegistrationError(f"--guide-id {gid[:8]} but the URL's page id is the card page of guide {r0['guide_id'][:8]}")
                gid = gid or r0["guide_id"]
            elif r0["decision"] == "REJECTED" and r0["numeric_id"] is None:
                raise RegistrationError(r0["reason"])
            elif gid and r0["card_matches"]:
                raise RegistrationError("URL's page id belongs to another guide's card: " + r0["reason"] if r0["reason"] else "card mismatch")
        if not gid:
            raise RegistrationError("--guide-id is required (or give --toc-file / a --pagecontent-url whose page id is on a card)")
        if gid not in guide_ids:
            raise RegistrationError(f"{gid} is not referenced by any topic card; refusing to register it")
        new = {"guide_id": gid, "evidence": a.evidence or "added via scripts/guide_intake.py"}
        if a.pagecontent_url:
            new["pagecontent_url"] = a.pagecontent_url
        if a.numeric_id:
            new["numeric_id"] = a.numeric_id
        if a.build_no:
            new["build_no"] = a.build_no
        if a.pagecontent_url:
            new["pagecontent_url"] = a.pagecontent_url
        norm = normalise_registration(new)
        dest = ROOT / default_toc_path(gid)
        if toc_resp is not None:
            if dest.exists() and json.loads(dest.read_text(encoding="utf-8")) != toc_resp:
                raise RegistrationError(f"{default_toc_path(gid)} already exists with different content; not overwriting")
        # dry-run validation against a scratch registry (with the TOC if supplied)
        scratch = refresh_registry(manifest, ROOT, None)
        if toc_resp is not None and not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(toc_resp, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            created = True
        else:
            created = False
        _, errs, pend = apply_registrations_ex(scratch, manifest, [norm], ROOT)
        if errs:
            if created:
                dest.unlink()
            raise RegistrationError(errs[0]["error"])
        if not (norm.get("numeric_id") or toc_resp is not None):
            raise RegistrationError("nothing to register: give --numeric-id/--build-no (or --pagecontent-url) and/or --toc-file")
        doc = load_file()
        kept, conflict = [], None
        for r in doc["registrations"]:
            if str(r.get("guide_id")).lower() != gid:
                kept.append(r)
                continue
            try:
                old = normalise_registration(r)
            except RegistrationError:
                old = {}
            for k in ("numeric_id", "build_no"):
                if old.get(k) and norm.get(k) and str(old[k]) != str(norm[k]):
                    conflict = f"{k} already registered as {old[k]!r}; edit data/guide_registrations.json by hand if intended"
        if conflict:
            raise RegistrationError(conflict)
        prev = next((r for r in doc["registrations"] if str(r.get("guide_id")).lower() == gid), {})
        entry = {**{k: v for k, v in prev.items() if k not in ("evidence", "verification")}, **{k: v for k, v in norm.items() if k != "evidence"}}
        entry["evidence"] = "; ".join(x for x in dict.fromkeys([str(prev.get("evidence") or ""), str(norm.get("evidence") or "")]) if x)
        if a.verification:
            entry["verification"] = a.verification
        elif prev.get("verification"):
            entry["verification"] = prev["verification"]
        if a.pagecontent_url:
            from html import unescape
            entry["pagecontent_url"] = a.pagecontent_url
        entry.update({"_topics": next(g["topic_ids"] for g in manifest["guides"] if g["guide_id"] == gid)})
        kept.append(entry)
        doc["registrations"] = kept
        save_file(doc)
    except (RegistrationError, TocError, OSError, ValueError) as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 3
    st = "TOC saved" if toc_resp is not None else "TOC will be downloaded with --allow-network"
    print(f"registered {gid} ({st}; numeric_id={norm.get('numeric_id')}, build_no={norm.get('build_no')})")
    return 0


def cmd_capture(a):
    manifest = load_manifest()
    urls_path = Path(a.urls_file) if a.urls_file else ROOT / "data" / "captured_pagecontent_urls.txt"
    urls = read_url_lines(urls_path)            # BOM / UTF-16 / zero-width / &amp; / markdown-wrapper tolerant
    fetcher = None
    if a.responses_dir:
        fetcher = SavedResponses(Path(a.responses_dir))
    elif a.allow_network:
        fetcher = SapHelpApiFetcher(GuideRegistry({"guides": {}}, ROOT), ev.EventLog(), allow_network=True, max_retries=2, delay_s=1.0)
    doc = load_file()
    rows = capture_mapping(urls, manifest, ROOT, fetcher, doc["registrations"])
    mode = "response_loio" if fetcher else "card_page_id"
    if a.responses_dir:
        mode += f" (saved responses: {a.responses_dir})"
    mapped = {}
    for r in rows:
        if r["decision"] == "MAPPED":
            mapped.setdefault(r["guide_id"], []).append(r)
    if not a.dry_run:
        for gid, rs in sorted(mapped.items()):
            r0 = rs[0]
            verified = r0["evidence"] == "response_loio"
            topics = next(g["topic_ids"] for g in manifest["guides"] if g["guide_id"] == gid)
            if verified:                                      # the response IS a TOC: save it (never overwrite a different one)
                dest = ROOT / default_toc_path(gid)
                resp = r0["_resp"]
                if dest.exists() and json.loads(dest.read_text(encoding="utf-8")) != resp:
                    for r in rs:
                        r.update(decision="CONFLICTS_WITH_EXISTING", reason=f"{default_toc_path(gid)} exists with different content; not overwritten")
                    continue
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(json.dumps(resp, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            entry = {"guide_id": gid, "numeric_id": r0["numeric_id"], "build_no": r0["build_no"],
                     "pagecontent_url": r0["url"].replace("&amp;", "&"), "captured_urls": [x["url"].replace("&amp;", "&") for x in rs],
                     "captured_page_ids": sorted({x["page_id"] for x in rs}),
                     "verification": "response_loio_verified" if verified else "card_page_match_unverified (loio is checked when the TOC is downloaded)",
                     "evidence": "; ".join(f"captured URL #{x['n']}: {x['reason']}" for x in rs), "_topics": topics}
            doc["registrations"] = [x for x in doc["registrations"] if str(x.get("guide_id")).lower() != gid] + [entry]
        # ambiguous claims: annotate (ignored by the pipeline), never register
        for r in rows:
            if r["decision"] == "AMBIGUOUS" and r["card_matches"]:
                for m in r["card_matches"]:
                    for x in doc["registrations"]:
                        if str(x.get("guide_id")).lower() == m["guide_id"] and not x.get("numeric_id"):
                            x.setdefault("_captured_candidates", [])
                            note = {"url": r["url"].replace("&amp;", "&"), "status": "AMBIGUOUS - NOT APPLIED", "why": r["reason"]}
                            if note not in x["_captured_candidates"]:
                                x["_captured_candidates"].append(note)
        save_file(doc)
    out = [{k: v for k, v in r.items() if k != "_resp"} for r in rows]
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "captured_url_mapping.json").write_text(json.dumps({"evidence_mode": mode, "urls_file": str(urls_path.name), "rows": out}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (ROOT / "data" / "captured_url_mapping.md").write_text(capture_markdown(out, mode), encoding="utf-8")
    print(capture_markdown(out, mode))
    return 0 if all(r["decision"] == "MAPPED" for r in rows) else 1


def cmd_check(a):
    manifest = load_manifest()
    reg, errors, pending = evaluate(manifest)
    for er in errors:
        print("INVALID:", er)
    for p in pending:
        print(f"PENDING {p['guide_id'][:8]}: {p['state']} (missing {', '.join(p['missing'])})")
    ok = [g for g in reg["guides"].values() if g.get("toc_file")]
    print(f"{len(ok)}/{len(manifest['guides'])} guides have a valid saved TOC; {len(errors)} invalid; {len(pending)} pending")
    return 1 if errors else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("template").set_defaults(fn=cmd_template)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    c = sub.add_parser("capture")
    c.add_argument("--urls-file", help="text file, one captured pagecontent URL per line (default data/captured_pagecontent_urls.txt)")
    c.add_argument("--allow-network", action="store_true", help="replay each captured URL (read-only GET); the response loio decides the mapping")
    c.add_argument("--responses-dir", help="folder of responses saved by scripts/capture_responses.py (no network needed)")
    c.add_argument("--dry-run", action="store_true", help="report only; do not touch data/guide_registrations.json or data/toc/")
    c.set_defaults(fn=cmd_capture)
    p = sub.add_parser("add")
    p.add_argument("--guide-id")
    p.add_argument("--numeric-id")
    p.add_argument("--build-no")
    p.add_argument("--pagecontent-url", help="the http.svc/pagecontent request URL copied from the browser network tab")
    p.add_argument("--toc-file", help="saved pagecontent?deliverableInfo=1 response for that guide")
    p.add_argument("--evidence")
    p.add_argument("--verification", help="free-text verification status stored with the registration (e.g. user_reported_response_loio)")
    p.set_defaults(fn=cmd_add)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
