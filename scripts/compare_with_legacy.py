"""Compare a new corpus (scripts/build_corpus.py output) with the legacy sap_pages/, cleaned_pages.json, chunks.json.

Read-only for everything legacy.  Output: <corpus_dir>/comparison_with_legacy.{json,md}.
    python scripts/compare_with_legacy.py data/sap_help_e2e/page_and_descendants
Pages are matched by file_path (the SAP TOC node file), never by fuzzy title matching.
"""
import argparse
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True


def letters(s):
    return re.sub(r"[\W_]+", "", s).lower()


def collapse_title(legacy_text, title):
    """Legacy cleaned text starts with the page title twice ('Contract Accounts Contract Accounts'); the new cleaner keeps it once."""
    t = letters(title)
    x = letters(legacy_text)
    return x[len(t):] if t and x.startswith(t + t) else x


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus_dir")
    a = ap.parse_args(argv)
    cdir = (ROOT / a.corpus_dir) if not Path(a.corpus_dir).is_absolute() else Path(a.corpus_dir)
    legacy = {}
    for p in sorted((ROOT / "sap_pages").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        legacy[d["file_path"]] = (p.name, d)
    cleaned = {c["url"]: c for c in json.loads((ROOT / "cleaned_pages.json").read_text(encoding="utf-8"))}
    lchunks = json.loads((ROOT / "chunks.json").read_text(encoding="utf-8"))
    by_url = {}
    for c in lchunks:
        by_url.setdefault(c["url"], []).append(c)
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((cdir / "pages").rglob("*.json"))]
    chunks = [json.loads(l) for l in (cdir / "chunks" / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
    new_by_doc = {}
    for c in chunks:
        new_by_doc.setdefault(c["doc_id"], []).append(c)

    rows, seen_legacy = [], set()
    for d in sorted(docs, key=lambda x: x["file_path"]):
        name, lp = legacy.get(d["file_path"], (None, None))
        row = {"doc_id": d["doc_id"], "page_title": d["page_title"], "legacy_file": name, "status": d["status"]}
        if lp is None:
            row["raw_identical_to_legacy"] = None
        else:
            seen_legacy.add(name)
            row["raw_identical_to_legacy"] = d["text_raw"] == lp["text"]
            lc = cleaned.get(lp["source_url"])
            row["legacy_cleaned_chars"] = len(lc["text"]) if lc else None
            row["new_cleaned_chars"] = len(d["text"])
            row["same_letters_as_legacy_cleaned"] = (collapse_title(lc["text"], d["page_title"]) == letters(d["text"])) if lc else None
            row["legacy_chunks"] = len(by_url.get(lp["source_url"], []))
        nc = new_by_doc.get(d["doc_id"], [])
        row["new_chunks"] = len(nc)
        row["new_chunk_chars"] = [len(c["text"]) for c in nc]
        rows.append(row)

    def stats(xs):
        return {"n": len(xs), "avg": round(statistics.mean(xs), 1), "median": statistics.median(xs), "min": min(xs), "max": max(xs)} if xs else {}

    leg_pages = [r for r in rows if r["legacy_file"]]
    leg_chunk_lens = [len(c["text"]) for r in leg_pages for c in by_url.get(legacy[[d for d in docs if d["doc_id"] == r["doc_id"]][0]["file_path"]][1]["source_url"], [])]
    all_legacy_lens = [len(c["text"]) for c in lchunks]
    legacy_texts = [d["text"] for _, d in legacy.values()]
    man = json.loads((cdir / "final_corpus_manifest.json").read_text(encoding="utf-8")) if (cdir / "final_corpus_manifest.json").is_file() else None
    unmatched = sorted(n for n, _ in legacy.values() if n not in seen_legacy)
    corpus_level = {
        "legacy": {"pages": len(legacy), "unique_pages_by_text": len(set(legacy_texts)), "duplicate_pages": len(legacy_texts) - len(set(legacy_texts)),
                   "chunks": len(lchunks), "unique_chunks": len({c["text"] for c in lchunks}),
                   "duplicate_chunks": len(lchunks) - len({c["text"] for c in lchunks}), "chunk_chars": stats(all_legacy_lens),
                   "guides_covered": sorted({d["source_url"].split("/")[5] for _, d in legacy.values()}), "topics_covered_by_target_cards": [17]},
        "new": {"pages": len(docs), "unique_canonical_pages": sum(1 for d in docs if d["status"] == "OK"),
                "duplicate_content_pages": sum(1 for d in docs if d["status"] == "DUPLICATE_CONTENT"), "chunks": len(chunks),
                "unique_chunks": len({c["text"] for c in chunks}), "duplicate_chunks": len(chunks) - len({c["text"] for c in chunks}),
                "chunk_chars": stats([len(c["text"]) for c in chunks]),
                "guides_covered": sorted({d["guide_id"] for d in docs}),
                "topics_resolved": sum(1 for r in man["topics"] if r["status"] == "RESOLVED") if man else None,
                "topics_total": len(man["topics"]) if man else None, "corpus_complete": man["corpus_complete"] if man else None},
        "legacy_pages_not_in_new_corpus": len(unmatched),
        "legacy_pages_not_in_new_corpus_note": "pages of the legacy scrape that no target topic (under the chosen scope) asks for - the noise the new corpus leaves out",
        "legacy_pages_not_in_new_corpus_files": unmatched}
    out = {
        "corpus_level": corpus_level,
        "corpus_dir": str(a.corpus_dir),
        "pages": len(rows), "matched_to_legacy_sap_pages": len(leg_pages),
        "legacy_files": sorted(r["legacy_file"] for r in leg_pages),
        "raw_text_identical": sum(1 for r in leg_pages if r["raw_identical_to_legacy"]),
        "raw_text_different": [r["legacy_file"] for r in leg_pages if r["raw_identical_to_legacy"] is False],
        "cleaned_same_letters_as_legacy": sum(1 for r in leg_pages if r.get("same_letters_as_legacy_cleaned")),
        "cleaned_different_letters": [r["legacy_file"] for r in leg_pages if r.get("same_letters_as_legacy_cleaned") is False],
        "cleaned_chars": {"legacy": sum(r.get("legacy_cleaned_chars") or 0 for r in leg_pages), "new": sum(r["new_cleaned_chars"] for r in leg_pages)},
        "chunks": {"legacy": len([c for r in leg_pages for c in by_url.get(legacy[[d for d in docs if d["doc_id"] == r["doc_id"]][0]["file_path"]][1]["source_url"], [])]),
                   "new": len(chunks)},
        "chunk_chars": {"legacy": stats(leg_chunk_lens), "new": stats([len(c["text"]) for c in chunks])},
        "rows": rows,
    }
    (cdir / "comparison_with_legacy.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md = [f"# Comparison with legacy corpus: `{a.corpus_dir}`", "",
          f"* pages in new corpus: **{out['pages']}**, matched to legacy `sap_pages/` by `file_path`: **{out['matched_to_legacy_sap_pages']}** ({', '.join(out['legacy_files'][:1])} … {', '.join(out['legacy_files'][-1:])})",
          f"* raw text identical to legacy `sap_pages` text: **{out['raw_text_identical']}/{out['matched_to_legacy_sap_pages']}**",
          f"* cleaned text has the same letters/digits as legacy `cleaned_pages.json`: **{out['cleaned_same_letters_as_legacy']}/{out['matched_to_legacy_sap_pages']}** (after collapsing the legacy doubled page title; whitespace and punctuation joins ignored)",
          f"* cleaned characters legacy → new: {out['cleaned_chars']['legacy']} → {out['cleaned_chars']['new']}",
          f"* chunks legacy → new: {out['chunks']['legacy']} → {out['chunks']['new']}",
          f"* chunk chars legacy: {out['chunk_chars']['legacy']}", f"* chunk chars new: {out['chunk_chars']['new']}", "",
          "", "## Corpus level", "", "```", json.dumps({k: v for k, v in corpus_level.items() if k != "legacy_pages_not_in_new_corpus_files"}, indent=1), "```", "",
          "| page | legacy file | raw identical | legacy chunks | new chunks |", "|---|---|---|---|---|"]
    md += [f"| {r['page_title']} | {r['legacy_file']} | {r['raw_identical_to_legacy']} | {r.get('legacy_chunks')} | {r['new_chunks']} |" for r in rows]
    (cdir / "comparison_with_legacy.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md[:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
