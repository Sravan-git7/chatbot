# Phase 10 report — RAG optimisation experiments (derived scope)

**Status: PARTIALLY COMPLETE — experiments completed and evaluated; NO optimisation was adopted; two items remain BLOCKED (real Ollama, 22 of 29 pages).**

Phase 10 produced a measured answer to "can the two weaknesses named in the Phase 8/9 reports be fixed cheaply?". The pre-declared adoption rules said **no for both**, so
the default pipeline is unchanged. The candidate code is shipped as an opt-in module (`scripts/rag_optimised.py`) that nothing in the default runtime imports.

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
* `evaluate_phase10.py` refuses to run twice (it will not overwrite `phase10_results.json`).
* Caveat that applies to G: the cue rules were written **after** the Phase 9 failures were seen, so gains on the Phase 8/9 sets are design-aware and are **not** unbiased evidence. Only TEST is unbiased.

## 3. DEV selection (`data/evaluation/phase10_selection.json`; TEST never read)

| λ | answerable R@1 (of 41) | wrong-topic answered | guard |
|---|---|---|---|
| 0 | 9 | 4 | pass (reference) |
| 0.5 | 23 | 7 | FAIL |
| 1.0 | 28 | 10 | FAIL |
| 2.0 | 33 | 10 | FAIL |

Rule outcome: **λ\* = 0 (fusion not selected)**. Diagnosis on DEV (read-only): fusion raises correct end-to-end answers 6 → 26 of 41 (with the selected G), but wrong-topic answers
rise 2 → 5 (3 absent-detail queries that are now routed to the right page but not refused, and 2 not-ingested queries routed to a *neighbouring* ingested page). The declared guard conflates
those two causes; I did **not** amend the rule after seeing this.

| Generator | oracle-correct (of 41) | absent-detail abstained (of 12) | constraint |
|---|---|---|---|
| G0 current (θ 0.34) | 33 | 3 | pass |
| G1 θ 0.5 | 31 | 5 | pass |
| G1 θ 0.67 | 18 | 10 | FAIL (loses 15) |
| **G2 detail-cue (θ 0.34)** | 32 | 9 | pass → **selected** |
| G2 + θ 0.5 | 30 | 10 | FAIL |

Selected configuration: λ 0, θ 0.34, detail-cue check on.

## 4. TEST results (sealed, 73 queries; `data/evaluation/phase10_results.json`)

| Configuration | answerable R@1 | R@3 | R@5 | MRR | real-router correct answers (of 41) | oracle correct (of 41) | oracle absent abstained (of 12) | wrong-topic answered (all non-answerable, of 32) |
|---|---|---|---|---|---|---|---|---|
| baseline (λ 0, θ 0.34, no cue) | 15/41 | 26 | 31 | 0.5441 | 10 | 32 | 6/12 | 3 |
| **selected** (G2 cue) | 15/41 | 26 | 31 | 0.5441 | 10 | 32 | 9/12 | 2 |
| R exploratory λ 2.0 (not selected) | 28/41 | 37 | 40 | 0.8006 | 21 | 32 | 6/12 | 7 |
| R exploratory λ 2.0 + G | 28/41 | 37 | 40 | 0.8006 | 21 | 32 | 9/12 | 4 |

### G — **NOT ADOPTED** (rule not met)
* +3 net correct abstentions (6/12 → 9/12; 3 gained, 0 lost; paired sign test p = 0.25), 0 answerable-correct lost, 0 grounding failures, 0 phantom citations.
* The declared bar was ≥ 4 net abstentions → **not supported**. Three absent-detail queries are still answered (P10T-044, 047, 048): their missing detail is not one of the cue categories, or a related sentence satisfies the cue.
* The direction agrees with DEV (+6 on DEV) but the TEST effect is smaller and not statistically significant.

### R — **NOT ADOPTED** (failed the DEV guard; TEST figures informational)
* R@1 15/41 → 28/41 (+0.317 absolute; paired: 15 only-candidate vs 2 only-baseline, sign-test p = 0.0023). Real-router correct answers 10 → 21 of 41.
* Costs: wrong-topic answers 3 → 7 (4 with G); top-1 on unresolved-identity queries 4/4 → 2/4 (the fused ranker pulls two of them onto an ingested page, e.g. P10T-062); absent-detail queries that the baseline refused for the *wrong* reason (mis-routed) are now answered (P10T-043, 048, 049).
* It therefore fails the declared criteria "no increase in wrong-topic answers" and "no worse unresolved/not-ingested routing". The trade-off is real and large (≈ +13 correct routes vs +4 wrong-topic answers) — **whether to accept it is a product decision that the pre-declared rule did not make for the maintainer; no claim of improvement is made.**

## 5. Regression references (earlier frozen sets; baseline vs selected; not unbiased for G)

| Set | metric | baseline | selected |
|---|---|---|---|
| Phase 9 (127) | card-router R@1 over gold-card queries | 51/111 (0.4595) | 51/111 (identical routing) |
| | oracle answerable correct (of 69) | 58 | 57 |
| | real-router correct (of 69) | 19 | 19 |
| | oracle absent abstained (of 14) | 7 | 14 (design-aware) |
| Phase 8 (88) | oracle answerable correct (of 59) | 51 | 48 (3 lost) |
| | oracle absent abstained (of 11) | 6 | 8 |

The Phase 9 baseline reproduces the frozen Phase 9 headline numbers (0.4595, 58/69 oracle, 7/14). On the Phase 8 set the cue check **loses 3 answerable answers** (P8-001 and P8-004: "which transaction" questions whose evidence sentence carries no code; P8-047: a "price" question, a cue-rule veto by inspection) and on Phase 9 it loses 1 (P9-009, a "how many" question); the Phase 8 loss is above the TEST tolerance of 2 and is one more reason not to adopt G.
Grounding failures 0 and phantom citations 0 in every configuration on every set. λ = 0 routing is identical to the baseline on all queries of both sets. Router-only R@1 with λ = 0.5–2 was not re-run on Phase 4/5 retrieval suites because the card collection and retrieval code are untouched.

## 6. Performance (`data/evaluation/phase10_performance.json`; extractive, 73 DEV queries, warm, this sandbox)

| Config | median ms | p95 ms |
|---|---|---|
| baseline | 15.9 | 36.9 |
| selected (cue) | 17.1 | 42.9 |
| R exploratory | 52.3 | 62.7 |
| R + G | 55.7 | 66.8 |

Fusion costs ≈ +36 ms median (a corpus-wide page search per query). Timings are noisy and are not a measure of Ollama latency.

## 7. Architecture changes

None to the default path. New, additive files only: `rag_optimised.py` (FusionBackend, DetailCueGenerator, `build_optimised_pipeline`, CLI), `phase10_lib.py`, `phase10_select.py`, `evaluate_phase10.py`, `build_phase10_queries.py`.
`rag_pipeline`, `rag_answer`, `rag_generate`, `rag_modes`, `rag_chat`, the card collection and every Phase 7–9 file are unmodified. Ollama generation is never wrapped by the cue check.

## 8. Tests

`tests/test_phase10.py` (43 tests): cue rules and word boundaries; wrapper behaviour; fusion with fake backends (λ = 0 passthrough, evidence equalisation, stability, never adds/drops a card); frozen hashes, disjointness, counts; selection rules reproduced from the grid; TEST verdicts recomputed from the results; report/results consistency; Phase 9 numbers reproduced; no network imports; default runtime does not import the experiments; real-store determinism (skips without stores).
Full-suite result: see the PR description (a report cannot hold the count of the suite that includes its own consistency tests).

## 9. Limitations

* Query sets are AI-authored and small (41 answerable per set); the paired tests have low power for G (3 vs 0, p = 0.25).
* Only 7 of 29 pages exist locally, so 22 cards can never be answered; fusion's evidence term only exists for those 7 pages, which biases it toward them.
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
* 43 focused tests; protected Phase 7–9 artifacts unchanged.

## 12. EXPERIMENTALLY EVALUATED

* R (page-evidence fusion): strong R@1 gain on TEST (15 → 28 of 41, p = 0.0023) but more wrong-topic answers — NOT ADOPTED.
* G (detail-cue abstention): +3/12 correct abstentions on TEST, below the declared bar of 4 — NOT ADOPTED.

## 13. BLOCKED

* Real Ollama generation (no executable/server/package; weight hosts unreachable): LLM faithfulness and abstention remain unmeasured.
* 22 of 29 SAP Help pages (help.sap.com TLS is dropped at the edge; saved robots.txt says `Disallow: /`, live state unknown): the corpus remains 7/29.

## 14. NOT CLAIMED

* No accuracy improvement of the shipped system; no claim that fusion or the cue check is better overall.
* No 29-topic coverage, no complete-corpus claim, no LLM metrics, no OOD-gate calibration, no human-labelled evaluation.
* The Phase 8/9 abstention gains of G are design-aware and are not evidence of generalisation.

## 15. Final git state

Base `d85c31e` → Phase 8 `30bbc95` → Phase 9 `59a766c` → Phase 10 (one commit on top; a report cannot contain its own hash — see `git log`). Branch `arena/01a0ed60-chatbot`; PR #1 open and **not merged**; `main` untouched.
Test results are recorded in the PR description and the final hand-off message.
