# Phase 10 report — RAG optimisation experiments (derived scope)

**Status: PARTIALLY COMPLETE — experiments completed and evaluated on the current corpus; NO optimisation was adopted into the default pipeline; one item remains BLOCKED (real Ollama).**

Phase 10 produced a measured answer to "can the two weaknesses named in the Phase 8/9 reports be fixed cheaply?". The pre-declared adoption rules said **no for both**, so
the default pipeline is unchanged. The candidate code is shipped as an opt-in module (`scripts/rag_optimised.py`) that nothing in the default runtime imports.

## Revision 2026-10-12 — re-run on the 28-page corpus

The verified corpus grew from 7 to 28 ingested pages (every established identity except the fail-closed M2C-18 conflict), and the Phase 8/9 query sets were regenerated for
it. Phase 10 is corpus-coupled, so the whole chain was re-run honestly on 2026-10-12: **DEV selection** (`phase10_select.py`, DEV only, sealed TEST never read) and then the
**sealed TEST evaluation once** (`evaluate_phase10.py`) with the newly selected configuration. The DEV and TEST query files themselves are unchanged (freezes `b7b1e51f…` /
`ffa46afa…`). The earlier 7-page numbers from 2026-10-01 are superseded; they remain in git history.

Two outcomes moved:

* On DEV the declared fusion guard ("wrong-topic answers must not exceed the λ = 0 count") now **passes for every λ** (16 wrong-topic answers at every λ on DEV — the richer
  corpus removed the evidence-equalisation bias toward the few ingested pages), so **λ\* = 2.0** is selected, with the same generator choice **G2 detail-cue**.
* On TEST the pre-declared adoption rules still reject both candidates (below), so the shipped default pipeline is still λ = 0, θ = 0.34, no cue check. Nothing in the default
  runtime reads `phase10_selection.json`.

## 1. Scope is derived, not specified

No Phase 10 specification exists in the repository (searched all `.md`, `.py`, `.json`). The scope below is **derived** from `data/phase8_report.md` §20 and the Phase 9 evidence;
it is my reading of the repository, **not a user-written specification**. The full derivation, candidates and decision rules were written **before any experiment** in
`data/phase10_contract.md`.

| Candidate | Source of the idea | What it changes |
|---|---|---|
| **R** — page-evidence re-ranking | Phase 8 §20 item 3 ("page-level re-ranking across the router's top-k") | re-orders the card router's 29-card list by `card_similarity + λ · best_page_chunk_similarity` (evidence-equalised: a card without an ingested page uses its own similarity as its evidence). λ ∈ {0, 0.5, 1, 2}. λ = 0 is a byte-for-byte passthrough |
| **G** — absent-detail abstention | Phase 8 §20 item 4; Phase 9 absent-detail 7/14 | extractive threshold θ ∈ {0.34, 0.5, 0.67}; and a deterministic *detail-cue check* (`CUE_RULES`): a question asking for a transaction code / a number / a default / a limit is refused when the extracted answer contains no such detail |

## 2. Method (leakage control)

* Two **fresh** AI-authored query sets (73 queries each: 41 answerable, 12 absent-detail, 8 not-ingested, 4 unresolved-identity, 8 out-of-domain) were written and hashed **before** any retrieval.
  DEV `b7b1e51f…` is used to select; TEST `ffa46afa…` is sealed and was evaluated **once**, with configurations fixed in advance. Neither overlaps the Phase 8/9 sets or each other (tested).
  AI authorship is disclosed; the queries are not human-labelled.
* Selection rules (contract §5, unchanged after seeing any result): R is selected only if its wrong-topic answers on DEV do **not exceed** the λ = 0 count; G is selected only if it loses ≤ 2 answerable-correct answers (oracle routing) and then maximises absent-detail abstentions.
* TEST adoption rules (`phase10_lib.TEST_RULES`): R needs ≥ +0.05 absolute R@1, paired sign-test p < 0.05, no increase in wrong-topic answers, no worse top-1 on not-ingested/unresolved. G needs ≥ 4 net correct abstentions, ≤ 2 answerable-correct lost, 0 grounding failures, 0 phantom citations.
* `evaluate_phase10.py` refuses to run twice (it will not overwrite `phase10_results.json`); the 2026-10-12 TEST run is the single evaluation of the sealed set against this system generation.
* Caveat that applies to G: the cue rules were written **after** the Phase 9 failures were seen, so gains on the Phase 8/9 sets are design-aware and are **not** unbiased evidence. Only TEST is unbiased.
* Corpus caveat for the query sets: they were authored against the 7-page corpus. Their 8 not-ingested gold labels still behave as labelled (all 8 route top-1 to a card
  without an ingested page in every configuration), but 2 of the 4 unresolved-identity queries are sensitive to reranking (see §4).

## 3. DEV selection (`data/evaluation/phase10_selection.json`; TEST never read)

| λ | answerable R@1 (of 41) | wrong-topic answered | guard |
|---|---|---|---|
| 0 | 9 | 16 | pass (reference) |
| 0.5 | 16 | 16 | pass |
| 1.0 | 16 | 16 | pass |
| 2.0 | 23 | 16 | pass → **selected** |

Rule outcome: **λ\* = 2.0 (fusion selected on DEV)**. On the 28-page corpus fusion raises DEV answerable R@1 9 → 23 of 41 without increasing wrong-topic answers (16 at every
λ). This reverses the 7-page outcome, where fusion's evidence term was only available for 7 pages and raised wrong-topic answers; the declared rule was **not** amended — the
changed outcome is a corpus effect.

| Generator | oracle-correct (of 41) | absent-detail abstained (of 12) | constraint |
|---|---|---|---|
| G0 current (θ 0.34) | 33 | 3 | pass |
| G1 θ 0.5 | 31 | 5 | pass |
| G1 θ 0.67 | 18 | 10 | FAIL (loses 15) |
| **G2 detail-cue (θ 0.34)** | 32 | 9 | pass → **selected** |
| G2 + θ 0.5 | 30 | 10 | FAIL |

Selected configuration: λ 2.0, θ 0.34, detail-cue check on.

## 4. TEST results (sealed, 73 queries; `data/evaluation/phase10_results.json`)

| Configuration | answerable R@1 | R@3 | R@5 | MRR | real-router correct answers (of 41) | oracle correct (of 41) | oracle absent abstained (of 12) | wrong-topic answered (all non-answerable, of 32) |
|---|---|---|---|---|---|---|---|---|
| baseline (λ 0, θ 0.34, no cue) | 15/41 | 26 | 31 | 0.5441 | 20 | 32 | 6/12 | 14 |
| **selected** (λ 2.0 + G2 cue) | 25/41 | 33 | 36 | 0.7318 | 23 | 32 | 9/12 | 12 |
| R exploratory λ 2.0 (no cue) | 25/41 | 33 | 36 | 0.7318 | 23 | 32 | 6/12 | 14 |
| R exploratory λ 2.0 + G | 25/41 | 33 | 36 | 0.7318 | 23 | 32 | 9/12 | 12 |

Not-ingested top-1 stays 8/8 in every configuration. Unresolved-identity top-1 is 4/4 at λ = 0 and 2/4 at λ = 2.0 (the fused ranker pulls two of them onto an ingested page).

### G — **NOT ADOPTED** (rule not met)
* +3 net correct abstentions (6/12 → 9/12; 3 gained, 0 lost; paired sign test p = 0.25), 0 answerable-correct lost, 0 grounding failures, 0 phantom citations.
* The declared bar was ≥ 4 net abstentions → **not supported**.
* Disclosure: because the DEV-selected configuration now also carries λ = 2.0, this TEST comparison is (fusion + cue) vs baseline, not cue-only; the abstention delta is
  attributed to the cue check by construction (fusion does not change oracle abstention at λ-independent oracle routing), but the comparison is labelled as computed.

### R — **NOT ADOPTED** (fails the declared TEST criteria)
* R@1 15/41 → 25/41 (+0.2439 absolute; paired: 13 only-candidate vs 3 only-baseline, sign-test p = 0.0213). Real-router correct answers 20 → 23 of 41.
* Wrong-topic answers do not increase (14 → 14 without cue; 14 → 12 with cue).
* But top-1 on unresolved-identity queries falls 4/4 → 2/4, so the declared criterion "no worse top-1 on not-ingested/unresolved" fails; the exploratory configuration is
  therefore **not adopted** and the default pipeline stays λ = 0. The trade-off is real (≈ +10 correct routes vs 2 unresolved queries pulled onto ingested pages) — **whether
  to accept it is a product decision that the pre-declared rule did not make for the maintainer; no claim of improvement is made.**

## 5. Regression references (earlier frozen sets; baseline vs selected; not unbiased for G)

| Set | metric | baseline | selected |
|---|---|---|---|
| Phase 9 (101 queries, freeze 101a5edb) | card-router R@1 over gold-card queries | 29/85 (0.3412) | 52/85 |
| | oracle answerable correct (of 69) | 58 | 57 |
| | real-router correct | 40 | 43 |
| | oracle absent abstained (of 14) | 7 | 14 (design-aware) |
| Phase 8 (80 queries, freeze 150cba14) | card-router R@1 over gold-card queries | 31/72 | 51/72 |
| | oracle answerable correct (of 59) | 51 | 48 (3 lost) |
| | real-router correct | 43 | 41 |
| | oracle absent abstained (of 11) | 6 | 8 |

The Phase 9 baseline reproduces the regenerated frozen Phase 9 headline numbers exactly (29/85 R@1, 58/69 oracle correct, 7/14 oracle absent). On the Phase 8 set the selected
configuration **loses 3 answerable answers** to the cue check; on Phase 9 it loses 1. The selected configuration is no longer λ = 0, so the λ-0 passthrough field is null in
`phase10_results.json`; the passthrough guarantee is covered by the FusionBackend unit tests instead.
Grounding failures 0 and phantom citations 0 in every configuration on every set. Router-only R@1 with λ = 0.5–2 was not re-run on Phase 4/5 retrieval suites because the card
collection and retrieval code are untouched.

## 6. Performance (`data/evaluation/phase10_performance.json`; extractive, 73 DEV queries, warm, this sandbox)

| Config | median ms | p95 ms |
|---|---|---|
| baseline | 17.6 | 21.4 |
| selected (λ 2.0 + cue) | 54.2 | 64.0 |
| R exploratory | 53.5 | 61.6 |
| R + G | 53.9 | 66.8 |

Fusion costs ≈ +36 ms median (a corpus-wide page search per query). Timings are noisy and are not a measure of Ollama latency.

## 7. Architecture changes

None to the default path. New, additive files only: `rag_optimised.py` (FusionBackend, DetailCueGenerator, `build_optimised_pipeline`, CLI), `phase10_lib.py`,
`phase10_select.py`, `evaluate_phase10.py`, `build_phase10_queries.py`. The default runtime does not import the experiments and does not read `phase10_selection.json`.
Ollama generation is never wrapped by the cue check.

## 8. Tests

`tests/test_phase10.py`: cue rules and word boundaries; wrapper behaviour; fusion with fake backends (λ = 0 passthrough, evidence equalisation, stability, never adds/drops a
card); frozen hashes, disjointness, counts; selection rules reproduced from the grid; TEST verdicts recomputed from the results; report/results consistency; Phase 9 numbers
reproduced; no network imports; default runtime does not import the experiments; real-store determinism (skips without stores).
Full-suite result: see the release report (a report cannot hold the count of the suite that includes its own consistency tests).

## 9. Limitations

* Query sets are AI-authored and small (41 answerable per set); the paired tests have low power for G (3 vs 0, p = 0.25).
* The sets were authored against the 7-page corpus; on the 28-page corpus their not-ingested/unresolved labels still hold for routing top-1 (8/8 and 4/4 at λ = 0), but they
  were not re-authored, so they exercise a subset of the new corpus.
* The cue rules are English keyword rules designed from the Phase 9 failures; they cannot generalise beyond those detail categories.
* Extractive generator only; LLM behaviour is unmeasured.

## 10. Reproducibility

```
python scripts/build_phase10_queries.py        # DO NOT re-run: writes the frozen sets (hash-checked)
python scripts/phase10_select.py               # DEV only -> phase10_selection.json
python scripts/evaluate_phase10.py             # TEST once -> phase10_results.json (refuses a second run)
python scripts/rag_optimised.py --generator extractive --lam 1.0 --cue-check "question"   # opt-in demo
PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m pytest tests -q -p no:cacheprovider
```
Stores must first be rebuilt with `--manifest /tmp/...` so default manifests stay untouched.

## 11. COMPLETED

* Derived scope and rules written before experiments; two frozen, disjoint, hash-checked query sets.
* Candidate implementation (opt-in), DEV-only selection, sealed single TEST evaluation, regression references, determinism check, performance comparison.
* Full honest re-run on the 28-page corpus (2026-10-12): DEV selection then sealed TEST evaluation once; same no-adoption outcome for the default pipeline.

## 12. EXPERIMENTALLY EVALUATED

* R (page-evidence fusion): DEV-selected on the 28-page corpus (λ = 2.0); TEST R@1 15 → 25 of 41 (p = 0.0213) with no extra wrong-topic answers, but unresolved-identity
  top-1 falls 4/4 → 2/4 — fails the declared routing criterion — NOT ADOPTED.
* G (detail-cue abstention): +3/12 correct abstentions on TEST, below the declared bar of 4 — NOT ADOPTED.

## 13. BLOCKED

* Real Ollama generation (no executable/server/package; weight hosts unreachable): LLM faithfulness and abstention remain unmeasured.
* The M2C-18 conflict remains unresolved (fail-closed by design): 28 of 29 pages are ingested; this is not 29/29 coverage.

## 14. NOT CLAIMED

* No accuracy improvement of the shipped system; no claim that fusion or the cue check is better overall.
* No complete-corpus claim (28 of 29 pages), no LLM metrics, no OOD-gate calibration, no human-labelled evaluation.
* The Phase 8/9 abstention gains of G are design-aware and are not evidence of generalisation.

## 15. Final git state

Phase 8 → Phase 9 → Phase 10 commits are in `git log` on branch `arena/b450cda2-chatbot` (a report cannot contain its own hash). Test results are recorded in the release
report and the final hand-off message.
