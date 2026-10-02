# Phase 11.1 contract - answer-correctness hardening (written BEFORE any candidate evaluation)

Scope comes from the user's Phase 11.1 message (E16 abstention, E02/E04 citation-evidence, routing classification, 40+ fresh holdout, baseline vs candidate, no regression).
Nothing here edits a Phase 1-10 artifact; the default `rag_pipeline` and `rag_generate` are untouched. The candidate is a new module (`scripts/rag_evidence.py`) wired into the
Phase 11 service only if the adoption rules below pass.

## 1. Diagnosis of the 7 failing Phase 11 cases (read-only; `data/phase11_1/diagnosis.json`, `scripts/phase11_1_diagnose.py`)

Real pipeline, real router, oracle routing to the expected card as the control. "evidence in context" = the verified evidence phrase is inside the chunks given to the generator.

| Case | Router | Identity | Chunks | Answer | Citation | Oracle control | Cause class |
|---|---|---|---|---|---|---|---|
| E02 | M2C-05 correct | corrected_identity | S1 (has the fact) is in context | picked another sentence ("The following table lists the standard application components ...") | S2, which does contain that sentence | same | **sentence selection** (lexical overlap; the section heading "Device Management" is not counted; manage/management do not stem together). Not a citation error: the cited chunk does contain the cited sentence |
| E04 | M2C-24 correct | identified_not_local, page ingested | top-5 chunks do **not** contain the transaction code chunk (FPR1) | generic "You create an installment plan when ..." | S1/S2/S4, which contain those sentences | same (oracle also lacks it) | **retrieval ranking + no detail check**: the question asks for a transaction, no context sentence names one, yet an answer was produced |
| E06 | M2C-04 (rank 1), expected M2C-02 at rank 3 | page not ingested | - | documentation unavailable | - | oracle answers, evidence in context | **sibling-card ambiguity** (Move-Out vs Move-In/Out) |
| E08 | M2C-23 (rank 1), expected M2C-24 at rank 2 | page not ingested | - | documentation unavailable | - | oracle answers | **sibling-card ambiguity** (Installment Plan Overview vs Creating Installment Plans) |
| E09 | M2C-18 (rank 1), expected M2C-17 at rank 2 | conflicting_identity | - | unable to verify | - | oracle answers | **identity problem / hub card** (protected M2C-18 conflict card absorbs the query) |
| E14 | M2C-18 (rank 1) | conflicting_identity | - | out of scope (lexical gate) | - | oracle M2C-07 answered "Transaction EL31" - related, not the asked authorization object | **retrieval ranking (hub card) + OOD gate**; with the right card the answer would still be an **unsupported** answer (needs the evidence check) |
| E16 | M2C-24 correct | ok | context lacks the word "minimum" | related sentences about "first installment" and "installment amount" | S1, S2 | same | **absent detail answered** (no sufficiency check) |

Routing is NOT changed in this phase (Phase 10's page-evidence fusion improved top-1 but raised wrong-topic answers and was not adopted; no new router evidence exists). E06/E08/E09/E14
are classified, and the requirement is that a mis-route never yields a fabricated answer (it ends in "documentation unavailable" / "unable to verify" / "out of scope").

## 2. Candidates

* **B** baseline: default `ExtractiveGenerator` (theta 0.34), default retriever (= the Phase 11 product).
* **C1** evidence gate + evidence-aware selection (`EvidenceExtractiveGenerator`, tau): asked-term presence, detail-kind presence (code / number / limit / default / time), best-sentence focus coverage >= tau (section heading counts as context), verbatim-only sentences.
* **C2** = C1 + `EvidenceRetriever` (same-page widening when retrieved chunks cannot supply the asked kind of detail).
All lexical, deterministic, no model, no network, no new router threshold.

## 3. Pre-declared constants

`TAU` 0.6 default; grid {0.5, 0.6, 0.67}. `KEEP_RATIO` 0.6, max 3 sentences (as baseline). Frame words, kind cue tables and kind evidence tests are in `rag_evidence.py` and are fixed before DEV is run.
Only tau is selected, on DEV.

## 4. Data and leakage control

* Fresh HOLDOUT: `data/evaluation/phase11_1_holdout_questions.json` (72 = 40 answerable, 15 absent-detail, 7 not-ingested, 3 unresolved, 7 out-of-domain), sha256 in `phase11_1_holdout_freeze.json`, written and frozen before `rag_evidence.py` was run. Checked: no overlap (exact or token-Jaccard >= 0.8) with the Phase 8/9/10 sets or the 16 E2E questions; gold evidence quotes lie inside one chunk; absent-detail terms do not occur in the page text.
  Authorship: AI coding assistant; not blind; not a domain expert; had read the 7-page corpus and the Phase 11 failure analysis (so the absent-detail design is not independent of what was learned in Phase 11). Not human-labelled.
* DEV (tau selection and debugging): Phase 10 DEV set (73) + the 16 Phase 11 E2E questions (these 16 were inspected: improvements there are NOT evidence).
* Regression, run once: Phase 10 TEST (73), Phase 9 (127), Phase 8 (88): reported as regression, design-aware, not unbiased.
* HOLDOUT is evaluated once per fixed configuration (B, C1 at tau*, C2 at tau*). The runner refuses to overwrite its results.

## 5. DEV selection of tau (oracle routing, extractive)

Among grid values with oracle-correct answerables >= B - 2 on the 41 Phase 10 DEV answerable queries, choose the one with the most absent-detail abstentions; ties go to the smaller tau. If none qualifies, the candidate is not adopted.

## 6. Adoption rules (candidate vs B, HOLDOUT; decided before the run)

A candidate is adopted into the product only if ALL hold:
1. Unsupported answers (absent-detail questions answered under oracle routing) fall by >= 4 of 15.
2. Oracle-correct answerables lose <= 3 of 40 versus B.
3. Wrong-topic answers in router mode (non-answerable questions that end `answered`) do not increase.
4. 0 grounding failures, 0 phantom citations, 0 support-chain failures (an answered sentence that is not a verbatim span of the chunk its marker names).
5. Citation-evidence failures (answerable, oracle routing, status answered, but no cited chunk contains the gold evidence) do not increase.
6. Router top-1 identical to B (the router is untouched) and in-page chunk R@5 for answerables does not fall.
7. Phase 10 TEST regression: oracle-correct loss <= 3 and absent-detail abstentions >= B.
C2's extra component (widening) is kept only if C2 has >= 1 more oracle-correct answerable than C1 and C2 also satisfies 1-7. Otherwise C1 ships.
A change that raises the answer rate while raising unsupported answers is rejected by rules 1, 3 and 5 regardless of other gains.

## 7. Metrics (per configuration and set)

Answerable answered / abstained / correct (router mode and oracle mode); absent-detail abstained; not-ingested, unresolved and out-of-domain status match; wrong-topic answers; grounding failures; support-chain failures;
citation-evidence failures; phantom citations; router R@1/3/5/MRR (unchanged by design); in-page chunk R@1/3/5; latency median and p95 (server `total_ms`).
Definitions follow `phase10_lib` (`correct` = answered AND a cited chunk of the gold page contains an evidence quote).

## 8. Amendment 1 (written after DEV, BEFORE the holdout was run) - disclosed deviation

Section 3 said the code constants would be fixed before DEV. The first DEV run (`data/phase11_1/eval_dev_round1.json`) exposed two defects, which were fixed before the holdout was touched:

| Round | What DEV showed | Fix |
|---|---|---|
| 1 (as first written) | C1@0.5 oracle-correct 35/51 vs B 41, new wrong selections (E01/E03/E05 answered with unrelated sentences) | (a) a term found only in the section heading counted fully, so any sentence under a matching heading scored 100 %: heading terms now weigh 0.5 and a sentence needs at least one own focus term; (b) modal verbs (must, may, have ...) were taken as the "asked-for" word and caused false refusals: added to the skip list |
| 2 | see below | none (only a cosmetic de-duplication of a repeated header line and docstring edits; DEV re-run confirmed identical metrics) |

DEV round 2 (51 queries = Phase 10 DEV 41 answerable... + 16 E2E; oracle routing; B vs candidates):

| config | oracle-correct answerables (of 51) | unsupported answered (of 14) | citation-evidence failures | wrong-topic (router) |
|---|---|---|---|---|
| B | 41 | 11 | 6 | 5 |
| C1@0.5 / 0.6 / 0.67 | 39 / 35 / 29 | 1 / 1 / 0 | 3 / 3 / 1 | 0 |
| C2@0.5 / 0.6 / 0.67 | 40 / 36 / 30 | 1 / 1 / 0 | 3 / 3 / 1 | 0 |

Selection rule (section 5): only tau = 0.5 keeps the loss <= 2 (C1 loses 2, C2 loses 1) -> **tau* = 0.5** for both candidates. The holdout is then evaluated once with B, C1@0.5, C2@0.5.
The remaining DEV losses are paraphrase questions whose wording shares no stem with the page (e.g. "told apart" vs "identified", "decides" vs "defines"); a lexical check cannot see synonyms, so these become abstentions. That is a recall cost accepted in exchange for the unsupported-answer reduction, and it is measured, not hidden.

## 9. Holdout-1 result and Amendment 2 (iteration 2; written BEFORE the iteration-2 code was run on anything)

Holdout-1 (72 questions, sealed, evaluated once; `data/phase11_1/eval_holdout.json`), tau = 0.5, oracle routing for generation metrics:

| | B | C1@0.5 | C2@0.5 |
|---|---|---|---|
| oracle-correct answerables (of 40) | 40 | 37 | 37 |
| unsupported answers: absent-detail answered (of 15) | 9 | 0 | 0 |
| wrong-topic answers, router mode | 4 | 0 | 0 |
| citation-evidence failures | 0 | **1** | **1** |
| grounding failures / phantom / support-chain failures | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| router R@1 (untouched) / chunk R@1,3,5 | 13/40 ; 30,37,40 | identical | identical |

Rule outcome (section 6): rules 1, 2, 3, 4, 6 pass; **rule 5 FAILS (0 -> 1)**; rule 7 not evaluated. **C1/C2 are therefore NOT adopted as they stand.** C2's widening added nothing on holdout-1 (C2 = C1), so it also fails its own rule.
Failure analysis (read after the sealed run; everything below is observation, not tuning of C1):
* citation-evidence failure: "What happens when I calculate interest on an installment plan?" - the selected sentence covers the topic words (installment, plan, calculated) but not the predicate (calculate interest): the evidence sentence scored lower because every term counted equally.
* three false abstentions (P111H-024 "relationship", -036 "calculated" vs "calculations", and the paraphrase cases): (a) an abstract noun after "what is the ..." was treated as the asked-for term; (b) the stemmer does not conflate calculated / calculations.

Iteration 2 (candidate **C3** = C1 + C2 with three general changes; holdout-1 becomes DEV2 because it has now been seen):
1. own stemmer in the evidence layer that conflates -ate/-ated/-ation(s), -e/-es/-ed/-ing, -ment(s) (and keeps process / processes together);
2. question-meta nouns (relationship, difference, purpose, reason, meaning, kind, type, way, example, overview, ...) join the frame words;
3. **IDF-weighted focus coverage**: a focus term's weight is ln((N+1)/(df+0.5)) over the N sentences of the retrieved evidence (a term that occurs in every sentence, e.g. the page topic, counts little; a term that occurs nowhere counts most). tau semantics change accordingly, so tau is re-selected.
DEV2 = Phase 10 DEV + the 16 E2E + holdout-1. Selection rule for tau: unchanged (section 5 applied to DEV2: highest... among tau in the grid with oracle-correct >= B - 2 *per 41 answerable*, scaled: allowed loss = 5 % of DEV2 answerables, rounded down; choose the most absent-detail abstentions; ties -> smaller tau).
Sealed **holdout-2** (`data/evaluation/phase11_1_holdout2_questions.json`, 48 questions: 28 answerable, 10 absent-detail, 4 not-ingested, 2 unresolved, 4 out-of-domain; frozen and validated before the iteration-2 code existed; author had seen holdout-1 results and failures) is evaluated once with B, C1@tau*, C3@tau*, C3-without-widening. The adoption rules of section 6 apply unchanged to C3 (rule 5 included), with "B" and "<= 3 of 40" scaled to "<= 3 or 7.5 % of answerables, rounded down" (holdout-2 has 28 answerables -> at most 2 lost), and rule 7 on Phase 10 TEST.
Ship decision: C3 ships (with or without widening, per the widening rule) only if all rules pass; otherwise the product stays on B and the failure is reported.

### Amendment 2b (still before any iteration-2 run)
* A fourth general change: the cue word of a limit / default question (minimum, maximum, default ...) is removed from the focus terms because it is checked as a *kind* (IDF would otherwise give an absent cue word the highest weight and reject a sentence that states the limit in other words).
* The iteration-1 code is replaced, so the iteration-1 configs are not re-run (their results are saved in `eval_dev.json`, `eval_dev_round1.json`, `eval_holdout.json`). In every iteration-2 result file `C1` = iteration-2 code without widening and `C2` = iteration-2 code with widening; sets: `dev2`, `holdout2`.
* Holdout-2 configs: B, C1@tau*, C2@tau*. Phase 10 TEST is run once (only for the final candidate).

### Amendment 2c - DEV2 outcome (iteration 2, before holdout-2)
DEV2 = 91 queries (62 answerable-type incl. holdout-1; 29 unsupported-type). Allowed answerable loss = 4 (5 % of 91).

| variant | oracle-correct (B = 81) | unsupported answered (B = 20/29) | citation-evidence fails (B = 6) | wrong-topic router (B = 9) |
|---|---|---|---|---|
| with IDF, C1@0.5 / 0.6 / 0.67 | 67 / 60 / 55 | 0 / 0 / 0 | 2 / 1 / 1 | 0 |
| with IDF, C2@0.5 / 0.6 / 0.67 | 68 / 61 / 56 | 0 | 2 / 1 / 1 | 0 |
| **without IDF**, C1@0.5 / 0.6 / 0.67 | **78** / 73 / 64 | 1 / 1 / 0 | 4 / 5 / 3 | 0 |
| **without IDF**, C2@0.5 / 0.6 / 0.67 | **79** / 74 / 65 | 1 / 1 / 0 | 4 / 5 / 3 | 0 |

IDF fails the selection rule at every tau (best loss 13 > 4): it gives unmatched paraphrase words the largest weight and over-abstains. **IDF is rejected** (the switch `USE_IDF` stays, default OFF; results in `eval_dev2_idf.json`). Without IDF only tau = 0.5 qualifies (C1 loses 3, C2 loses 2) -> **tau* = 0.5, USE_IDF = False.** The stemmer, meta-noun and cue-word changes stay. Holdout-2 is now evaluated once with B, C1@0.5, C2@0.5.

## 10. Final evaluation and ship decision (written after holdout-2, test10, p9, p8 had been run once each)

Config for the decision: **C1 (evidence-aware extractive generator, no widening), tau = 0.5, USE_IDF off.** Oracle routing for generation metrics; router-mode for wrong-topic.

| set | n (answerable / unsupported) | oracle-correct B -> C1 | unsupported answered B -> C1 | citation-evidence fails B -> C1 | wrong-topic (router) B -> C1 | grounding / phantom / chain | router R@1, chunk R@1/3/5 |
|---|---|---|---|---|---|---|---|
| **holdout-2 (sealed, fresh)** | 28 / 10 | 25 -> 24 | 6 -> 0 | 2 -> 0 | 2 -> 0 | 0 / 0 / 0 | identical |
| Phase 10 TEST (once) | 41 / 12 | 32 -> 33 | 6 -> 4 | 3 -> 2 | 3 -> 2 | 0 / 0 / 0 | identical |
| holdout-1 (iteration 1 code; became DEV2) | 40 / 15 | 40 -> 37 | 9 -> 0 | 0 -> 1 | 4 -> 0 | 0 / 0 / 0 | identical |
| Phase 9 (127 q, regression) | 58 / 14 (oracle) | 58 -> 52 | 7 -> 0 | 0 -> 2 | 3 -> 0 | 0 / 0 / 0 | identical |
| Phase 8 (regression) | 51 / 11 | 51 -> 43 | 5 -> 1 | 4 -> 2 | 2 -> 1 | 0 / 0 / 0 | identical |

Adoption rules (section 6, scaled as in section 9) on holdout-2: (1) unsupported answered falls 6 -> 0 (>= 4) PASS; (2) answerable loss 1 (<= 2) PASS; (3) wrong-topic 2 -> 0 PASS; (4) 0 grounding / phantom / chain failures PASS; (5) citation-evidence failures 2 -> 0 PASS; (6) router top-1 and chunk recall identical PASS; (7) Phase 10 TEST loss -1 (a gain) and absent abstentions 6 -> 8 PASS. **C1 is adopted.**
C2 (widening) equals C1 on holdout-2 and on TEST, so the widening rule is not met -> **widening is NOT adopted** (it helped on DEV only).
Cost, stated plainly: on the older, larger regression sets C1 answers fewer answerable questions correctly (Phase 9 58 -> 52, Phase 8 51 -> 43, mostly paraphrase questions whose wording shares no stem with the page, now abstained) in exchange for 7 -> 0 and 5 -> 1 unsupported answers. The fresh holdouts show a smaller cost (-1/28, -3/40 on holdout-1, +1/41 on TEST). Pooled over the three sets never used for design (holdout-2, TEST, and holdout-1 before iteration 2) the loss is 3/109 answerable. Caveats: AI-authored questions, small n, single run, lexical check only; holdout-1 saw the iteration-1 candidate fail rule 5 and iteration 2 was designed after that, so holdout-2 is the only fully unbiased adoption set.
