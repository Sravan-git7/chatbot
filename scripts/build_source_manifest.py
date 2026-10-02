#!/usr/bin/env python3
"""Phase 0 - build an auditable 01-29 source registry from the reference PDFs (offline, read-only).

    python scripts/build_source_manifest.py [--pdf-dir .] [--out-dir data]

Writes  data/source_manifest.json   data/source_manifest.csv
        data/source_inventory.md    data/source_validation_report.md

The PDFs are the source of truth. Nothing is invented, repaired or normalised beyond joining text that the PDF
itself wrapped over several lines. No network, no embeddings, no vector store, PDFs are never modified.

URL handling: ``source_url`` is the exact ``/Annots`` ``/URI`` value of the link annotation in the PDF. The text that is
printed on the page (``source_url_display``) is preserved separately, byte for byte (it contains ``&#8203;`` artefacts and
line breaks). If the two disagree, the annotation is missing/ambiguous, or the URL deviates from the pattern shared by the
other cards, ``source_url_status`` is ``needs_review`` (with reasons) - the value is never "fixed".

``status`` = ``verified`` only means: the PDF was extracted, every expected field is present, the number/filename/title
are internally consistent and the URL has no review flag. It does NOT mean that the SAP Help page was opened or checked.

Exit code: 0 = all 29 present and extracted, 1 = numbering/extraction problems (see the report).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_FILENAMES = """01_Utilities_Master_Data.pdf
02_Move_In_Out_Overview.pdf
03_Move_In_Process.pdf
04_Move_Out_Process.pdf
05_Device_Management_Overview.pdf
06_Reading_Meters.pdf
07_Monitoring_Meter_Reading_Results.pdf
08_Meter_Reading_Estimation.pdf
09_Estimation_Procedure_Details.pdf
10_Meter_Reading_Data_During_Move_In.pdf
11_SAP_Utilities_Billing_Procedure.pdf
12_Automatic_Billing.pdf
13_Budget_Billing_Plan.pdf
14_SAP_Utilities_Invoicing_Procedure.pdf
15_Processing_Budget_Billing_Plans.pdf
16_Periodic_Billing_and_Invoicing_Analysis.pdf
17_Contract_Accounts_Overview.pdf
18_Contract_Account_Business_Object.pdf
19_Analyze_Incoming_Payments.pdf
20_Clearing_Control_in_Incoming_Payments.pdf
21_Clearing_Types.pdf
22_Processing_Incoming_Payments_from_External_Cash_Desks.pdf
23_Installment_Plan_Overview.pdf
24_Creating_Installment_Plans.pdf
25_Displaying_and_Changing_Installment_Plans.pdf
26_FI_CA_Dunning.pdf
27_Submission_of_Receivables_to_Collection_Agency.pdf
28_Collection_Agency_APIs_and_Enterprise_Services.pdf
29_Disconnection_Reconnection_of_a_Utility_Installation.pdf""".split("\n")
EXPECTED_IDS = [f"{i:02d}" for i in range(1, 30)]
NAME_RE = re.compile(r"^(?P<num>\d{2})_(?P<slug>.+)\.pdf$", re.I)
HDR_RE = re.compile(r"^\s*SAP Utilities M2C Source Reference\s+(?P<num>\d+)\s*$")
SECTIONS = ["What it covers", "Meter-to-Cash relevance", "Authoritative SAP Help source", "Library use",
            "Copyright / distribution note"]
HELP_URL_RE = re.compile(r"^https://help\.sap\.com/docs/(?P<product>[^/?#]+)/(?P<guide>[^/?#]+)/(?P<page>[^/?#]+)\.html(?P<query>\?[^#]*)?$")
ENTITY_ZWSP = "&#8203;"
ZERO_WIDTH = "\u200b\u200c\u200d\ufeff\u2060"
CANON_PRODUCT = "SAP_S4HANA_ON-PREMISE"


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def find_pdfs(pdf_dir: Path) -> List[Path]:
    return sorted(p for p in pdf_dir.glob("*.pdf") if p.is_file())


def extract_pdf(path: Path) -> Dict[str, Any]:
    """Raw facts from one PDF: page texts, link annotations, metadata. Never raises for bad PDFs."""
    from pypdf import PdfReader
    out: Dict[str, Any] = {"ok": False, "error": None, "pages": 0, "text": "", "uris": [], "metadata": {}}
    try:
        r = PdfReader(str(path))
        out["pages"] = len(r.pages)
        out["text"] = "\n".join((p.extract_text() or "") for p in r.pages)
        for p in r.pages:
            for a in p.get("/Annots") or []:
                a = a.get_object()
                act = a.get("/A")
                if act is not None and "/URI" in act.get_object():
                    out["uris"].append(str(act.get_object()["/URI"]))
        md = r.metadata or {}
        out["metadata"] = {k.lstrip("/").lower(): str(v) for k, v in md.items()}
        out["ok"] = bool(out["text"].strip())
        if not out["ok"]:
            out["error"] = "no extractable text"
    except Exception as e:                                  # noqa: BLE001 - reported, not hidden
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def _squash(lines: List[str]) -> str:
    """Join lines the PDF wrapped; collapse whitespace. No other change."""
    return re.sub(r"\s+", " ", " ".join(l.strip() for l in lines)).strip()


def parse_card(text: str) -> Dict[str, Any]:
    """Parse the fixed card layout. Missing pieces stay None and are reported, never guessed."""
    lines = text.split("\n")
    res: Dict[str, Any] = {"reference_number_text": None, "title": None, "category": None, "sections": {}, "issues": []}
    hi = next((i for i, l in enumerate(lines) if HDR_RE.match(l)), None)
    if hi is None:
        res["issues"].append("header 'SAP Utilities M2C Source Reference NN' not found")
        return res
    res["reference_number_text"] = HDR_RE.match(lines[hi]).group("num")
    ci = next((i for i in range(hi + 1, len(lines)) if lines[i].startswith("Category:")), None)
    if ci is None:
        res["issues"].append("'Category:' line not found")
        return res
    res["title"] = _squash(lines[hi + 1:ci]) or None
    # category may itself wrap until the first section heading
    first_sec = next((i for i in range(ci + 1, len(lines)) if lines[i].strip() == SECTIONS[0]), None)
    if first_sec is None:
        res["issues"].append("section 'What it covers' not found")
        return res
    res["category"] = _squash([lines[ci][len("Category:"):]] + lines[ci + 1:first_sec]) or None
    # section headings: 'Meter-to-Cash' / 'relevance' is wrapped over two lines in the PDFs
    idx: List[tuple] = []
    i = first_sec
    while i < len(lines):
        s = lines[i].strip()
        if s == "Meter-to-Cash" and i + 1 < len(lines) and lines[i + 1].strip() == "relevance":
            idx.append((SECTIONS[1], i, i + 2)); i += 2; continue
        if s in SECTIONS and s != SECTIONS[1]:
            idx.append((s, i, i + 1))
        i += 1
    for k, (name, _, body_start) in enumerate(idx):
        end = idx[k + 1][1] if k + 1 < len(idx) else len(lines)
        res["sections"][name] = lines[body_start:end]
    for s in SECTIONS:
        if s not in res["sections"]:
            res["issues"].append(f"section '{s}' not found")
    return res


def norm_display(u: str) -> str:
    u = u.replace(ENTITY_ZWSP, "")
    for z in ZERO_WIDTH:
        u = u.replace(z, "")
    return re.sub(r"\s+", "", u)


def assess_url(annotation_uris: List[str], display_lines: Optional[List[str]]) -> Dict[str, Any]:
    """Status of the extracted link. Values are preserved exactly; problems are listed, nothing is repaired."""
    reasons: List[str] = []
    display_raw = None
    display_url = None
    if display_lines is not None:
        body = list(display_lines)
        # first line is the fixed label "Open this topic on SAP Help Portal"
        label = body[0].strip() if body else ""
        rest = body[1:] if label.lower().startswith("open this topic") else body
        display_raw = "\n".join(rest).strip("\n")
        display_url = "".join(l.strip() for l in rest)
    uri = None
    if not annotation_uris:
        reasons.append("no link annotation (/URI) in the PDF")
    else:
        uniq = list(OrderedDict.fromkeys(annotation_uris))
        uri = uniq[0]
        if len(uniq) > 1:
            reasons.append(f"{len(uniq)} different link annotations: {uniq}")
    if display_url is None or not display_url:
        reasons.append("no URL text printed under 'Authoritative SAP Help source'")
    if uri is None and display_url:
        status = "needs_review"
        reasons.append("only printed text available (contains layout/encoding artefacts); not used as the URL")
        return {"url": None, "display_raw": display_raw, "status": status, "reasons": reasons, "notes": []}
    if uri is None:
        return {"url": None, "display_raw": display_raw, "status": "missing", "reasons": reasons, "notes": []}
    notes: List[str] = []
    if display_url:
        artefacts = []
        if ENTITY_ZWSP in display_url:
            artefacts.append(f"{display_url.count(ENTITY_ZWSP)}x literal '{ENTITY_ZWSP}' (zero-width-space HTML entity) in the printed text")
        if display_raw and "\n" in display_raw:
            artefacts.append("printed URL wraps over several lines")
        if artefacts:
            notes.append("printed text differs only by layout artefacts: " + "; ".join(artefacts))
        if norm_display(display_url) != uri:
            reasons.append("printed URL (after removing whitespace and zero-width-space entities) does not equal the link annotation")
    m = HELP_URL_RE.match(uri)
    if not uri.startswith("https://"):
        reasons.append("URL is not https")
    if urlsplit(uri).netloc != "help.sap.com":
        reasons.append(f"host is not help.sap.com: {urlsplit(uri).netloc!r}")
    if not m:
        reasons.append("URL does not match https://help.sap.com/docs/<product>/<guide>/<page>.html")
    else:
        if m.group("product") != CANON_PRODUCT:
            reasons.append(f"product segment {m.group('product')!r} differs from {CANON_PRODUCT!r} used by the other cards")
        if not re.fullmatch(r"[0-9a-f]{32}", m.group("guide")):
            reasons.append(f"guide segment is not 32 lower-case hex: {m.group('guide')!r}")
        if not re.fullmatch(r"[0-9a-f]{32}", m.group("page")):
            reasons.append(f"page segment is not 32 lower-case hex: {m.group('page')!r}")
        if m.group("query"):
            reasons.append(f"query string {m.group('query')!r} present (not on most cards; version pin to be confirmed)")
    if any(ch in uri for ch in ZERO_WIDTH) or "&#" in uri or "%" in uri or " " in uri:
        reasons.append("URL text contains encoded or invisible characters")
    return {"url": uri, "display_raw": display_raw, "status": "needs_review" if reasons else "ok", "reasons": reasons, "notes": notes}


def build_document(path: Path, facts: Dict[str, Any], card: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    m = NAME_RE.match(path.name)
    sec = (card or {}).get("sections", {})
    issues: List[str] = list((card or {}).get("issues", []))
    doc: Dict[str, Any] = OrderedDict()
    doc["id"] = m.group("num") if m else None
    doc["filename"] = path.name
    doc["title"] = (card or {}).get("title")
    doc["category"] = (card or {}).get("category")
    doc["what_it_covers"] = _squash(sec["What it covers"]) if "What it covers" in sec else None
    doc["meter_to_cash_relevance"] = _squash(sec["Meter-to-Cash relevance"]) if "Meter-to-Cash relevance" in sec else None
    u = assess_url(facts["uris"], sec.get("Authoritative SAP Help source"))
    doc["authoritative_source"] = u["url"]
    doc["source_type"] = "SAP Help Portal" if u["url"] and urlsplit(u["url"]).netloc == "help.sap.com" else None
    doc["source_url_status"] = u["status"]
    doc["source_url_reasons"] = u["reasons"]
    doc["source_url_notes"] = u["notes"]
    doc["source_url_display"] = u["display_raw"]
    doc["library_use"] = _squash(sec["Library use"]) if "Library use" in sec else None
    doc["copyright_note"] = _squash(sec["Copyright / distribution note"]) if "Copyright / distribution note" in sec else None
    doc["reference_number_in_text"] = (card or {}).get("reference_number_text")
    md = facts["metadata"]
    doc["pdf_metadata"] = {k: md[k] for k in ("title", "author", "creator", "producer", "creationdate", "subject") if k in md}
    doc["pdf_pages"] = facts["pages"]
    doc["pdf_bytes"] = path.stat().st_size
    doc["pdf_sha256"] = sha256(path.read_bytes())
    # consistency checks
    if not facts["ok"]:
        issues.append(f"extraction failed: {facts['error']}")
    if m and doc["reference_number_in_text"] is not None and int(doc["reference_number_in_text"]) != int(m.group("num")):
        issues.append(f"reference number in text ({doc['reference_number_in_text']}) != number in file name ({m.group('num')})")
    slug = m.group("slug").replace("_", " ") if m else None
    title_meta = md.get("title")
    if doc["title"] and title_meta and title_meta != doc["title"]:
        issues.append(f"title in text {doc['title']!r} != PDF metadata title {title_meta!r}")
    if doc["title"] and slug and re.sub(r"\W+", " ", slug).strip().lower() != re.sub(r"\W+", " ", doc["title"]).strip().lower():
        issues.append(f"title {doc['title']!r} does not match the file name slug {slug!r} (informational)")
    for k in ("title", "category", "what_it_covers", "meter_to_cash_relevance"):
        if not doc[k]:
            issues.append(f"missing {k}")
    doc["extraction_ok"] = bool(facts["ok"]) and not any(i.startswith(("header", "'Category", "section", "missing")) for i in issues)
    doc["review_reasons"] = [f"URL: {r}" for r in u["reasons"]] + [i for i in issues if not i.endswith("(informational)")]
    doc["informational"] = [i for i in issues if i.endswith("(informational)")]
    doc["status"] = "verified" if doc["extraction_ok"] and u["status"] == "ok" and not doc["review_reasons"] else "needs_review"
    return doc


def validate_numbering(pdfs: List[Path], docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    names = [p.name for p in pdfs]
    nums = [NAME_RE.match(n).group("num") if NAME_RE.match(n) else None for n in names]
    cnt = Counter(n for n in nums if n)
    v: Dict[str, Any] = {
        "pdf_count": len(pdfs),
        "expected_count": 29,
        "missing_numbers": [n for n in EXPECTED_IDS if n not in cnt],
        "duplicate_numbers": sorted(n for n, c in cnt.items() if c > 1),
        "numbers_out_of_range": sorted(n for n in cnt if n not in EXPECTED_IDS),
        "files_without_number_prefix": [n for n, x in zip(names, nums) if x is None],
        "missing_expected_filenames": [f for f in EXPECTED_FILENAMES if f not in names],
        "unexpected_filenames": [n for n in names if n not in EXPECTED_FILENAMES],
        "filename_number_mismatches": [],
    }
    for n in names:                                      # same number, but the name is not the expected one
        m = NAME_RE.match(n)
        if m and n not in EXPECTED_FILENAMES:
            exp = next((f for f in EXPECTED_FILENAMES if f.startswith(m.group("num") + "_")), None)
            v["filename_number_mismatches"].append({"file": n, "expected": exp})
    by_hash = defaultdict(list)
    for d in docs:
        by_hash[d["pdf_sha256"]].append(d["filename"])
    v["duplicate_content_files"] = [sorted(x) for x in by_hash.values() if len(x) > 1]
    by_url = defaultdict(list)
    for d in docs:
        if d["authoritative_source"]:
            by_url[d["authoritative_source"]].append(d["filename"])
    v["duplicate_source_urls"] = [{"url": u, "files": sorted(f)} for u, f in by_url.items() if len(f) > 1]
    by_title = defaultdict(list)
    for d in docs:
        if d["title"]:
            by_title[d["title"].lower()].append(d["filename"])
    v["duplicate_titles"] = [sorted(x) for x in by_title.values() if len(x) > 1]
    v["numbering_ok"] = (len(pdfs) == 29 and not v["missing_numbers"] and not v["duplicate_numbers"] and not v["numbers_out_of_range"]
                         and not v["files_without_number_prefix"] and not v["missing_expected_filenames"]
                         and not v["unexpected_filenames"] and not v["duplicate_content_files"])
    return v


CSV_COLUMNS = ["id", "filename", "title", "category", "what_it_covers", "meter_to_cash_relevance", "authoritative_source",
               "source_type", "source_url_status", "source_url_reasons", "source_url_notes", "source_url_display", "status",
               "review_reasons", "reference_number_in_text", "library_use", "copyright_note", "pdf_pages", "pdf_bytes", "pdf_sha256"]


def write_csv(path: Path, docs: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(CSV_COLUMNS)
        for d in docs:
            row = []
            for c in CSV_COLUMNS:
                val = d.get(c)
                if isinstance(val, list):
                    val = " | ".join(val)
                row.append("" if val is None else str(val).replace("\n", "\\n"))
            w.writerow(row)


def _cell(s: Any) -> str:
    return ("" if s is None else str(s)).replace("|", "\\|").replace("\n", " ")


def write_inventory(path: Path, docs: List[Dict[str, Any]], val: Dict[str, Any]) -> None:
    groups: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()
    for d in docs:
        groups.setdefault(d["category"] or "(no category extracted)", []).append(d)
    L = ["# Source inventory: SAP Utilities Meter-to-Cash reference PDFs (01-29)", "",
         "Generated by `scripts/build_source_manifest.py` from the PDFs only (offline). Grouping = the `Category:` printed in each PDF; "
         "groups appear in the order of the first document that carries them. URLs are the exact link annotations, unrepaired. "
         "`verified` = extracted and internally consistent, NOT checked against SAP Help.", "",
         f"* PDFs: **{val['pdf_count']}** / 29   numbering OK: **{val['numbering_ok']}**   "
         f"verified: **{sum(d['status'] == 'verified' for d in docs)}**   needs review: **{sum(d['status'] != 'verified' for d in docs)}**", ""]
    for cat, ds in groups.items():
        L += [f"## {cat} ({len(ds)})", "", "| # | Title | What it covers | Meter-to-Cash relevance | Source URL | URL status | Status |",
              "|--:|---|---|---|---|---|---|"]
        for d in ds:
            L.append(f"| {d['id']} | {_cell(d['title'])}<br>`{d['filename']}` | {_cell(d['what_it_covers'])} | {_cell(d['meter_to_cash_relevance'])} | "
                     f"{('`' + d['authoritative_source'] + '`') if d['authoritative_source'] else '**missing**'} | {d['source_url_status']} | {d['status']} |")
        L.append("")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def _external_findings(root: Path) -> Dict[int, str]:
    """Facts learned later from captured SAP responses (NOT from the PDFs); shown separately, never merged into the manifest."""
    out: Dict[int, str] = {}
    f = root / "data" / "topic_corrections.json"
    if f.is_file():
        try:
            for c in json.loads(f.read_text(encoding="utf-8")).get("corrections", []):
                out[int(c["topic_id"])] = (f"card names guide `{c['card_guide_id']}`, but SAP resolves the original URL to guide "
                                           f"`{c['resolved_guide_id']}` (`data/topic_corrections.json`, evidence attached there)")
        except (ValueError, KeyError):
            out[0] = "data/topic_corrections.json exists but could not be read"
    if (root / "data" / "forensics" / "card_mapping_investigation_18_5.md").is_file():
        out.setdefault(18, "the page id on the card was served by a different SAP deliverable (`e4375c1c…`, 'Enterprise Services in Financials') "
                           "than the guide named in the card URL (`94424864…`) in a probe; unresolved (`data/forensics/card_mapping_investigation_18_5.md`)")
    return out


def write_report(path: Path, docs: List[Dict[str, Any]], val: Dict[str, Any], extra_pdfs: List[str], root: Path) -> None:
    ok = [d for d in docs if d["extraction_ok"]]
    fails = [d for d in docs if not d["extraction_ok"]]
    no_url = [d for d in docs if d["source_url_status"] == "missing"]
    bad_url = [d for d in docs if d["source_url_status"] == "needs_review"]
    manual = [d for d in docs if d["status"] != "verified"]
    def bl(items): return items if items else ["none"]
    L = ["# Source validation report", "",
         "Phase 0 (source registry). Generated by `scripts/build_source_manifest.py`; offline, PDFs read-only.", "",
         "## Result", "",
         f"**{'PASS' if val['numbering_ok'] and not fails else 'FAIL'}** numbering/extraction. "
         f"URL review: {len(bad_url)} document(s) need review, {len(no_url)} missing.", "",
         "| Check | Result |", "|---|---|",
         f"| Total PDFs found | **{val['pdf_count']}** (expected 29) |",
         f"| Successfully extracted | **{len(ok)}** / {len(docs)} |",
         f"| Missing numbers (01-29) | {val['missing_numbers'] or 'none'} |",
         f"| Missing expected filenames | {val['missing_expected_filenames'] or 'none'} |",
         f"| Duplicate numbers | {val['duplicate_numbers'] or 'none'} |",
         f"| Duplicate documents (identical PDF bytes) | {val['duplicate_content_files'] or 'none'} |",
         f"| Duplicate source URLs | {[x['files'] for x in val['duplicate_source_urls']] or 'none'} |",
         f"| Duplicate titles | {val['duplicate_titles'] or 'none'} |",
         f"| Filenames not matching the expected numbering/name | {val['unexpected_filenames'] or 'none'} |",
         f"| Files without a two-digit number prefix | {val['files_without_number_prefix'] or 'none'} |",
         f"| Numbers outside 01-29 | {val['numbers_out_of_range'] or 'none'} |",
         f"| Extraction failures | {len(fails)} |",
         f"| Documents with missing SAP Help URL | {len(no_url)} |",
         f"| Documents with suspicious/malformed URL (`needs_review`) | {len(bad_url)} |",
         f"| Documents requiring manual verification | {len(manual)} |", "",
         "## Extraction failures", ""]
    L += bl([f"* `{d['filename']}`: {'; '.join(d['review_reasons'])}" for d in fails])
    L += ["", "## Documents with missing SAP Help URLs", ""] + bl([f"* `{d['filename']}`" for d in no_url])
    L += ["", "## Documents with suspicious / malformed URLs", "",
          "The extracted `/URI` value is kept exactly as found; nothing was repaired.", ""]
    for d in bad_url:
        L.append(f"* **{d['id']}** `{d['filename']}`: `{d['authoritative_source']}`")
        for r in d["source_url_reasons"]:
            L.append(f"  * {r}")
    if not bad_url:
        L.append("none")
    ext = _external_findings(root)
    ext_only = [d for d in docs if d["status"] == "verified" and d["id"] and int(d["id"]) in ext]
    L += ["", "## Documents requiring manual verification", "",
          f"{len(manual)} from the PDF review" + (f", plus {len(ext_only)} more ({', '.join(d['id'] for d in ext_only)}) because of later SAP findings "
                                                   "(the manifest status reflects the PDFs only)" if ext_only else ""), ""]
    if manual or ext_only:
        L += ["| # | File | Reasons |", "|--:|---|---|"]
        L += [f"| {d['id']} | `{d['filename']}` | {_cell('; '.join(d['review_reasons']))}"
              f"{('; SAP finding: ' + _cell(ext[int(d['id'])])) if d['id'] and int(d['id']) in ext else ''} |" for d in manual]
        L += [f"| {d['id']} | `{d['filename']}` | PDF fields complete; SAP finding: {_cell(ext[int(d['id'])])} |" for d in ext_only]
    else:
        L.append("none")
    by_note = defaultdict(list)
    for d in docs:
        for n in d["source_url_notes"]:
            by_note[re.sub(r"\d+x literal", "Nx literal", n)].append(d["id"])
    L += ["", "## Notes that did NOT trigger review", "",
          "The printed URL text is not used as the URL (the link annotation is). The printed text differs from the annotation only as follows:", ""]
    L += bl([f"* {n} - documents: {', '.join(ids)}" + (" (all 29)" if len(ids) == len(docs) else "") for n, ids in by_note.items()])
    inf = [(d, n) for d in docs for n in d["informational"]]
    L += ["", "## Informational (title vs. file name)", ""] + bl([f"* {d['id']}: {n}" for d, n in inf])
    L += ["", "## Findings from captured SAP responses (not from the PDFs)", "",
          "Kept out of the manifest, which reflects only the PDFs. They matter for any later mapping of cards to SAP guides:", ""]
    L += bl([f"* topic {k:02d}: {v}" for k, v in sorted(ext.items())])
    L += ["", "## Other PDFs found in the scanned directory", ""] + bl([f"* `{n}`" for n in extra_pdfs])
    L += ["", "`verified` in the manifest = extracted, complete, internally consistent, URL without review flag. It does not mean the SAP Help page was opened.", ""]
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf-dir", default=str(ROOT))
    ap.add_argument("--out-dir", default=str(ROOT / "data"))
    a = ap.parse_args(argv)
    pdf_dir, out_dir = Path(a.pdf_dir), Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    all_pdfs = find_pdfs(pdf_dir)
    docs, facts_by = [], {}
    for p in all_pdfs:
        facts = extract_pdf(p)
        facts_by[p.name] = facts
        card = parse_card(facts["text"]) if facts["ok"] else None
        docs.append(build_document(p, facts, card))
    docs.sort(key=lambda d: (d["id"] is None, d["id"] or "", d["filename"]))
    val = validate_numbering(all_pdfs, docs)
    extra = [n for n in val["unexpected_filenames"]]
    (out_dir / "source_manifest.json").write_text(json.dumps({"documents": docs}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(out_dir / "source_manifest.csv", docs)
    write_inventory(out_dir / "source_inventory.md", docs, val)
    write_report(out_dir / "source_validation_report.md", docs, val, extra, ROOT)
    ok = sum(d["extraction_ok"] for d in docs)
    ver = sum(d["status"] == "verified" for d in docs)
    bad_url = [d["id"] for d in docs if d["source_url_status"] == "needs_review"]
    no_url = [d["id"] for d in docs if d["source_url_status"] == "missing"]
    print(f"PDFs found: {val['pdf_count']}/29   extracted: {ok}   numbering OK: {val['numbering_ok']}")
    print(f"missing numbers: {val['missing_numbers'] or 'none'}   duplicates: {val['duplicate_numbers'] or val['duplicate_content_files'] or 'none'}   "
          f"filename problems: {val['unexpected_filenames'] or val['missing_expected_filenames'] or 'none'}")
    print(f"verified: {ver}   needs_review: {len(docs) - ver}   URL needs_review: {bad_url or 'none'}   URL missing: {no_url or 'none'}")
    print(f"wrote {out_dir / 'source_manifest.json'}, source_manifest.csv, source_inventory.md, source_validation_report.md")
    return 0 if val["numbering_ok"] and ok == len(docs) else 1


if __name__ == "__main__":
    sys.exit(main())
