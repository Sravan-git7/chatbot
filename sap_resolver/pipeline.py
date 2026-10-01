"""End-to-end, deterministic corpus build for the 29 target topics.

    topic manifest (29 PDFs) -> validate -> guide registry (+ declarative registrations) -> TOC resolution ->
    topic/page resolution -> scope expansion -> fetch (cache / offline / network) -> page de-duplication ->
    cleaning -> content de-duplication -> chunking -> statistics -> final corpus manifest -> embedding input

Output tree (``out_dir``, default data/sap_help) - never sap_pages/, chunks.json or chroma_db:
    CORPUS.json                       ownership marker
    raw/<guide_id>/<page_id>.json     fetch cache: the only stage that can touch the network
    pages/<guide_id>/<page_id>.json   canonical documents (raw + cleaned text, hashes, topic refs)   [rebuilt]
    chunks/chunks.jsonl               every chunk with full identity metadata                        [rebuilt]
    chunks/embedding_input.jsonl      Chroma-ready records (id, document, scalar metadata); NOT embedded here
    corpus_stats.json, logs/build.jsonl
    <manifest_dir>/final_corpus_manifest.{json,md}

Everything after ``raw/`` is a pure function of (raw pages, manifests, registry, config): rebuilding gives
byte-identical pages/chunks/manifest (retrieved_at is carried over from the raw cache, not regenerated).
"""
from __future__ import annotations

import json
import shutil
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import events as ev
from .chunk import ChunkConfig, chunk_document, embedding_record
from .clean import clean_text, content_hash as compute_content_hash
from .dedupe import dedupe_documents, _refresh_topics
from .fetch import (FetchAborted, FetchError, HttpApiError, LegacyLocalFetcher, SapHelpApiFetcher, UnresolvedGuideError,
                    _atomic_write_json)
from .plan import ConfigError, IngestConfig, ScopeMode, assert_safe_out_dir, build_plan, storage_key
from .intake import acquire_tocs
from .registry import GuideRegistry, apply_registrations_ex, load_registrations, refresh_registry, shared_numeric_ids
from .resolver import RESOLVED, resolve_topics
from .schema import (SCHEMA_VERSION, STATUS_DUPLICATE_CONTENT, STATUS_EMPTY, STATUS_OK, doc_id, sha256_text,
                     validate_chunk, validate_page)

# topic-level statuses
S_RESOLVED, S_UNRES_GUIDE, S_UNRES_PAGE, S_FETCH_FAILED, S_EMPTY = (
    "RESOLVED", "UNRESOLVED_GUIDE", "UNRESOLVED_PAGE", "FETCH_FAILED", "EMPTY_CONTENT")
EXIT_OK, EXIT_INCOMPLETE, EXIT_FETCH_OR_REGISTRATION, EXIT_INVALID_INPUT = 0, 1, 2, 3
MARKER = "CORPUS.json"


class ManifestError(ValueError):
    pass


@dataclass
class BuildConfig:
    repo_root: Path
    out_dir: Path = Path("data/sap_help")
    manifest_dir: Path = Path("data")
    mode: str = "cache"                      # cache (no fetching) | offline (legacy local pages) | network
    ingest: IngestConfig = field(default_factory=IngestConfig)
    chunk: ChunkConfig = field(default_factory=ChunkConfig)
    require_complete: bool = False
    expected_topics: Optional[int] = 29
    refresh: bool = False                    # ignore raw cache and re-fetch
    max_consecutive_failures: int = 5
    max_retries: int = 3
    delay_s: float = 1.0
    topic_manifest: Optional[Dict[str, Any]] = None     # injected (tests); default = PDFs
    registry: Optional[Dict[str, Any]] = None           # injected (tests); default = registry file + evidence
    registry_file: Path = Path("data/guide_registry.json")
    registrations_file: Path = Path("data/guide_registrations.json")
    corrections_file: Path = Path("data/topic_corrections.json")
    fetcher: Any = None                                 # injected (tests)
    log: Optional[ev.EventLog] = None


@dataclass
class BuildResult:
    exit_code: int
    manifest: Dict[str, Any]
    events: Dict[str, int]
    messages: List[str]


def _abs(root: Path, p: Path) -> Path:
    return p if Path(p).is_absolute() else Path(root) / p


# ----------------------------------------------------------------------------- 1. manifests
def validate_topic_manifest(m: Dict[str, Any], expected: Optional[int]) -> List[str]:
    errs: List[str] = []
    topics = m.get("topics") or []
    if expected is not None and len(topics) != expected:
        errs.append(f"expected {expected} topics, manifest has {len(topics)}")
    ids = [t.get("topic_id") for t in topics]
    if len(set(ids)) != len(ids):
        errs.append("duplicate topic_id values")
    hexre = __import__("re").compile(r"^[0-9a-f]{32}$")
    for t in topics:
        for k in ("topic_id", "title", "category", "guide_id", "page_id", "canonical_url", "product"):
            if t.get(k) in (None, ""):
                errs.append(f"topic {t.get('topic_id')}: missing {k}")
        for k in ("guide_id", "page_id"):
            if t.get(k) and not hexre.match(t[k]):
                errs.append(f"topic {t.get('topic_id')}: {k} is not 32 lower-case hex")
    return errs


def load_topic_manifest(cfg: BuildConfig, log: ev.EventLog) -> Dict[str, Any]:
    if cfg.topic_manifest is not None:
        return cfg.topic_manifest
    from .pdf_cards import build_topic_manifest
    m = build_topic_manifest(cfg.repo_root, log)            # the PDFs are authoritative
    saved = _abs(cfg.repo_root, Path("data/topic_manifest.json"))
    if saved.is_file():
        old = {t["topic_id"]: (t["guide_id"], t["page_id"], t["title"]) for t in json.loads(saved.read_text(encoding="utf-8"))["topics"]}
        new = {t["topic_id"]: (t["guide_id"], t["page_id"], t["title"]) for t in m["topics"]}
        if old != new:
            log.emit(ev.PAGE_FAILED, kind="stale_topic_manifest", error="data/topic_manifest.json differs from the PDFs; PDFs used")
    return m


# ----------------------------------------------------------------------------- 2. fetch stage
class RawStore:
    def __init__(self, out_dir: Path):
        self.dir = out_dir / "raw"

    def path(self, guide_id: str, page_id: str) -> Path:
        return self.dir / storage_key(guide_id, page_id)

    def read(self, guide_id: str, page_id: str) -> Optional[Dict[str, Any]]:
        p = self.path(guide_id, page_id)
        if not p.is_file():
            return None
        rec = json.loads(p.read_text(encoding="utf-8"))
        if rec.get("guide_id") != guide_id or rec.get("page_id") != page_id or "text_raw" not in rec:
            raise ValueError(f"raw cache record {p} does not match its path (guide/page mismatch or no text)")
        return rec

    def write(self, rec: Dict[str, Any]) -> None:
        _atomic_write_json(self.path(rec["guide_id"], rec["page_id"]), rec)


def _make_fetcher(cfg: BuildConfig, registry: Dict[str, Any], log: ev.EventLog):
    if cfg.fetcher is not None:
        return cfg.fetcher
    reg = GuideRegistry(registry, cfg.repo_root)
    if cfg.mode == "offline":
        return LegacyLocalFetcher(cfg.repo_root, reg)
    if cfg.mode == "network":
        return SapHelpApiFetcher(reg, log, allow_network=True, max_retries=cfg.max_retries, delay_s=cfg.delay_s)
    return None


def fetch_pages(plan, cfg: BuildConfig, registry: Dict[str, Any], out_dir: Path, log: ev.EventLog):
    store, fetcher = RawStore(out_dir), _make_fetcher(cfg, registry, log)
    raws: Dict[str, Dict[str, Any]] = {}
    failures: List[Dict[str, Any]] = []
    consecutive, aborted = 0, False
    for e in plan.entries:
        key = e.storage_key
        try:
            cached = None if cfg.refresh else store.read(e.guide_id, e.page_id)
        except (ValueError, OSError) as ex:
            log.emit(ev.PAGE_FAILED, guide_id=e.guide_id, page_id=e.page_id, error_type="CacheCorrupt", error=str(ex))
            cached = None
        if cached is not None:
            raws[key] = cached
            log.emit(ev.PAGE_SKIPPED, guide_id=e.guide_id, page_id=e.page_id, reason="raw cache hit")
            continue

        def fail(kind: str, msg: str, count_for_breaker: bool = True):
            nonlocal consecutive
            failures.append({"guide_id": e.guide_id, "page_id": e.page_id, "file_path": e.file_path, "title": e.title,
                             "topic_ids": e.topic_ids, "failure": kind, "error": msg})
            consecutive += 1 if count_for_breaker else 0

        if aborted:
            fail("ABORTED", "skipped after too many consecutive fetch failures", False)
            continue
        if fetcher is None:
            fail("NETWORK_DISABLED", "page is not in the raw cache and neither --offline nor --allow-network was given", False)
            log.emit(ev.PAGE_FAILED, guide_id=e.guide_id, page_id=e.page_id, error_type="NETWORK_DISABLED",
                     error="not in raw cache; fetching not enabled")
            continue
        try:
            fp = fetcher.fetch_page(e)
        except HttpApiError as ex:          # HTTP_ERROR already logged per attempt by the fetcher
            fail("HTTP_ERROR", str(ex))
        except UnresolvedGuideError as ex:
            fail("GUIDE_IDS_UNKNOWN", str(ex), False)
            log.emit(ev.PAGE_FAILED, guide_id=e.guide_id, page_id=e.page_id, error_type="UnresolvedGuideError", error=str(ex))
        except FetchError as ex:
            fail(type(ex).__name__, str(ex))
            log.emit(ev.PAGE_FAILED, guide_id=e.guide_id, page_id=e.page_id, file_path=e.file_path,
                     error_type=type(ex).__name__, error=str(ex))
        else:
            consecutive = 0
            rec = {"schema_version": SCHEMA_VERSION, "guide_id": e.guide_id, "page_id": e.page_id, "file_path": e.file_path,
                   "page_title": e.title, "text_raw": fp.text, "page_hash": sha256_text(fp.text),
                   "retrieved_at": fp.retrieved_at, "source_type": fp.source_type, "fetched_via": fp.fetched_via,
                   "current_page": fp.current_page}
            try:
                store.write(rec)
            except OSError as ex:
                fail("WRITE_ERROR", str(ex))
                log.emit(ev.PAGE_FAILED, guide_id=e.guide_id, page_id=e.page_id, error_type="OSError", error=str(ex))
                continue
            raws[key] = rec
            log.emit(ev.PAGE_STORED, guide_id=e.guide_id, page_id=e.page_id, storage_key=key, chars=len(fp.text))
        if consecutive >= cfg.max_consecutive_failures and cfg.mode == "network" and not aborted:
            aborted = True
            log.emit(ev.PAGE_FAILED, error_type="FetchAborted",
                     error=f"{consecutive} consecutive failures; stopping network fetching (no retries beyond policy)")
    return raws, failures


# ----------------------------------------------------------------------------- 3. documents
def make_documents(plan, raws, registry, topics_by_id) -> List[Dict[str, Any]]:
    docs = []
    for e in plan.entries:
        raw = raws.get(e.storage_key)
        if raw is None:
            continue
        g = registry["guides"].get(e.guide_id, {})
        cr = clean_text(raw["text_raw"], e.title)
        refs = [{"topic_id": tid, "topic_title": topics_by_id[tid]["title"], "role": role, "via_doc_id": None,
                 "pdf_file": topics_by_id[tid]["pdf_file"]} for tid, role in sorted(e.topic_roles.items())]
        card_topics = [tid for tid, role in sorted(e.topic_roles.items()) if role == "topic_page"]
        source_url = (topics_by_id[card_topics[0]]["canonical_url"] if topics_by_id[card_topics[0]].get("correction")
                      else topics_by_id[card_topics[0]]["url_as_given"]) if card_topics else e.canonical_url
        doc = {
            "schema_version": SCHEMA_VERSION, "doc_id": doc_id(e.guide_id, e.page_id),
            "topic_id": None, "topic_title": None, "topic_ids": [], "topic_refs": refs,
            "guide_id": e.guide_id, "numeric_deliverable_id": g.get("numeric_deliverable_id"), "build_no": g.get("build_no"),
            "page_id": e.page_id, "file_path": e.file_path, "alias_file_paths": list(e.alias_file_paths),
            "parent_page_id": e.parent_page_id, "toc_path": list(e.toc_path), "depth": e.depth, "page_title": e.title,
            "source_url": source_url, "canonical_url": e.canonical_url, "retrieved_at": raw.get("retrieved_at"),
            "source_type": raw.get("source_type"), "fetched_via": raw.get("fetched_via"),
            "page_hash": raw.get("page_hash") or sha256_text(raw["text_raw"]),
            "content_hash": compute_content_hash(cr.text), "duplicate_of": None, "duplicate_docs": [],
            "text_raw": raw["text_raw"], "text": cr.text, "clean_stats": cr.stats,
            "status": STATUS_OK if cr.text else STATUS_EMPTY}
        _refresh_topics(doc)
        docs.append(doc)
    return docs


# ----------------------------------------------------------------------------- 4. statistics & manifest
def _len_stats(vals: List[int]) -> Dict[str, Any]:
    if not vals:
        return {"count": 0, "total": 0, "mean": None, "median": None, "min": None, "max": None}
    return {"count": len(vals), "total": sum(vals), "mean": round(statistics.mean(vals), 1),
            "median": statistics.median(vals), "min": min(vals), "max": max(vals)}


def _topic_status(res, n_failed: int, n_chunks: int) -> str:
    if res.status != RESOLVED:
        return S_UNRES_PAGE if res.reason == "PAGE_NOT_IN_TOC" else S_UNRES_GUIDE
    if n_failed:
        return S_FETCH_FAILED
    return S_EMPTY if n_chunks == 0 else S_RESOLVED


def build_final_manifest(cfg, scope_cfg, topics, resolutions, guides, registry, plan, docs, chunks, failures,
                         reg_errors, refs_by_topic, out_dir, stats, pending_regs=()) -> Dict[str, Any]:
    chunks_by_doc = Counter(c["doc_id"] for c in chunks)
    rows = []
    for r in resolutions:
        t = next(x for x in topics if x["topic_id"] == r.topic_id)
        base = {"topic_id": r.topic_id, "topic_title": r.title, "guide_id": r.guide_id, "pdf_file": r.source_pdf,
                "page_id": r.page_id, "canonical_url": r.canonical_url,
                "resolution_status": (S_RESOLVED if r.status == RESOLVED else
                                      S_UNRES_PAGE if r.reason == "PAGE_NOT_IN_TOC" else S_UNRES_GUIDE),
                "resolution_reason": r.reason, "scope": scope_cfg.scope_for(r.topic_id).value,
                "max_depth": scope_cfg.max_depth if scope_cfg.scope_for(r.topic_id) is ScopeMode.PAGE_AND_DESCENDANTS else None}
        if r.correction:
            base["card_guide_id"] = r.card_guide_id
            base["correction"] = {k: v for k, v in r.correction.items() if not k.startswith("_")}
        if r.status != RESOLVED:
            rows.append({**base, "pages_known": False, "page_count": None, "unique_page_count": None,
                         "duplicate_page_count": None, "duplicate_content_count": None, "failed_page_count": None,
                         "empty_page_count": None, "chunk_count": None, "status": base["resolution_status"],
                         "note": "page/chunk counts are UNKNOWN (not zero): the guide/page cannot be resolved yet"
                                 + (f"; {r.candidate_note}" if r.candidate_note else "")})
            continue
        mine_docs = [d for d in docs if r.topic_id in d["topic_ids"]]
        entries = [e for e in plan.entries if r.topic_id in e.topic_roles]
        failed = [f for f in failures if r.topic_id in f["topic_ids"]]
        n_chunks = sum(chunks_by_doc[d["doc_id"]] for d in mine_docs)
        refs = refs_by_topic[r.topic_id]
        st = _topic_status(r, len(failed), n_chunks)
        warnings = []
        top_doc = next((d for d in docs if d["page_id"] == r.page_id and d["guide_id"] == r.guide_id), None)
        if top_doc is not None and top_doc["status"] == STATUS_EMPTY:
            warnings.append("topic page itself has no text")
        rows.append({**base, "pages_known": True, "page_count": refs, "unique_page_count": len(entries),
                     "duplicate_page_count": refs - len(entries),
                     "duplicate_content_count": sum(1 for d in mine_docs if d["status"] == STATUS_DUPLICATE_CONTENT),
                     "failed_page_count": len(failed), "empty_page_count": sum(1 for d in mine_docs if d["status"] == STATUS_EMPTY),
                     "chunk_count": n_chunks, "status": st,
                     "failed_pages": [{k: f[k] for k in ("page_id", "title", "failure", "error")} for f in failed],
                     "warnings": warnings})
    status_counts = dict(sorted(Counter(r["status"] for r in rows).items()))
    complete = all(r["status"] == S_RESOLVED for r in rows) and len(rows) == (cfg.expected_topics or len(rows))
    def missing_for(gid):
        e = registry["guides"].get(gid) or {}
        miss = []
        if not e.get("toc_file"):
            miss.append("toc_file (saved pagecontent?deliverableInfo=1 response, or --allow-network to download it)")
        if not (e.get("numeric_deliverable_id") and e.get("build_no")):
            miss.append("numeric_id + build_no")
        return miss
    unresolved_guides = [{"guide_id": g.guide_id, "reason": g.reason, "topic_ids": g.topic_ids,
                          "fetch_ready": g.fetch_ready, "missing": missing_for(g.guide_id)} for g in guides if g.status != RESOLVED]
    reasons = []
    if unresolved_guides:
        reasons.append(f"{len(unresolved_guides)} guide(s) unresolved (no saved TOC): "
                       + ", ".join(g["guide_id"][:8] for g in unresolved_guides))
    for k in (S_UNRES_PAGE, S_FETCH_FAILED, S_EMPTY):
        if status_counts.get(k):
            reasons.append(f"{status_counts[k]} topic(s) {k}")
    if reg_errors:
        reasons.append(f"{len(reg_errors)} invalid guide registration(s)")
    fingerprint = sha256_text("\n".join(f"{c['chunk_id']}:{c['chunk_hash']}" for c in chunks))
    docs_summary = [{"doc_id": d["doc_id"], "page_title": d["page_title"], "topic_ids": d["topic_ids"], "status": d["status"],
                     "duplicate_of": d["duplicate_of"], "chunks": chunks_by_doc[d["doc_id"]], "chars": len(d["text"]),
                     "path": f"pages/{d['doc_id']}.json"} for d in docs]
    return {
        "manifest_schema_version": SCHEMA_VERSION,
        "corpus_complete": complete,
        "completeness": ("COMPLETE: all topics RESOLVED" if complete else
                         "INCOMPLETE: " + ("; ".join(reasons) if reasons else "see topic statuses")),
        "corpus_fingerprint": fingerprint,
        "topics_total": len(rows), "topic_status_counts": status_counts,
        "unresolved_guides": unresolved_guides, "registration_errors": reg_errors,
        "pending_registrations": list(pending_regs),
        "topic_corrections": [{"topic_id": r.topic_id, "card_guide_id": r.card_guide_id, "resolved_guide_id": r.guide_id,
                               "page_id": r.page_id, "resolution_status": "RESOLVED" if r.status == RESOLVED else "UNRESOLVED",
                               "resolution_reason": r.reason,
                               "evidence": [{k: v for k, v in e.items() if not k.startswith("_")} for e in r.correction.get("evidence", [])],
                               "reason": r.correction.get("reason")} for r in resolutions if r.correction],
        "shared_numeric_ids": shared_numeric_ids(registry),
        "totals": stats["totals"],
        "config": {"mode": cfg.mode, "default_scope": scope_cfg.default_scope.value,
                   "topic_scope_overrides": {str(k): v.value for k, v in sorted(scope_cfg.topic_scopes.items())},
                   "max_depth": scope_cfg.max_depth, "chunking": cfg.chunk.to_dict(), "expected_topics": cfg.expected_topics},
        "isolation": {"corpus_dir": str(out_dir.relative_to(cfg.repo_root)) if out_dir.is_relative_to(cfg.repo_root) else str(out_dir),
                      "legacy_untouched": ["sap_pages/", "chunks.json", "cleaned_pages.json", "chroma_db/"]},
        "guides": [{"guide_id": g.guide_id, "status": g.status, "reason": g.reason, "topic_ids": g.topic_ids,
                    "toc_nodes": g.toc_nodes, "fetch_ready": g.fetch_ready,
                    "numeric_deliverable_id": (registry["guides"].get(g.guide_id) or {}).get("numeric_deliverable_id"),
                    "build_no": (registry["guides"].get(g.guide_id) or {}).get("build_no")} for g in guides],
        "topics": rows,
        "failed_pages": failures,
        "documents": docs_summary,
    }


def manifest_markdown(m: Dict[str, Any]) -> str:
    T = m["totals"]
    L = ["# Final corpus manifest", "", f"**{m['completeness']}**", "",
         f"* corpus_complete: `{m['corpus_complete']}`  * fingerprint: `{m['corpus_fingerprint'][:16]}…`  * mode: `{m['config']['mode']}`",
         f"* default scope: `{m['config']['default_scope']}`  overrides: `{m['config']['topic_scope_overrides']}`  max_depth: `{m['config']['max_depth']}`",
         f"* corpus dir: `{m['isolation']['corpus_dir']}` (legacy `sap_pages/`, `chunks.json`, `chroma_db/` untouched)", "",
         "## Totals (resolved topics only; UNKNOWN topics are not counted as zero)", "", "| metric | value |", "|---|---:|"]
    for k, v in T.items():
        if not isinstance(v, (dict, list)):
            L.append(f"| {k} | {v} |")
    L += ["", "Topic status counts: " + ", ".join(f"`{k}`={v}" for k, v in m["topic_status_counts"].items()), "",
          "## Topics", "", "| # | topic | guide | resolution | scope | pages | unique | dup pages | dup content | chunks | status |",
          "|--:|---|---|---|---|--:|--:|--:|--:|--:|---|"]
    u = lambda v: "UNKNOWN" if v is None else v
    for r in m["topics"]:
        L.append(f"| {r['topic_id']} | {r['topic_title']} | `{r['guide_id'][:8]}` | {r['resolution_status']} | {r['scope']} | "
                 f"{u(r['page_count'])} | {u(r['unique_page_count'])} | {u(r['duplicate_page_count'])} | "
                 f"{u(r['duplicate_content_count'])} | {u(r['chunk_count'])} | **{r['status']}** |")
    L += ["", "## Guides", "", "| guide | status | reason | topics | numeric id | build | fetch ready |", "|---|---|---|---|---|---|---|"]
    for g in m["guides"]:
        L.append(f"| `{g['guide_id']}` | {g['status']} | {g['reason'] or ''} | {g['topic_ids']} | "
                 f"{g['numeric_deliverable_id'] or 'UNKNOWN'} | {g['build_no'] or 'UNKNOWN'} | {g['fetch_ready']} |")
    if m["failed_pages"]:
        L += ["", "## Failed pages", ""] + [f"* `{f['guide_id'][:8]}/{f['page_id'][:8]}` {f['title']}: **{f['failure']}** {f['error']}" for f in m["failed_pages"]]
    if m.get("unresolved_guides"):
        L += ["", "## Unresolved guides (what is still needed)", ""] + [
            f"* `{g['guide_id']}` topics {g['topic_ids']}: " + "; ".join(g["missing"]) for g in m["unresolved_guides"]]
    if m.get("pending_registrations"):
        L += ["", "## Pending registrations", ""] + [
            f"* `{g['guide_id'][:8]}` {g['state']}: missing {', '.join(g['missing'])}" for g in m["pending_registrations"]]
    if m["registration_errors"]:
        L += ["", "## Invalid registrations", ""] + [f"* {e}" for e in m["registration_errors"]]
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------------- 5. orchestration
def _prepare_out_dir(cfg: BuildConfig, out_dir: Path) -> None:
    assert_safe_out_dir(out_dir, cfg.repo_root)
    if out_dir.name == "data" and out_dir.parent == Path(cfg.repo_root).resolve():
        raise ConfigError("out_dir must not be the data/ directory itself")
    marker = out_dir / MARKER
    if out_dir.exists() and any(out_dir.iterdir()) and not marker.is_file():
        raise ConfigError(f"{out_dir} exists, is not empty and is not a corpus directory (no {MARKER}); refusing to use it")
    out_dir.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"kind": "sap_help_target_corpus", "schema_version": SCHEMA_VERSION}) + "\n", encoding="utf-8")
    for sub in ("pages", "chunks"):            # derived artefacts are rebuilt from scratch; raw/ (the fetch cache) is kept
        shutil.rmtree(out_dir / sub, ignore_errors=True)


def build_corpus(cfg: BuildConfig) -> BuildResult:
    root = Path(cfg.repo_root).resolve()
    cfg.repo_root = root
    out_dir = _abs(root, cfg.out_dir).resolve()
    manifest_dir = _abs(root, cfg.manifest_dir).resolve()
    if cfg.mode not in ("cache", "offline", "network"):
        raise ConfigError("mode must be cache|offline|network")
    cfg.chunk.validate()
    _prepare_out_dir(cfg, out_dir)
    log = cfg.log or ev.EventLog(out_dir / "logs" / "build.jsonl")
    msgs: List[str] = []

    # validate manifests
    topic_manifest = load_topic_manifest(cfg, log)
    errs = validate_topic_manifest(topic_manifest, cfg.expected_topics)
    if errs:
        raise ManifestError("; ".join(errs))
    from .corrections import apply_corrections, load_corrections
    topics, applied_corrections, rejected_corrections = apply_corrections(
        topic_manifest["topics"], load_corrections(_abs(root, cfg.corrections_file)), root)
    topics_by_id = {t["topic_id"]: t for t in topics}
    for c in applied_corrections:
        log.emit(ev.TOPIC_CORRECTED, topic_id=c["topic_id"], card_guide_id=c["card_guide_id"],
                 resolved_guide_id=c["resolved_guide_id"], card_page_id=c["card_page_id"])
        msgs.append(f"topic {c['topic_id']}: card guide {c['card_guide_id'][:8]} corrected to {c['resolved_guide_id'][:8]} (evidence attached)")

    # resolve guides
    if cfg.registry is not None:
        registry = json.loads(json.dumps(cfg.registry))
    else:
        rf = _abs(root, cfg.registry_file)
        existing = json.loads(rf.read_text(encoding="utf-8")) if rf.is_file() else None
        registry = refresh_registry(topic_manifest, root, existing)
    registrations = load_registrations(_abs(root, cfg.registrations_file))
    toc_errors: List[Dict[str, Any]] = []
    if cfg.mode == "network":           # one verified TOC request per guide that has ids but no saved TOC
        def toc_fetcher(temp_registry):
            if cfg.fetcher is not None and hasattr(cfg.fetcher, "fetch_toc_response"):
                return cfg.fetcher
            return SapHelpApiFetcher(GuideRegistry(temp_registry, root), log, allow_network=True,
                                     max_retries=cfg.max_retries, delay_s=cfg.delay_s)
        _, toc_errors = acquire_tocs(registrations, topic_manifest, root, toc_fetcher, log)
        for er in toc_errors:
            log.emit(ev.PAGE_FAILED, kind="toc_acquisition", **er)
            msgs.append(f"guide TOC acquisition failed: {er}")
    registry, reg_errors, pending_regs = apply_registrations_ex(registry, topic_manifest, registrations, root)
    reg_errors = reg_errors + [{"registration_index": None, **e} for e in toc_errors]
    reg_errors = reg_errors + [{"registration_index": None, "kind": "topic_correction_rejected", **rj} for rj in rejected_corrections]
    for er in reg_errors:
        log.emit(ev.PAGE_FAILED, kind="guide_registration", **er)
        msgs.append(f"invalid guide registration: {er}")

    # resolve topics + expand scope
    resolutions, guides, trees = resolve_topics(topics, GuideRegistry(registry, root), log)
    plan = build_plan(resolutions, trees, topics_by_id, cfg.ingest, log)
    refs_by_topic: Dict[int, int] = {}
    for r in resolutions:
        if r.status == RESOLVED:
            top = trees[r.guide_id].nodes[r.node_file_path]
            n = 1
            if cfg.ingest.scope_for(r.topic_id) is ScopeMode.PAGE_AND_DESCENDANTS:
                n += len(list(trees[r.guide_id].descendants(top, cfg.ingest.max_depth)))
            refs_by_topic[r.topic_id] = n

    # fetch -> documents -> dedupe -> chunk
    raws, failures = fetch_pages(plan, cfg, registry, out_dir, log)
    docs = make_documents(plan, raws, registry, topics_by_id)
    dedupe_documents(docs, log)
    chunks: List[Dict[str, Any]] = []
    for d in docs:
        if d["status"] == STATUS_OK:
            chunks.extend(chunk_document(d, cfg.chunk))
    schema_errors = [f"{d['doc_id']}: {e}" for d in docs for e in validate_page(d)] + \
                    [f"{c['chunk_id']}: {e}" for c in chunks for e in validate_chunk(c)]

    # write artefacts
    for d in docs:
        _atomic_write_json(out_dir / "pages" / f"{d['doc_id']}.json", d)
    (out_dir / "chunks").mkdir(parents=True, exist_ok=True)
    with (out_dir / "chunks" / "chunks.jsonl").open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n")
    with (out_dir / "chunks" / "embedding_input.jsonl").open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(embedding_record(c, cfg.chunk.embedding_context), ensure_ascii=False, sort_keys=True) + "\n")

    # statistics
    lens = [len(c["text"]) for c in chunks]
    cpt, ppt = Counter(), Counter()
    by_doc = Counter(c["doc_id"] for c in chunks)
    for d in docs:
        for t in d["topic_ids"]:
            ppt[t] += 1
            cpt[t] += by_doc[d["doc_id"]]
    refs_total = sum(refs_by_topic.values())
    totals = {
        "topics_resolved": sum(1 for r in resolutions if r.status == RESOLVED), "topics_unresolved": sum(1 for r in resolutions if r.status != RESOLVED),
        "page_references": refs_total, "unique_pages_planned": len(plan.entries), "pages_fetched": len(raws),
        "pages_failed": len(failures), "duplicate_pages_identity": refs_total - len(plan.entries),
        "duplicate_content_pages": sum(1 for d in docs if d["status"] == STATUS_DUPLICATE_CONTENT),
        "empty_pages": sum(1 for d in docs if d["status"] == STATUS_EMPTY),
        "canonical_documents_chunked": sum(1 for d in docs if d["status"] == STATUS_OK),
        "total_chars_raw": sum(len(d["text_raw"]) for d in docs), "total_chars_cleaned": sum(len(d["text"]) for d in docs),
        "total_chunks": len(chunks), "avg_chunk_chars": round(statistics.mean(lens), 1) if lens else None,
        "median_chunk_chars": statistics.median(lens) if lens else None,
        "min_chunk_chars": min(lens) if lens else None, "max_chunk_chars": max(lens) if lens else None,
        "duplicate_chunks_exact": len(chunks) - len({c["text"] for c in chunks}),
    }
    stats = {"totals": totals, "chunk_length": _len_stats(lens),
             "chunks_per_topic": {str(k): v for k, v in sorted(cpt.items())},
             "pages_per_topic": {str(k): v for k, v in sorted(ppt.items())},
             "chunks_per_page": _len_stats([by_doc[d["doc_id"]] for d in docs if d["status"] == STATUS_OK])}
    _atomic_write_json(out_dir / "corpus_stats.json", stats)

    manifest = build_final_manifest(cfg, cfg.ingest, topics, resolutions, guides, registry, plan, docs, chunks, failures,
                                    reg_errors, refs_by_topic, out_dir, stats, pending_regs)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "final_corpus_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (manifest_dir / "final_corpus_manifest.md").write_text(manifest_markdown(manifest), encoding="utf-8")

    code = EXIT_OK
    if schema_errors:
        msgs += [f"schema error: {e}" for e in schema_errors[:10]]
        code = EXIT_FETCH_OR_REGISTRATION
    if failures:
        msgs.append(f"{len(failures)} planned page(s) could NOT be fetched - corpus is partial (see failed_pages)")
        code = EXIT_FETCH_OR_REGISTRATION
    if reg_errors:
        code = EXIT_FETCH_OR_REGISTRATION
    if not manifest["corpus_complete"]:
        msgs.append(manifest["completeness"])
        if cfg.require_complete and code == EXIT_OK:
            code = EXIT_INCOMPLETE
    return BuildResult(code, manifest, log.counts(), msgs)
