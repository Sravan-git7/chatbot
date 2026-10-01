"""Rebuild the 29-topic target corpus from scratch (deterministic).

    python scripts/build_corpus.py --offline                    # local saved pages only (today: topic #17)
    python scripts/build_corpus.py --allow-network              # the real rebuild, once all 6 guides are registered
    python scripts/build_corpus.py --allow-network --require-complete   # exit non-zero unless ALL 29 topics RESOLVED

Stages: validate manifests -> resolve guides (registry + data/guide_registrations.json) -> resolve topics ->
expand scope -> fetch -> page de-dup -> clean -> content de-dup -> chunk -> statistics -> final manifest.

Fetch sources (network is OFF by default):
    (default)         raw cache only (<out>/raw); a page missing from the cache is reported as FETCH_FAILED
    --offline         raw cache, then the locally saved legacy pages in sap_pages/ (verified guide only)
    --allow-network   raw cache, then the SAP Help pagecontent API (needs numeric id + build number per guide).
                      NOTE help.sap.com/robots.txt has "Disallow: /" for generic agents; enabling this is your decision.

Exit codes: 0 ok | 1 --require-complete and the corpus is incomplete | 2 pages failed to fetch / invalid guide
registration / schema error | 3 invalid manifests or configuration.

Never touches sap_pages/, chunks.json, cleaned_pages.json, chroma_db/, the embedding model or the LLM.
No embeddings are computed and no Chroma collection is created or updated.
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

from sap_resolver.chunk import ChunkConfig                                       # noqa: E402
from sap_resolver.pipeline import (EXIT_INVALID_INPUT, BuildConfig, ManifestError, build_corpus)  # noqa: E402
from sap_resolver.plan import ConfigError, IngestConfig, ScopeMode              # noqa: E402


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--offline", action="store_true", help="use locally saved pages (sap_pages/) - no network")
    src.add_argument("--allow-network", action="store_true", help="explicitly enable SAP Help API fetching")
    ap.add_argument("--require-complete", action="store_true", help="exit non-zero unless all topics are RESOLVED")
    ap.add_argument("--scope", choices=[m.value for m in ScopeMode], help="default scope (overrides data/ingest_config.json)")
    ap.add_argument("--max-depth", type=int, help="descendant depth limit (1 = direct children)")
    ap.add_argument("--topic-scope", action="append", default=[], metavar="ID=SCOPE", help="per-topic override, repeatable")
    ap.add_argument("--config", default="data/ingest_config.json")
    ap.add_argument("--registrations-file", default="data/guide_registrations.json",
                    help="declarative guide registrations (default data/guide_registrations.json)")
    ap.add_argument("--corrections-file", default="data/topic_corrections.json",
                    help="per-topic card->guide corrections with evidence (default data/topic_corrections.json)")
    ap.add_argument("--out-dir", help="corpus directory (default: out_dir of the config = data/sap_help)")
    ap.add_argument("--manifest-dir", help="where final_corpus_manifest.* go (default: data/ for the default corpus, else --out-dir)")
    ap.add_argument("--refresh", action="store_true", help="ignore the raw cache and fetch again")
    ap.add_argument("--max-chunk-chars", type=int, default=ChunkConfig.max_chars)
    ap.add_argument("--overlap-chars", type=int, default=ChunkConfig.overlap_chars)
    ap.add_argument("--embedding-context", choices=["none", "title", "title_section"], default="none")
    ap.add_argument("--expected-topics", type=int, default=29)
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    a = parse_args(argv)
    if a.verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        ing = IngestConfig.load(ROOT / a.config)
        if a.scope:
            ing.default_scope = ScopeMode(a.scope)
        if a.max_depth:
            ing.max_depth = a.max_depth
        for item in a.topic_scope:
            tid, _, sc = item.partition("=")
            ing.topic_scopes[int(tid)] = ScopeMode(sc)
        default_out = ing.out_dir
        out_dir = Path(a.out_dir or default_out)
        manifest_dir = Path(a.manifest_dir or ("data" if out_dir == Path(default_out) and not a.out_dir else out_dir))
        cfg = BuildConfig(
            repo_root=ROOT, out_dir=out_dir, manifest_dir=manifest_dir,
            mode="offline" if a.offline else "network" if a.allow_network else "cache",
            ingest=ing, chunk=ChunkConfig(max_chars=a.max_chunk_chars, overlap_chars=a.overlap_chars,
                                          embedding_context=a.embedding_context),
            require_complete=a.require_complete, expected_topics=a.expected_topics, refresh=a.refresh,
            registrations_file=Path(a.registrations_file), corrections_file=Path(a.corrections_file))
        res = build_corpus(cfg)
    except (ManifestError, ConfigError, ValueError) as e:
        print(f"INVALID INPUT: {e}", file=sys.stderr)
        return EXIT_INVALID_INPUT
    m, T = res.manifest, res.manifest["totals"]
    print(f"corpus dir : {m['isolation']['corpus_dir']}   mode: {m['config']['mode']}   scope: {m['config']['default_scope']}")
    print(f"topics     : {m['topic_status_counts']}")
    print(f"pages      : unique planned={T['unique_pages_planned']} fetched={T['pages_fetched']} failed={T['pages_failed']} "
          f"dup(identity)={T['duplicate_pages_identity']} dup(content)={T['duplicate_content_pages']}")
    print(f"chunks     : {T['total_chunks']} (avg {T['avg_chunk_chars']}, median {T['median_chunk_chars']}, "
          f"min {T['min_chunk_chars']}, max {T['max_chunk_chars']})")
    print(f"fingerprint: {m['corpus_fingerprint'][:16]}   complete: {m['corpus_complete']}")
    for msg in res.messages:
        print("WARNING:", msg, file=sys.stderr)
    print(f"exit code  : {res.exit_code}")
    return res.exit_code


if __name__ == "__main__":
    sys.exit(main())
