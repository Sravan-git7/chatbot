"""Post-build audit of a corpus produced by scripts/build_corpus.py (read-only; no embeddings, no Chroma).

    python scripts/audit_corpus.py                     # data/sap_help  (+ data/final_corpus_manifest.json)
    python scripts/audit_corpus.py data/sap_help_e2e/page_and_descendants

Writes <corpus>/audit.json and audit.md and prints the summary. Exit code 0 = corpus READY for embedding,
1 = not ready (incomplete, failed fetches, suspicious cross-guide pages, ...).
"""
import argparse
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True


def stats(xs):
    return {"n": len(xs), "avg": round(statistics.mean(xs), 1), "median": statistics.median(xs), "min": min(xs), "max": max(xs)} if xs else {"n": 0}


def load_manifest(cdir):
    """The manifest that belongs to this corpus: <corpus>/final_corpus_manifest.json, else data/final_corpus_manifest.json
    if its isolation.corpus_dir is this directory."""
    own = cdir / "final_corpus_manifest.json"
    if own.is_file():
        return json.loads(own.read_text(encoding="utf-8")), own
    shared = ROOT / "data" / "final_corpus_manifest.json"
    if shared.is_file():
        m = json.loads(shared.read_text(encoding="utf-8"))
        if (ROOT / m["isolation"]["corpus_dir"]).resolve() == cdir:
            return m, shared
    raise SystemExit(f"no final_corpus_manifest.json belonging to {cdir}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus_dir", nargs="?", default="data/sap_help")
    a = ap.parse_args(argv)
    cdir = (ROOT / a.corpus_dir).resolve()
    m, mpath = load_manifest(cdir)
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((cdir / "pages").rglob("*.json"))]
    chunks = [json.loads(l) for l in (cdir / "chunks" / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
    topic_ids = {t["topic_id"] for t in m["topics"]}
    T = m["totals"]
    chunks_by_doc = Counter(c["doc_id"] for c in chunks)

    per_guide = {}
    for g in m["guides"]:
        gd = [d for d in docs if d["guide_id"] == g["guide_id"]]
        per_guide[g["guide_id"]] = {"guide_status": g["status"], "topics": g["topic_ids"], "numeric_deliverable_id": g["numeric_deliverable_id"],
                                    "build_no": g["build_no"], "documents": len(gd), "canonical_ok": sum(d["status"] == "OK" for d in gd),
                                    "duplicate_content": sum(d["status"] == "DUPLICATE_CONTENT" for d in gd),
                                    "empty": sum(d["status"] == "EMPTY_CONTENT" for d in gd),
                                    "chunks": sum(chunks_by_doc[d["doc_id"]] for d in gd), "cleaned_chars": sum(len(d["text"]) for d in gd)}
    per_topic = [{k: r.get(k) for k in ("topic_id", "topic_title", "guide_id", "resolution_status", "scope", "page_count", "unique_page_count",
                                        "duplicate_page_count", "duplicate_content_count", "chunk_count", "status")} for r in m["topics"]]

    suspicious = []
    for d in docs:
        why = []
        url_guide = re.search(r"/docs/[^/]+/([0-9a-f]{32})/", d["canonical_url"])
        if not url_guide or url_guide.group(1) != d["guide_id"]:
            why.append("canonical_url names another guide")
        rawp = cdir / "raw" / d["guide_id"] / f"{d['page_id']}.json"
        if rawp.is_file():
            r = json.loads(rawp.read_text(encoding="utf-8"))
            if r.get("guide_id") != d["guide_id"] or r.get("page_id") != d["page_id"]:
                why.append("raw cache record belongs to another guide/page")
        if not d["topic_ids"] or not set(d["topic_ids"]) <= topic_ids:
            why.append("page belongs to no target topic")
        if d["status"] == "EMPTY_CONTENT":
            why.append("empty after cleaning")
        elif len(d["text"]) < 200:
            why.append(f"very short ({len(d['text'])} chars)")
        if d["text_raw"] and len(d["text"]) < 0.6 * len(d["text_raw"]):
            why.append("cleaning removed >40% of the text")
        if not d["toc_path"] or d["toc_path"][-1] != d["page_title"]:
            why.append("toc_path does not end at the page title")
        if why:
            suspicious.append({"doc_id": d["doc_id"], "title": d["page_title"], "why": why})
    pid_guides = defaultdict(set)
    for d in docs:
        pid_guides[d["page_id"]].add(d["guide_id"])
    cross = [{"page_id": p, "guides": sorted(g)} for p, g in pid_guides.items() if len(g) > 1]
    stray_chunks = [c["chunk_id"] for c in chunks if c["topic_id"] not in topic_ids]
    http_errors = 0
    logp = cdir / "logs" / "build.jsonl"
    if logp.is_file():
        http_errors = sum(1 for l in logp.read_text(encoding="utf-8").splitlines() if '"HTTP_ERROR"' in l)
    dup_chunks = len(chunks) - len({c["text"] for c in chunks})
    blockers = []
    if not m["corpus_complete"]:
        blockers.append(m["completeness"])
    if m["failed_pages"]:
        blockers.append(f"{len(m['failed_pages'])} failed page fetch(es)")
    if m["registration_errors"]:
        blockers.append(f"{len(m['registration_errors'])} invalid registration(s)")
    if cross:
        blockers.append(f"{len(cross)} page id(s) present under more than one guide")
    if stray_chunks:
        blockers.append(f"{len(stray_chunks)} chunk(s) outside the target topics")
    if any("another guide" in w for s in suspicious for w in s["why"]):
        blockers.append("cross-guide substitution suspected")
    res = {
        "corpus_dir": a.corpus_dir, "manifest": str(mpath.relative_to(ROOT)) if mpath.is_relative_to(ROOT) else str(mpath), "corpus_fingerprint": m["corpus_fingerprint"],
        "topics_resolved": f"{sum(1 for r in m['topics'] if r['status'] == 'RESOLVED')}/{m['topics_total']}",   # page identified AND fetched/chunked
        "topics_page_identified": f"{sum(1 for r in m['topics'] if r['resolution_status'] == 'RESOLVED')}/{m['topics_total']}",   # verified TOC contains the page
        "guides_resolved": f"{sum(1 for g in m['guides'] if g['status'] == 'resolved')}/{len(m['guides'])}",
        "totals": {"page_references": T["page_references"], "unique_pages": T["unique_pages_planned"], "pages_fetched": T["pages_fetched"],
                   "duplicate_page_identities": T["duplicate_pages_identity"], "duplicate_content_pages": T["duplicate_content_pages"],
                   "cleaned_pages": sum(1 for d in docs if d["status"] == "OK"), "empty_pages": T["empty_pages"],
                   "chars_raw": T["total_chars_raw"], "chars_cleaned": T["total_chars_cleaned"], "chunks": len(chunks),
                   "duplicate_chunks_exact": dup_chunks, "failed_pages": len(m["failed_pages"]), "http_errors_logged": http_errors},
        "chunk_chars": stats([len(c["text"]) for c in chunks]),
        "per_guide": per_guide, "per_topic": per_topic,
        "pages_not_in_any_target_topic": [d["doc_id"] for d in docs if not d["topic_ids"] or not set(d["topic_ids"]) <= topic_ids],
        "chunks_outside_target_topics": stray_chunks, "cross_guide_page_ids": cross, "suspicious_pages": suspicious,
        "failed_pages": m["failed_pages"], "unresolved_topics": [{"topic_id": r["topic_id"], "status": r["status"], "guide_id": r["guide_id"]}
                                                                 for r in m["topics"] if r["status"] != "RESOLVED"],
        "shared_numeric_ids": m.get("shared_numeric_ids", {}), "ready_for_embedding": not blockers, "blockers": blockers}
    (cdir / "audit.json").write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    L = [f"# Corpus audit: `{a.corpus_dir}`", "", f"**{'READY for embedding' if not blockers else 'NOT READY: ' + '; '.join(blockers)}**", "",
         f"* topics with page identified in a verified TOC: **{res['topics_page_identified']}**   topics fetched OK (resolved + pages fetched): **{res['topics_resolved']}**   guides resolved: **{res['guides_resolved']}**   fingerprint `{m['corpus_fingerprint'][:16]}`",
         "* " + ", ".join(f"{k}={v}" for k, v in res["totals"].items()), f"* chunk chars: {res['chunk_chars']}",
         f"* pages in no target topic: {len(res['pages_not_in_any_target_topic'])}; chunks outside target topics: {len(stray_chunks)}; "
         f"cross-guide page ids: {len(cross)}; suspicious pages: {len(suspicious)}", "",
         "## Per guide", "", "| guide | status | numeric/build | topics | docs | ok | dup content | chunks | cleaned chars |", "|---|---|---|---|--:|--:|--:|--:|--:|"]
    for gid, g in per_guide.items():
        L.append(f"| `{gid[:8]}` | {g['guide_status']} | {g['numeric_deliverable_id']}/{g['build_no']} | {g['topics']} | {g['documents']} | "
                 f"{g['canonical_ok']} | {g['duplicate_content']} | {g['chunks']} | {g['cleaned_chars']} |")
    L += ["", "## Per topic", "", "| # | topic | guide | scope | pages | unique | dup pages | dup content | chunks | status |", "|--:|---|---|---|--:|--:|--:|--:|--:|---|"]
    u = lambda v: "UNKNOWN" if v is None else v
    for r in per_topic:
        L.append(f"| {r['topic_id']} | {r['topic_title']} | `{r['guide_id'][:8]}` | {r['scope']} | {u(r['page_count'])} | {u(r['unique_page_count'])} | "
                 f"{u(r['duplicate_page_count'])} | {u(r['duplicate_content_count'])} | {u(r['chunk_count'])} | {r['status']} |")
    if suspicious:
        L += ["", "## Suspicious pages", ""] + [f"* `{s['doc_id'][:8]}…/{s['doc_id'].split('/')[1][:8]}` {s['title']}: {'; '.join(s['why'])}" for s in suspicious]
    if m["failed_pages"]:
        L += ["", "## Failed pages", ""] + [f"* {f['title']}: {f['failure']} {f['error']}" for f in m["failed_pages"]]
    (cdir / "audit.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:12]))
    return 0 if not blockers else 1


if __name__ == "__main__":
    sys.exit(main())
