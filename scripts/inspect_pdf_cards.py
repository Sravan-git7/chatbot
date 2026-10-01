"""PHASE 2 (read-only): deep inspection of the 29 reference-card PDFs.

Looks beyond visible text: raw objects, trailer /ID, catalog entries (names, dests,
open actions, JS, embedded files, XMP), every annotation and its action, hidden-text
operators (render mode 3, white fill, off-page text), bytes after %%EOF, and every
URL-like / 32-hex / numeric token anywhere in the decoded file. Writes
data/forensics/pdf_deep_inspection.json
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True
from pypdf import PdfReader                      # noqa: E402
from pypdf.generic import IndirectObject         # noqa: E402

HEX32 = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{32}(?![0-9a-fA-F])")


def inspect(path: Path, topic_guide: str, topic_page: str):
    raw = path.read_bytes()
    rd = PdfReader(io.BytesIO(raw))
    cat = rd.trailer["/Root"]
    out = {"file": path.name, "bytes": len(raw), "pdf_version": raw[:8].decode("latin-1").strip(),
           "pages": len(rd.pages), "trailer_keys": sorted(rd.trailer.keys()),
           "catalog_keys": sorted(cat.keys()),
           "info": {k: str(v) for k, v in (rd.metadata or {}).items()},
           "xmp_metadata": rd.xmp_metadata is not None,
           "has_names_dests_openaction_js": {k: (k in cat) for k in ("/Names", "/Dests", "/OpenAction", "/AA", "/JavaScript", "/AcroForm", "/Outlines", "/PageLabels", "/StructTreeRoot", "/Metadata")},
           "embedded_files": list((rd.attachments or {}).keys()),
           "bytes_after_last_EOF": len(raw) - (raw.rfind(b"%%EOF") + 5) - (1 if raw.endswith(b"\n") else 0),
           "eof_count": raw.count(b"%%EOF"), "xref_sections": raw.count(b"startxref")}
    idt = rd.trailer.get("/ID")
    out["trailer_ID"] = [bytes(x).hex() if isinstance(x, (bytes, bytearray)) else str(x) for x in idt] if idt else None
    # objects
    kinds = Counter()
    annots = []
    hidden = {"render_mode_3": 0, "white_fill": 0}
    all_text_ops = []
    for i in range(1, rd.trailer["/Size"]):
        try:
            o = rd.get_object(IndirectObject(i, 0, rd))
        except Exception:
            continue
        if o is None:
            continue
        kinds[type(o).__name__] += 1
        if hasattr(o, "get") and o.get("/Type") == "/Annot":
            a = o.get("/A") or {}
            annots.append({"subtype": str(o.get("/Subtype")), "rect": [round(float(x), 1) for x in o.get("/Rect", [])],
                           "action_keys": sorted(a.keys()), "uri": str(a.get("/URI")) if "/URI" in a else None,
                           "other_keys": sorted(k for k in o.keys() if k not in ("/Type", "/Subtype", "/Rect", "/A", "/Border", "/F"))})
        if hasattr(o, "get_data"):
            try:
                s = o.get_data().decode("latin-1")
            except Exception:
                continue
            if "BT" in s and "Tj" in s:
                hidden["render_mode_3"] += len(re.findall(r"\b3\s+Tr\b", s))
                # fill colour set to white (1 1 1 rg / 1 g) immediately before text
                hidden["white_fill"] += len(re.findall(r"\b1\s+1\s+1\s+rg\b|\b1\s+g\b", s))
                all_text_ops = re.findall(r"\((.*?)\)\s*Tj", s)
    out["object_kinds"] = dict(kinds)
    out["annotations"] = annots
    out["hidden_text_indicators"] = hidden
    out["content_stream_tj_strings"] = len(all_text_ops)
    # every token class anywhere (raw + decoded)
    blob = raw.decode("latin-1") + "\n" + "\n".join(
        (rd.get_object(IndirectObject(i, 0, rd)).get_data().decode("latin-1")
         if hasattr(rd.get_object(IndirectObject(i, 0, rd)), "get_data") else "") for i in range(1, rd.trailer["/Size"]))
    hexes = sorted(set(h.lower() for h in HEX32.findall(blob)))
    m_id = re.search(rb"/ID\s*\[<([0-9a-fA-F]{32})>", raw)
    out["trailer_ID_hex"] = m_id.group(1).decode().lower() if m_id else None
    out["hex32_tokens_anywhere"] = {h: ("card_guide_id" if h == topic_guide else "card_page_id" if h == topic_page else
                                        "reportlab_document_digest (trailer /ID)" if h == out["trailer_ID_hex"] else "OTHER")
                                    for h in hexes}
    out["url_like_tokens_raw_decoded"] = sorted(set(re.findall(r"https?:[^\s()<>\"']+", blob)))
    out["numeric_tokens_ge_5_digits_in_text_strings"] = sorted(set(n for s in all_text_ops for n in re.findall(r"\d{5,}", s)))
    out["query_params"] = sorted(set(re.findall(r"\?[A-Za-z_]+=[^\s()<>\"']+", blob)))
    return out


def main():
    man = json.loads((ROOT / "data" / "topic_manifest.json").read_text(encoding="utf-8"))
    res = [inspect(ROOT / t["pdf_file"], t["guide_id"], t["page_id"]) for t in man["topics"]]
    summary = {
        "pdfs": len(res),
        "producers": dict(Counter(r["info"].get("/Producer") for r in res)),
        "authors": dict(Counter(r["info"].get("/Author") for r in res)),
        "creators": dict(Counter(r["info"].get("/Creator") for r in res)),
        "subjects_keywords": dict(Counter(str((r["info"].get("/Subject"), r["info"].get("/Keywords"))) for r in res)),
        "annotation_counts": dict(Counter(len(r["annotations"]) for r in res)),
        "annotation_action_keys": dict(Counter(str(a["action_keys"]) for r in res for a in r["annotations"])),
        "annotation_extra_keys": dict(Counter(str(a["other_keys"]) for r in res for a in r["annotations"])),
        "catalog_keys": dict(Counter(str(r["catalog_keys"]) for r in res)),
        "features_present": {k: sum(r["has_names_dests_openaction_js"][k] for r in res) for k in res[0]["has_names_dests_openaction_js"]},
        "embedded_files_total": sum(len(r["embedded_files"]) for r in res),
        "xmp_present": sum(r["xmp_metadata"] for r in res),
        "hidden_render_mode_3_total": sum(r["hidden_text_indicators"]["render_mode_3"] for r in res),
        "white_fill_ops_total": sum(r["hidden_text_indicators"]["white_fill"] for r in res),
        "bytes_after_last_EOF_nonzero": [r["file"] for r in res if r["bytes_after_last_EOF"] not in (0, -1)],
        "eof_counts": dict(Counter(r["eof_count"] for r in res)),
        "distinct_urls_in_files": sorted({u for r in res for u in r["url_like_tokens_raw_decoded"]
                                          if "help.sap.com" not in u}),
        "help_sap_urls_per_pdf": dict(Counter(len({u for u in r["url_like_tokens_raw_decoded"] if "help.sap.com" in u}) for r in res)),
        "hex32_token_classes": dict(Counter(c for r in res for c in r["hex32_tokens_anywhere"].values())),
        "OTHER_hex32_equals_trailer_ID_count": sum(1 for r in res for h, c in r["hex32_tokens_anywhere"].items()
                                                     if c.startswith("reportlab_document_digest")),
        "query_params_seen": dict(Counter(q for r in res for q in r["query_params"])),
        "numeric_tokens_seen": sorted({n for r in res for n in r["numeric_tokens_ge_5_digits_in_text_strings"]}),
        "sha256_distinct_pdfs": len({hashlib.sha256((ROOT / r["file"]).read_bytes()).hexdigest() for r in res}),
    }
    out = ROOT / "data" / "forensics" / "pdf_deep_inspection.json"
    out.write_text(json.dumps({"summary": summary, "per_pdf": res}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", out.relative_to(ROOT))
    print(json.dumps(summary, indent=1)[:6000])


if __name__ == "__main__":
    main()
