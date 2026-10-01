# Phase 11.1 - Answer correctness hardening: report

Nothing was committed or pushed. Contract (written before any candidate run, amended twice before the sealed sets were run, all amendments dated in the file): `data/phase11_1_contract.md`. Diagnosis: `data/phase11_1/diagnosis.md`.

## 1. HEAD
`bb61544252d7338704e0c281e8f76f769af84b4c` (Phase 10), branch `arena/01a0ed60-chatbot`; Phase 11 and 11.1 are uncommitted.

## 2. git status
No tracked file is modified. Untracked: Phase 11 files (`web/`, `scripts/rag_{service,api}.py`, `scripts/phase11_e2e.py`, tests, data) plus the Phase 11.1 files below.

## 3. Files changed / added in Phase 11.1
- New: `scripts/rag_evidence.py` (evidence sufficiency, support chain, optional widening, LLM guard), `scripts/evaluate_phase11_1.py`, `scripts/phase11_1_diagnose.py`, `scripts/build_phase11_1_holdout.py`, `scripts/build_phase11_1_holdout2.py`
- New data: `data/phase11_1_contract.md`, `data/phase11_1_report.md`, `data/phase11_1/*` (diagnosis, baseline/candidate E2E, DEV / DEV2 / holdout / holdout-2 / TEST / p8 / p9 results), `data/evaluation/phase11_1_holdout{,2}_{questions,freeze}.json`
- New tests: `tests/test_phase11_1_evidence.py` (37), `tests/test_phase11_1_service.py` (13), `web/src/__tests__/abstention.test.tsx` (4)
- Edited (Phase 11 files, still uncommitted): `scripts/rag_service.py` (evidence pipeline, support-chain gate, new wording, `debug.evidence`), `scripts/phase11_e2e.py` (`--out`/`--questions`), `web/src/components/DebugPanel.tsx` (evidence block), `web/e2e/browser_e2e.cjs` (+3 checks).
- Not touched: router, retrieval, page store, card store, Phase 1-10 artifacts and tests, `rag_pipeline.py`, `rag_generate.py`.

## 4. Baseline metrics (Phase 11 code, reproduced)
Product E2E 9/16 (answerable 5/10, negatives 4/6); identical to Phase 11. Fresh sets (oracle routing for generation, router mode for wrong-topic), B = baseline extractive generator:

| set | oracle-correct answerable | unsupported (absent-detail) answered | citation-evidence fails | wrong-topic (router) | grounding / phantom |
|---|---|---|---|---|---|
| holdout-2 (28 ans / 10 unsupp.) | 25 | 6 | 2 | 2 | 0 / 0 |
| Phase 10 TEST (41 / 12) | 32 | 6 | 3 | 3 | 0 / 0 |
| holdout-1 (40 / 15) | 40 | 9 | 0 | 4 | 0 / 0 |

## 5. Candidate metrics (shipped: evidence-aware generator, tau 0.5, no widening, no IDF)
| set | oracle-correct answerable | unsupported answered | citation-evidence fails | wrong-topic (router) | grounding / phantom / chain | router R@1, chunk R@1/3/5 |
|---|---|---|---|---|---|---|
| holdout-2 | 24 (-1) | 0 (-6) | 0 (-2) | 0 (-2) | 0 / 0 / 0 | identical |
| Phase 10 TEST | 33 (+1) | 4 (-2) | 2 (-1) | 2 (-1) | 0 / 0 / 0 | identical |
| Phase 9 (127 q; 69 answerable, 14 absent) | 52 (-6, B 58) | 0 (-7, B 7) | 2 (+2) | 0 (-3) | 0 / 0 / 0 | identical |
| Phase 8 (59 answerable, 11 absent) | 43 (-8, B 51) | 1 (-4, B 5) | 2 (-2) | 1 (-1) | 0 / 0 / 0 | identical |

Latency: median 20-23 ms and p95 about 50-57 ms per answer for both baseline and candidate (generation stage only changes by ~1 ms). Router and retrieval are not changed, so Phase 4, 5, 7, 8, 9 retrieval/routing baselines are unchanged (verified: R@1 and chunk recall identical in every table; the full pinned suite passes).
**Answer rate vs unsupported answers (stated plainly):** the candidate answers fewer answerable questions than the baseline on the older, larger sets (Phase 9 -6, Phase 8 -8: mostly paraphrase questions whose wording shares no stem with the page, which the lexical check cannot verify and now abstains) and fewer unsupported ones (12 -> 1 across the Phase 8 and 9 absent sets (7+5 -> 0+1), 15 -> 0 on holdout-1, 6 -> 0 on holdout-2). It is therefore a precision-for-recall trade, adopted only because the pre-declared rules passed on a fresh set, not because the answer rate rose.

## 6. Holdout
- **Holdout-1:** 72 questions, sha256 `52b0a0a8…`, frozen before any candidate code existed. Evaluated once with the iteration-1 candidate: **it failed the pre-declared rule 5** (citation-evidence failures 0 -> 1) and was **not adopted**. It became DEV2.
- **Holdout-2:** 48 questions (28 answerable incl. paraphrase / keyword / numeric-code / yes-no, 10 absent-detail, 4 not-ingested, 2 unresolved identity, 4 out-of-domain; all 7 ingested pages covered), sha256 `3a904940…`, frozen before the iteration-2 candidate existed, evaluated once. **All seven adoption rules passed** (see contract section 10).
- Authorship: AI coding assistant, not blind, no human labelling; holdout-2's author had seen holdout-1's results and failures. Evidence quotes are verified to exist in exactly one chunk and absent-detail terms are verified absent from the page text by the builders. Small n; single run; lexical evidence only.
- Iteration 2 (stemmer, meta nouns, cue words, rejected IDF) was designed on DEV2 = Phase 10 DEV + 16 E2E + holdout-1. IDF weighting was tried and rejected (loss 13 > 4).

## 7. E16
"What is the minimum installment amount?" -> status `unable_to_verify`, answer "I couldn't find enough verified information in the available SAP Utilities documentation to answer that specific detail.", no sources, not grounded. Mechanism: the question needs a *limit* kind and no retrieved sentence states a minimum/limit. General, covers number/code/limit/default/time kinds plus an asked-for-term check; no question text is in the code (a test pins this).

## 8. E02 / E04
- E02: now answered with the sentence that states the fact ("manages technical data, installations, meter readings, and the inspection of devices"), cited to the chunk containing it. Every answer sentence is a verbatim span of the chunk its marker names (independent `support_chain` check in the service; failure -> abstain, never "grounded").
- E04: the code-bearing chunk is not retrieved in the top 5. Candidate abstains (no code in evidence) instead of the former mismatched answer. A widening variant answers it ("choose ... (transaction FPR1)", cited chunk contains it) but did not meet its adoption rule on any unseen set, so it is not shipped. E04 therefore remains a *missed answer*, not a wrong one.

## 9. Routing (E06, E08, E09, E14)
Classified, not fixed (router unchanged): E06 and E08 sibling ambiguity, E09 hub-card/identity conflict, E14 OOD gate on the hub card. None fabricated an answer. Details in `data/phase11_1/diagnosis.md`. Product E2E is now **11/16** (E02, E16 fixed; E04 abstains; E06/E08/E09/E14 routing misses remain).

## 10. Test counts
Python **908 passed** (was 858; +37 evidence, +13 service/API tests); frontend vitest **52 passed** (was 48); `tsc --noEmit` clean; product E2E 11/16.

## 11. Browser E2E
Real Chromium against the live server: **28/28** (25 previous + exact abstention message, abstention not framed as an answer and without sources, unresolved identity text). Real answer text checked (e.g. "In the SAP Easy Access screen, choose Account > Installment Plan > Create ..."). `data/phase11/browser_e2e.json` and the screenshots were regenerated by this run.

## 12. Protected files
Verified unchanged: no tracked file modified; `source_manifest.json` 08ad208c, `card_collection_manifest.json` 5b3a5c30, `retrieval_units.json` f5e9b908, `rag_chat.py` e862ce38, `rag_core.py` 881316e4, `m2c_page_identity.json` fccb0bb8, `data/phase11_e2e_results.json` e65766f5eb95 (baseline E2E written elsewhere via `--out`); pinned Phase 7-11 hash tests pass; both holdout freezes match their hashes.

## 13. Remaining limitations
- Lexical check only: it cannot see synonyms (recall loss on paraphrases) and cannot prove semantic faithfulness; the LLM guard (`EvidenceGuard`) is stub-tested only because Ollama is unavailable (Phase 9 blocker unchanged).
- One residual citation-evidence failure type: a sentence that matches the topic words but not the predicate can still be chosen (it failed the first holdout once; rate 0-2 per set; on Phase 9 it is 2 vs 0 for the baseline, i.e. rule 5 would not hold on that older set). IDF weighting was rejected for over-abstaining.
- Remaining unsupported answer cases need permission/"who is allowed" style detail types (not covered by kinds).
- The shipped candidate was adopted on one sealed set of 48 (+ Phase 10 TEST); holdout-1 was consumed by iteration 1. Small n, AI-authored questions.
- Router failures (E06/E08/E09/E14) and missed answers (E04) remain; the widening variant and router changes would each need their own fresh holdout.
- Not committed; PR #1 unchanged.
