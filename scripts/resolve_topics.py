"""CLI for the 29-topic manifest / multi-guide resolver / ingestion plan.

Run from the repository root (PowerShell or bash):

    python scripts/resolve_topics.py all                 # manifest + registry + resolution + plan (offline)
    python scripts/resolve_topics.py manifest            # 29 PDFs -> data/topic_manifest.json
    python scripts/resolve_topics.py registry            # -> data/guide_registry.json
    python scripts/resolve_topics.py resolve             # -> data/topic_resolution.json
    python scripts/resolve_topics.py plan --scope page_and_descendants
    python scripts/resolve_topics.py register-guide --toc-file saved_response.json [--numeric-id N --build-no B]
    python scripts/build_corpus.py --offline        # (replaces the old `ingest` command)

Nothing here touches ChromaDB, the `sap_docs` collection, sap_pages/, chunks.json or any
retrieval / LLM code. `ingest` needs a resolved topic; network is OFF unless --allow-network
and only works for guides whose numeric deliverable id + build number are in the registry.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from sap_resolver import events as ev                                   # noqa: E402
from sap_resolver.fetch import LegacyLocalFetcher, SapHelpApiFetcher, ingest_plan   # noqa: E402
from sap_resolver.pdf_cards import build_topic_manifest                 # noqa: E402
from sap_resolver.plan import IngestConfig, ScopeMode, build_plan       # noqa: E402
from sap_resolver.registry import GuideRegistry, refresh_registry, register_guide   # noqa: E402
from sap_resolver.resolver import resolve_topics, summarize             # noqa: E402

DATA = ROOT / "data"
MANIFEST = DATA / "topic_manifest.json"
REGISTRY = DATA / "guide_registry.json"
RESOLUTION = DATA / "topic_resolution.json"
PLAN = DATA / "ingest_plan.json"
CONFIG = DATA / "ingest_config.json"
LOG = DATA / "logs" / "resolution.jsonl"


def _dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}")


def _load(path: Path):
    if not path.is_file():
        sys.exit(f"missing {path.relative_to(ROOT)}; run the earlier step first (or `all`)")
    return json.loads(path.read_text(encoding="utf-8"))


def cmd_manifest(log):
    m = build_topic_manifest(ROOT, log)
    _dump(MANIFEST, m)
    print(f"{m['topic_count']} topics, {m['guide_count']} guides")


def cmd_registry(log):
    m = _load(MANIFEST)
    existing = json.loads(REGISTRY.read_text(encoding="utf-8")) if REGISTRY.is_file() else None
    _dump(REGISTRY, refresh_registry(m, ROOT, existing))


_MEMO = {}   # resolve once per CLI run so `all` does not log every event twice


def cmd_register(args):
    if not args.toc_file:
        sys.exit("register-guide needs --toc-file")
    resp = json.loads(Path(args.toc_file).read_text(encoding="utf-8"))
    reg = _load(REGISTRY)
    man = _load(MANIFEST)
    from sap_resolver.toc import TocTree
    loio = TocTree.from_pagecontent_response(resp).guide_id
    reg = register_guide(reg, man, resp, DATA / "toc" / f"{loio}.json", ROOT, args.numeric_id, args.build_no, args.evidence)
    _dump(REGISTRY, reg)
    print(f"registered guide {loio}; run `resolve` / `plan` to regenerate outputs")


def _resolve(log):
    if "r" not in _MEMO:
        m = _load(MANIFEST)
        reg = GuideRegistry.load(REGISTRY, ROOT) if REGISTRY.is_file() else sys.exit("run `registry` first")
        _MEMO["r"] = (m, reg, resolve_topics(m["topics"], reg, log))
    return _MEMO["r"]


def cmd_resolve(log):
    m, reg, (res, guides, trees) = _resolve(log)
    s = summarize(res, guides)
    _dump(RESOLUTION, {"summary": s, "guides": [g.to_dict() for g in guides],
                       "topics": [r.to_dict() for r in res]})
    print(json.dumps(s, indent=2))


def _config(args) -> IngestConfig:
    cfg = IngestConfig.load(CONFIG)
    if args.scope:
        cfg.default_scope = ScopeMode(args.scope)
    if args.max_depth:
        cfg.max_depth = args.max_depth
    return cfg


def cmd_plan(log, args):
    m, reg, (res, guides, trees) = _resolve(log)
    plan = build_plan(res, trees, {t["topic_id"]: t for t in m["topics"]}, _config(args), log)
    _dump(PLAN, plan.to_dict())
    print(f"scope={plan.config.default_scope.value}: {len(plan.entries)} page(s) planned, "
          f"{len(plan.skipped_topics)} topic(s) skipped as unresolved")
    return m, reg, plan


def cmd_ingest(log, args):
    sys.exit("`ingest` is superseded by the full pipeline: python scripts/build_corpus.py --offline | --allow-network "
             "(fetch -> de-dup -> clean -> chunk -> manifests). This command no longer writes pages.")
    m, reg, plan = cmd_plan(log, args)
    if args.source == "local":
        fetcher = LegacyLocalFetcher(ROOT, reg)
    else:
        if not args.allow_network:
            sys.exit("--source network requires --allow-network (help.sap.com/robots.txt has Disallow: /)")
        fetcher = SapHelpApiFetcher(reg, log, allow_network=True)
    stats = ingest_plan(plan, fetcher, ROOT, Path(args.out) if args.out else None, log,
                        overwrite=args.overwrite, dry_run=args.dry_run)
    print(json.dumps(stats, indent=2))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["manifest", "registry", "register-guide", "resolve", "plan", "ingest", "all"])
    ap.add_argument("--toc-file", help="register-guide: saved pagecontent?deliverableInfo=1 JSON response for the guide")
    ap.add_argument("--numeric-id", help="register-guide: numeric deliverable_id taken from the same request (optional)")
    ap.add_argument("--build-no", help="register-guide: buildNo taken from the same request (optional)")
    ap.add_argument("--evidence", default="", help="register-guide: free-text provenance of the supplied files")
    ap.add_argument("--scope", choices=[m.value for m in ScopeMode], help="override default_scope in ingest_config.json")
    ap.add_argument("--max-depth", type=int, help="limit descendants depth (page_and_descendants only)")
    ap.add_argument("--source", choices=["local", "network"], default="local")
    ap.add_argument("--allow-network", action="store_true")
    ap.add_argument("--out", help="output dir for ingested pages (default: data/sap_help)")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true", help="echo events to the console")
    args = ap.parse_args(argv)
    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log = ev.EventLog(LOG)
    if args.command == "manifest":
        cmd_manifest(log)
    elif args.command == "registry":
        cmd_registry(log)
    elif args.command == "register-guide":
        cmd_register(args)
    elif args.command == "resolve":
        cmd_resolve(log)
    elif args.command == "plan":
        cmd_plan(log, args)
    elif args.command == "ingest":
        cmd_ingest(log, args)
    else:
        cmd_manifest(log); cmd_registry(log); cmd_resolve(log); cmd_plan(log, args)
    print("events:", json.dumps(log.counts()))


if __name__ == "__main__":
    main()
