# Phase 12 - Full corpus + real-LLM validation: report

Contract (written before the question set): `data/phase12_contract.md`. Question set (frozen before any evaluation): `data/evaluation/phase12_queries.json`, sha256 `3c5a9ddd2d62e9cb1919a4fbb7c81cd5239994ff230abbbe6440fb6fa5c132ac`
(`phase12_freeze.json`). **Authorship: AI coding assistant; not blind (it had read all 7 page texts and the Phase 11.1 failure analysis); not a domain expert; NOT human-labelled.**
A report cannot contain its own commit hash; the hash is given in the hand-over message.

## COMPLETED (really done and measured here)

1. **Part A - environment/ref repair and verification** at the start of the phase (Python 908, vitest 52, tsc clean, product E2E 11/16, browser E2E 28/28, protected hashes OK).
2. **Part B - Phase 11 + 11.1 committed and pushed** (`f5cddbc`); PR #1 body updated; PR not merged.
3. **Honest corpus/network status** (`scripts/phase12_corpus_status.py --probe` -> `data/phase12/corpus_status.json`, `import_manifest.json`): 29 cards, **7 local pages**, 18 fetchable-in-principle pages with recorded ids,
   4 cards that cannot be fetched at all (M2C-01/13/16 identity-only, M2C-18 conflicting). The probe (DNS -> TCP -> TLS) shows `help.sap.com`, `ollama.com`, `registry.ollama.ai`, `huggingface.co` fail at the **TLS handshake**
   (EOF); `github.com` and `pypi.org` work. A real fetch attempt (`fetch_attempt_log.json`) saved 0 pages and stopped at the circuit breaker (3 consecutive transport failures). No bypass was tried.
4. **Import tooling for a machine that can reach SAP Help** (`scripts/phase12_import_pages.py`, never fetches, validates with the existing `page_fetch.check_response`; instructions in `data/phase12/IMPORT_INSTRUCTIONS.md`, Windows commands included). Tested with temp folders.
5. **Ollama environment check** (`scripts/phase12_ollama_check.py`): exit 3 here - `NO_OLLAMA_EXECUTABLE`, `NO_PYTHON_OLLAMA_PACKAGE`, `OLLAMA_SERVER_NOT_RESPONDING`. While testing it, a bug was found and fixed: an empty generation made `ready` false without naming a blocker; it now reports `GENERATION_ROUND_TRIP_FAILED`.
6. **Evaluation on the frozen set - extractive configurations only** (`scripts/evaluate_phase12.py` -> `data/evaluation/phase12_results.json`, `phase12_performance.json`). Results below.
7. **Router failure audit, no router change** (`scripts/phase12_failure_audit.py` -> `data/evaluation/phase12_failure_audit.json`), pre-declared first-match-wins rules, over 8 question sets.
8. **Real-browser E2E** (`web/e2e/phase12_browser_e2e.cjs` -> `data/phase12/browser_e2e.json`): **24/24**, of which 22 backend/real-server checks and 2 clearly labelled *synthetic* renderer checks. Includes a real server started with `--generator ollama` (real 502, no answer text, no fallback) and a real server process killed mid-session. The Phase 11 browser E2E still passes 28/28.
9. **Tests**: 38 new tests (`tests/test_phase12_questions_and_env.py`, `tests/test_phase12_eval_audit.py`). Full suite: **946 passed** with stores; **885 passed + 61 skipped (all with stated reasons)** with the stores removed. vitest 52, tsc clean, `git diff --check` clean.

## Results on the Phase 12 set (113 questions: 65 answerable, 16 absent-detail, 10 not-ingested, 6 unresolved-identity, 8 ambiguous, 8 out-of-domain; corpus 7/29)

`baseline` = extractive generator of Phases 8-10. `evidence` = shipped Phase 11.1 configuration (extractive + evidence sufficiency, tau 0.5). "Real routing" = what a user gets; "oracle" = gold card forced (retrieval/generation in isolation).

| metric | baseline | evidence |
|---|---|---|
| answerable, correct answer + cited evidence - real routing (of 65) | 24 | 21 |
| answerable, correct - oracle (of 65) | 53 | 52 |
| answerable, abstained - real / oracle | 39 / 6 | 42 / 10 |
| citation-evidence failures - real / oracle | 2 / 6 | 2 / 3 |
| wrong-page answers (answered from a non-gold card) - real | 0 | 0 |
| unsupported questions answered (of 40) - real | 4 | 2 |
| absent-detail questions answered (of 16) - real / oracle | 3 / 10 | 1 / 1 |
| ambiguous: acceptable answer / abstained (of 8) - real | 5 / 3 | 5 / 3 |
| grounding failures, support-chain failures, phantom citations, URL changes | 0 | 0 |
| chunk R@1 / R@3 / R@5 / MRR (oracle page, 65 q) | 0.754 / 0.969 / 0.985 / 0.860 | same (retriever unchanged) |
| gold evidence in the generation context - real / oracle (of 65) | 29 / 63 | 29 / 63 |
| latency total median / p95 (ms, 2 vCPU, warm) | 29.4 / 68.2 | 29.4 / 69.2 |

Router (identical for all configurations; 105 questions with a gold card): **R@1 0.505 (53/105), R@3 0.752, R@5 0.857, MRR 0.650**; answerable only R@1 0.462 (30/65). By category R@1: corrected_identity 1.00, ambiguous 0.875,
numeric_detail 0.83, review_conflict 0.70, paraphrased 0.64, sibling_topic 0.54, direct_factual 0.375, absent_detail 0.25, terminology 0.22, code_transaction 0.11.

Reading of the numbers (no claim beyond them):
* The evidence guard does what it was adopted for: absent-detail answers fall from 10 to 1 (oracle) and unsupported answers from 4 to 2 (real); citation-evidence failures from 6 to 3 (oracle).
* It is **not free**: with real routing 3 fewer answerable questions are answered (24 -> 21), and in the `numeric_detail` category (oracle) the guard abstains on 5 of 6 questions where the baseline answered 5 (4 correct). The numeric/threshold cue is too strict for answerable numeric facts - a known cost from Phase 11.1 that this fresh set confirms; it was **not** tuned here (no tuning on a frozen set).
* Most answerable questions fail on **routing**, not on retrieval or generation: only 29/65 reach a context containing the evidence with real routing versus 63/65 with the gold card. Those failures end as honest abstentions or "documentation unavailable", never as wrong-page answers (0).
* The two remaining unsupported answers of `evidence`: P12-071 (absent detail "preselected" - the page mentions interval type but not a preselection; the lexical check passed) and P12-096 (an `unresolved_identity` label: the router picked a *different, ingested* card (invoicing) and the answer is on-topic for that card; by the frozen label it counts as wrong). Both are listed, not hidden.
* The oracle citation-evidence failures left (P12-015, 053, 057) are list/table questions where the cited chunk contains the topic but the cited sentence does not contain the evidence phrase.

## Router failure audit (read-only; rules pre-declared in contract section G; first match wins)

Phase 12 set, 52 router top-1 misses: sibling_ambiguity 16, other_ranking 12, identity_hub 11 (top-1 = M2C-18 x6, M2C-13 x3, M2C-01, M2C-16), vocabulary_mismatch 8, near_tie_embedding 5. 46 of the 52 gold cards have no local page (flag `gold_page_not_available`).
`ood_gate` (right top-1, answerable, status out_of_domain): 0 on Phase 12; 1 across the older sets (P9-030). Over all 8 sets (296 misses): identity_hub 88, sibling_ambiguity 85, other_ranking 61, vocabulary_mismatch 36, near_tie_embedding 25, query_underspecified 1.
The two largest causes are structural: hub cards that can never answer (M2C-18/13/01/16) outranking real cards, and sibling cards of the same category. **No router change was made or evaluated.** Candidate changes (card-text query expansion, dense+lexical fusion, sibling-aware re-ranking) are listed with adoption rules in the contract; none has been run, so the baseline router stays.

## BLOCKED (not done - exact reason)

* **Real Ollama / LLM validation: BLOCKED.** No Ollama executable, Python package or server here; `ollama.com`/`registry.ollama.ai`/`huggingface.co` fail the TLS handshake, so no model can be downloaded; 2 CPUs / 3.8 GB RAM would also be marginal for `llama3.2:3b`. `ollama_raw` and `ollama` are recorded as `BLOCKED` in the results file with no metrics and were **not** replaced by the extractive generator. The EvidenceGuard on real LLM output is still only stub-tested.
* **Full corpus: BLOCKED.** 0 of the 18 fetchable pages could be fetched (TLS dropped at the edge); also `robots.txt` last saved for `help.sap.com` says `Disallow: /` and the current state is unknown, which is the user's decision. Corpus remains **7/29**. Even with network access the maximum is 25/29 (M2C-01/13/16/18 cannot be fetched without a new verified identity).
* Consequently the 10 `not_ingested` and 6 `unresolved_identity` questions only test honest unavailability, not real answers; `phase12_results_ollama.json` and an enlarged-corpus set do not exist.

What to do on your side: `data/phase12/IMPORT_INSTRUCTIONS.md` (A: Ollama run, B: page import).

## NOT CLAIMED

* No claim of 29/29 or "complete" corpus; no claim of any LLM metric; no claim that the evidence guard works on real LLM output.
* No claim of human-labelled ground truth, blindness or statistical significance (113 questions, one AI author; most per-category counts are < 20).
* No router improvement is claimed - none was tried. Router R@1 0.505 is the baseline behaviour measured on a fresh set.
* The "renderer (synthetic)" browser checks use a synthetic response and prove only markdown rendering, not backend behaviour.
* Latency is for the extractive pipeline on a 2-vCPU sandbox; no LLM latency exists.

## Preservation

Not modified: `rag_chat.py`, `rag_core.py`, Phase 1-10 artifacts, card/page collection manifests, `rag_pipeline.py` logic, the Phase 11 E2E results. Protected hashes verified (`source_manifest` 08ad208c, `card_collection_manifest` 5b3a5c30, `retrieval_units` f5e9b908, `rag_chat` e862ce38, `rag_core` 881316e4, `m2c_page_identity` fccb0bb8, `phase11_e2e_results` e65766f5). Re-running the Phase 11 browser E2E rewrote its committed artifact files; they were restored to HEAD content.
