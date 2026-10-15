> **2026-10-15 closure follow-up — NOT READY.** The assessment below is the published `a027cd64` record, not the latest result. See [RELEASE_BLOCKER_CLOSURE.md](RELEASE_BLOCKER_CLOSURE.md) for the exhaustive current blocker classification, all61 independent failure reproductions, narrow fixes and external procedures. Tested source: `47e1e09aece4feb03aeae3abd06c5458b983ba07`; backend **7F/1330P/137S/49E +204 subtests**. All four Chroma advisories remain open. Frozen `phase12_results.json` reports38/65 and two wrong-page cases; the older37/65 narrative remains provenance-unreconciled, not a new run or baseline change. No production activation authorized.

# SURA RAG quality — release mission v3

**FAIL / BLOCKED; NOT READY.** No labels, scores, tolerances, corpus captures, cache records, checkpoint pins or historical results were rebaselined. Engineering hardening is not SAP semantic correctness.

## Current evidence

Runtime `c324ffb366511b15385524aa8ed24e956f662780`; fresh unchanged-cache generator runs:

| Evaluation | Behavior matches | Mean key-fact recall | Prohibited heuristic flags | Scope |
|---|---:|---:|---:|---|
| Phase 3 A0 | 47/70 (67.1%) | 52.1% | 10 in 9 cases | Real shipped Python extractive generator; cached evidence, NOT current retrieval/full API |
| Phase 3 A0 oracle | 46/70 (65.7%) | 50.7% | 10 | Oracle cached context, NOT oracle SAP adjudication or real-model success |

Both report lexical citation coverage/precision 100% and zero hallucinated tokens under their heuristic. **Those numbers do not establish correct SAP semantics, relevance, source version, or complete answers.** Retrieval latencies in the cache are not newly measured HTTP inference. Generator-only millisecond latency is not production capacity.

Commands (candidate root, isolated non-model environment):

```sh
../.venv/bin/python eval/phase3/runner.py --adapter A0 --out ../phase3-a0-final-v7.json
../.venv/bin/python eval/phase3/runner.py --adapter A0 --oracle --out ../phase3-a0-oracle-final-v7.json
../.venv/bin/python benchmarks/run_quality.py --source-commit c324ffb366511b15385524aa8ed24e956f662780 --out ../full-quality-final-v7.json
../.venv/bin/python eval/release_v1/verify.py --out ../adversarial-preflight-final.json
```

First two exit 0 **means evaluation executed**, not gate passed. Full quality exits 1 (`ModuleNotFoundError: sentence_transformers`); no inference/result JSON. New adversarial preflight exits 2/BLOCKED. Summaries/hashes are versioned in `release/evidence/`; full outputs and traces remain at the fresh sibling paths.

## Historical weaknesses, not current full-pipeline reproduction

Frozen Phase 12: 113 cases = 65 answerable/40 negative/8 ambiguous; historical strict evidence result **37/65**, gold evidence in context 62/65, one wrong-page answer and 11/40 negative-label answers. This strongly motivates generator relevance/completeness and evidence-identity investigation; it does not prove the current full pipeline has the same exact metric. The corpus expanded after labels were authored: negative-label drift is reported, not silently relabeled. Frozen labels are AI-authored, not blind independent expert gold.

M2C-18 remains fail-closed: page `b1a202c9...` is absent from the verified 1481-node TOC of guide `9442486404b54071b4ebeab6a16628e7`; the captured page belongs to unregistered guide `e4375c1c...` / deliverable `40374490`. No new authoritative SAP mapping/version proof was obtainable. Admitting that capture under the requested guide would invent identity; no ingestion/store activation was performed.

Q35 remains separate strict numerical provenance work: Linux historical raw `.34654998779296875` versus historical Windows **rounded** `.3466`. The historical Windows raw score is missing. Neither a rounded value nor diagnostic float64 cosine reconstructs that raw score. Strict policy and batch/single provenance requirements remain unchanged; see the Windows report.

## Cached flag root-cause review

- CASE-012: business-master-data question receives technical-master-data enumeration too (`Premise`, `Grid` flags). Source extraction can be lexically grounded yet off-topic.
- CASE-020/023/024: selected procedural evidence is accompanied by a categorical “page does not document steps” limitation, even where the frozen case expects documented procedure. Evidence selection/procedure detection and unjustified whole-page absence claims need authoritative full-page adjudication; selected spans alone cannot justify absence.
- CASE-052: broad payments ambiguity selects external-cash-desk content. Existing metric permits a partial answer to match clarification; **that permissive match is not our strict safety/semantic acceptance**.
- CASE-025/037/039/040: heuristic flags include phrases not literally asserted in the output; polarity/token-overlap false positives are possible. They remain open review items, not automatically dismissed or rebaselined. The ten flags are not ten independently proven hallucinations; nor are they a security/quality pass.

These root causes require source/version-aware independent review and real retrieval runs before changing answer logic. No speculative generator rewrite, tolerance adjustment, curated cache replacement or abstention-based accuracy inflation was used to manufacture a pass.

## New versioned package

`eval/release_v1/cases.json` pins frozen reference/cache/corpus input hashes and covers positive, negative, ambiguous, navigation-only, wrong-guide, version-conflict, insufficient-evidence and adversarial policies. Positive cases reference existing P12-001/018/065 identities/quotes; they are **frozen AI reference labels**, not newly invented SAP gold. New policy cases are explicitly a review package awaiting independent adjudication.

`verify.py` refuses overwritten result paths and input drift; optionally observes an explicitly supplied existing private API, never starts a server/downloads/builds a store. It reads a backend token only from the environment, does not record it, counts 429/error responses as incomplete cases, and labels quote/identity matches only as **CANDIDATE**. Even an apparently clean observation run remains BLOCKED pending independent SAP claim/version review. Six evaluation-honesty regressions pass.

Predeclared unchanged strict threshold: >=95% substantive correctness on answerable frozen cases, 100% claim/citation identity, zero wrong-guide/version/unsupported factual answers, 100% safe prohibited/navigation/insufficient responses. Abstention is not a substantively correct answer. Independent review must check **every material claim**, not just one matching quote. Additional versioned performance targets are in the package; no measurements were invented.

## Closure

RAG/content owners need an approved existing embedding runtime + exact model/tokenizer hashes, verified cold-copy card/page stores, independent authoritative guide/version/page adjudication, frozen full-RAG replay and new adversarial full-API replay. Fix and regress independently demonstrated selection/identity/procedure bugs without changing frozen references. These are genuine external resource/adjudication blockers; the current cached failures remain material release failures.
