"""PHASES 6-7 (read-only w.r.t. the RAG corpus): target-corpus audit.

Builds both ingestion plans (page_only / page_and_descendants) from the resolver,
then audits them against the legacy corpus. Writes ONLY:
    data/ingest_plan_page_only.json
    data/ingest_plan_page_and_descendants.json
    data/corpus_audit.json / data/corpus_audit.md
    data/logs/corpus_audit.jsonl
It never writes sap_pages/, chunks.json, chroma_db or data/sap_help/ and makes no network request.

Anything that cannot be proven is reported as UNKNOWN, never as 0 or an extrapolation.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from sap_resolver import events as ev                                   # noqa: E402
from sap_resolver.plan import IngestConfig, ScopeMode, build_plan       # noqa: E402
from sap_resolver.registry import GuideRegistry                         # noqa: E402
from sap_resolver.resolver import RESOLVED, resolve_topics              # noqa: E402

DATA = ROOT / "data"
UNKNOWN = "UNKNOWN"


def load(p):
    return json.loads((ROOT / p).read_text(encoding="utf-8"))


def legacy_index():
    """file_path -> {sap_pages no., chunks, url}; plus duplicate-chunk accounting."""
    chunks = load("chunks.json")
    per_url = Counter(c["url"] for c in chunks)
    seen, dup_chunks = set(), 0
    for c in chunks:
        if c["text"] in seen:
            dup_chunks += 1
        seen.add(c["text"])
    pages = {}
    text_seen = {}
    dup_pages = 0
    for i in range(1, 82):
        p = load(f"sap_pages/{i:03d}.json")
        is_dup_text = p["text"] in text_seen
        dup_pages += is_dup_text
        text_seen.setdefault(p["text"], i)
        pages[p["file_path"]] = {"sap_pages_no": i, "title": p["title"], "chunks": per_url[p["source_url"]],
                                 "duplicate_text_of": text_seen[p["text"]] if is_dup_text else None}
    return pages, len(chunks), dup_chunks, dup_pages, len(chunks) - dup_chunks


def main():
    log = ev.EventLog(DATA / "logs" / "corpus_audit.jsonl")
    man = load("data/topic_manifest.json")
    topics = {t["topic_id"]: t for t in man["topics"]}
    reg = GuideRegistry.load(DATA / "guide_registry.json", ROOT)
    res, guides, trees = resolve_topics(man["topics"], reg, log)
    resd = {r.topic_id: r for r in res}
    legacy, n_chunks, dup_chunks, dup_pages, uniq_chunks = legacy_index()
    audit_manifest = load("data/corpus_manifest.json") if (DATA / "corpus_manifest.json").is_file() else None
    heuristic = {t["topic_no"]: set(t["related_pages_union"]) for t in audit_manifest["topics"]} if audit_manifest else {}
    heuristic_pages = set().union(*heuristic.values()) if heuristic else set()

    out = {"legacy_corpus": {}, "plans": {}, "guides": [], "topics": {}}
    unique_legacy_pages = len({v["duplicate_text_of"] or v["sap_pages_no"] for v in legacy.values()})
    out["legacy_corpus"] = {"pages": len(legacy), "unique_pages_by_text": unique_legacy_pages,
                            "duplicate_pages": dup_pages, "chunks": n_chunks, "duplicate_chunks": dup_chunks,
                            "unique_chunks": uniq_chunks}

    for scope in (ScopeMode.PAGE_ONLY, ScopeMode.PAGE_AND_DESCENDANTS):
        cfg = IngestConfig(default_scope=scope, out_dir="data/sap_help")
        plog = ev.EventLog()
        plan = build_plan(res, trees, topics, cfg, plog)
        (DATA / f"ingest_plan_{scope.value}.json").write_text(
            json.dumps(plan.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        rows, refs_total = [], 0
        for tid in sorted(topics):
            r = resd[tid]
            t = topics[tid]
            base = {"topic_id": tid, "title": t["title"], "guide_id": t["guide_id"], "page_id": t["page_id"],
                    "url": t["canonical_url"], "retrieval_scope": scope.value}
            if r.status != RESOLVED:
                rows.append({**base, "status": f"UNRESOLVED ({r.reason})", "pages": UNKNOWN, "unique_pages": UNKNOWN,
                             "duplicate_pages": UNKNOWN, "chunks": UNKNOWN,
                             "legacy_pages_related_by_title_unconfirmed": sorted(heuristic.get(tid, [])) or None})
                continue
            tree = trees[r.guide_id]
            top = tree.nodes[r.node_file_path]
            nodes = [top] + (list(tree.descendants(top, cfg.max_depth)) if scope is ScopeMode.PAGE_AND_DESCENDANTS else [])
            refs = len(nodes)
            mine = [e for e in plan.entries if tid in e.topic_roles]
            in_legacy = [e for e in mine if e.file_path in legacy or any(a in legacy for a in e.alias_file_paths)]
            chunks_known = sum(legacy[e.file_path]["chunks"] for e in in_legacy if e.file_path in legacy)
            refs_total += refs
            rows.append({**base, "status": "RESOLVED", "pages": refs, "unique_pages": len(mine),
                         "duplicate_pages": refs - len(mine),
                         "chunks": chunks_known if len(in_legacy) == len(mine) else UNKNOWN,
                         "chunks_basis": "existing legacy chunks.json chunks of exactly these pages (current chunker)",
                         "pages_with_local_text": len(in_legacy),
                         "legacy_sap_pages_nos": sorted(legacy[e.file_path]["sap_pages_no"] for e in in_legacy if e.file_path in legacy)})
        resolved_rows = [x for x in rows if x["status"] == "RESOLVED"]
        planned_files = {e.file_path for e in plan.entries}
        legacy_in_target = {fp for fp in legacy if fp in planned_files}
        chunks_in_target = sum(legacy[fp]["chunks"] for fp in legacy_in_target)
        out["plans"][scope.value] = {
            "topics_total": 29, "topics_resolved": len(resolved_rows), "topics_unresolved": 29 - len(resolved_rows),
            "topics_with_zero_CONFIRMED_pages": 29 - len(resolved_rows),
            "topics_proven_to_have_zero_pages": 0,
            "page_references": refs_total if resolved_rows else 0,
            "unique_pages": len(plan.entries),
            "duplicate_pages": refs_total - len(plan.entries),
            "estimated_chunks_for_resolved_topics": sum(x["chunks"] for x in resolved_rows if x["chunks"] != UNKNOWN),
            "estimated_chunks_for_unresolved_topics": UNKNOWN,
            "duplicate_chunks_in_plan": 0 if refs_total == len(plan.entries) else UNKNOWN,
            "legacy_pages_inside_confirmed_target": len(legacy_in_target),
            "legacy_pages_outside_confirmed_target": len(legacy) - len(legacy_in_target),
            "legacy_chunks_inside_confirmed_target": chunks_in_target,
            "legacy_chunks_outside_confirmed_target": n_chunks - chunks_in_target,
            "legacy_pages_related_by_title_only_unconfirmed": len(heuristic_pages - {legacy[fp]["sap_pages_no"] for fp in legacy_in_target}),
            "legacy_pages_unrelated_even_by_title": len(set(range(1, 82)) - heuristic_pages - {legacy[fp]["sap_pages_no"] for fp in legacy_in_target}),
            "plan_file": f"data/ingest_plan_{scope.value}.json",
            "plan_events": plog.counts(),
            "skipped_unresolved_topic_ids": [s["topic_id"] for s in plan.skipped_topics],
        }
        out["topics"][scope.value] = rows
    out["guides"] = [{
        "guide_id": g.guide_id, "topic_ids": g.topic_ids,
        "numeric_id": (reg.get(g.guide_id) or {}).get("numeric_deliverable_id") or UNKNOWN,
        "build_number": (reg.get(g.guide_id) or {}).get("build_no") or UNKNOWN,
        "toc_available": g.status == RESOLVED,
        "evidence_source": (reg.get(g.guide_id) or {}).get("evidence", [])} for g in guides]
    (DATA / "corpus_audit.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # ---- markdown
    L = ["# Target-corpus audit (29 topics)", "",
         "Generated by `scripts/corpus_audit.py`. Local files only; no network. UNKNOWN = cannot be proven locally.", "",
         "## Legacy corpus", "", "| metric | value |", "|---|---:|"]
    L += [f"| {k} | {v} |" for k, v in out["legacy_corpus"].items()]
    L += ["", "## 7-guide mapping", "", "| guide_id | topics | numeric_id | build_number | TOC_available | evidence_source |", "|---|---|---|---|---|---|"]
    for g in out["guides"]:
        ev_txt = "; ".join(g["evidence_source"])[:230] if g["toc_available"] else "none found (card URL only)"
        L.append(f"| `{g['guide_id']}` | {g['topic_ids']} | {g['numeric_id']} | {g['build_number']} | {g['toc_available']} | {ev_txt} |")
    for scope, p in out["plans"].items():
        L += ["", f"## Plan: {scope}", "", "| metric | value |", "|---|---:|"]
        L += [f"| {k} | {v} |" for k, v in p.items() if k not in ("plan_events", "skipped_unresolved_topic_ids")]
        L += ["", "| topic | title | guide | page_id | scope | pages | unique | dup | chunks | status |", "|--:|---|---|---|---|--:|--:|--:|--:|---|"]
        for r in out["topics"][scope]:
            L.append(f"| {r['topic_id']} | {r['title']} | `{r['guide_id'][:8]}` | `{r['page_id'][:8]}` | {r['retrieval_scope']} | "
                     f"{r['pages']} | {r['unique_pages']} | {r['duplicate_pages']} | {r['chunks']} | {r['status']} |")
    (DATA / "corpus_audit.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(json.dumps({"legacy": out["legacy_corpus"], **{k: {kk: vv for kk, vv in v.items() if kk not in ("plan_events", "skipped_unresolved_topic_ids")} for k, v in out["plans"].items()}}, indent=1))


if __name__ == "__main__":
    main()
