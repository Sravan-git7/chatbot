# Phase 7F - out-of-domain detection for the card router

**Result in one line:** the rank-1 cosine similarities of in-domain and out-of-domain queries overlap substantially (AUROC 0.87), so **no refusal threshold is justified. `min_cosine` stays `None`** and the router is unchanged.

Scope kept: no change to retrieval, the router, the embedding model, card text, collection configuration, weights or Phase 4/5 expectations. No answer generation, no `rag_chat.py` or CLI change, no 7G, no page ingestion, no network, no commit, no push.

## Read this first: limits of the evidence

1. **The new queries were written by an AI agent, not a human.** I (the coding agent) typed all 110 queries individually, with no generation script and no LLM call. But I am a language model, so the statement "not LLM-generated" **cannot be made**. The honest statement is "authored directly by an AI agent, no generation pipeline, not human-written". This matches the precedent in `independent_queries.json` and is stated inside the query file. **A human-written set should be added before any threshold is trusted** (see section 10).
2. **144 in-domain and 62 OOD queries is a small sample.** It is enough to show that a threshold does not separate the classes. It is not enough to estimate production behaviour. The OOD mix is also adversarial by design (16 other-SAP-module and 14 adjacent-utility questions). The real traffic mix is unknown.
3. **The in-domain population is mostly not new.** 104 of the 144 are the Phase 4/5 queries. Phase 5 queries were deliberately hard (keyword-only or paraphrased).

## 1. How were the OOD queries authored?

- File: `data/evaluation/phase7F_ood_queries.json`. sha256 `631c7a52…dbe14`, pinned by a test.
- **Written and saved before any of its queries was embedded or routed.** I had seen only the card texts, the Phase 4/5 data and the five legacy OOD questions.
- **Labelling criteria are in the file.**
  - In-domain: the question is answered by the described scope of one or more of the 29 cards. Every in-domain query lists its expected card(s) and a **verbatim quote of that card's "What it covers" text** as the evidence basis. A test checks that the quote is really in the card.
  - OOD: the question is not about the topics of any of the 29 cards.
  - Ambiguous: a defensible reading could belong to either side. These 8 are excluded from the decision and are never relabelled.
- OOD categories (all realistic questions, none are nonsense):

  | Category | n |
  |---|---|
  | unrelated general | 10 |
  | other software / IT | 8 |
  | other SAP modules (SD, MM, CO, HCM, BTP, SuccessFactors…) | 16 |
  | utilities-adjacent but not covered | 14 |
  | lexical-overlap traps | 8 |
  | very short, unrelated | 6 |

- **Independence checks:** I ran these before any retrieval. No in-domain query repeats a Phase 4/5 query. No in-domain query shares more than 3 contiguous words with any card's `embedding_text`. This check caught 7 queries that shared 4 to 7 words with a card, and I reworded those 7 **before any retrieval**. No label or query changed after retrieval. Tests enforce all of this.
- **Decision rule C1-C3 was declared in the file before evaluation** (details in section 5).
- **Legacy OOD:** the five legacy questions q26-q30 (the user's own) were also routed, as a descriptive group.

## 2. How many queries were evaluated?

| Group | n | Used as |
|---|---|---|
| Phase 4 | 50 | in-domain |
| Phase 5 | 54 | in-domain |
| 7F in-domain | 40 | in-domain |
| **In-domain total** | **144** | decision |
| 7F OOD | 62 | OOD, decision |
| 7F ambiguous | 8 | descriptive only |
| Legacy q26-q30 | 5 | descriptive only |

Total routed: 219, each through the unchanged router with k=29 against the real `sap_m2c_card_v1` collection. The dev/test split follows a fixed rule from the file (alternating by sorted order within each label). In-domain splits 72/72. OOD splits 31/31.

## 3. Rank-1 score distributions

Score = rank-1 cosine **similarity** (= 1 - cosine distance). Every row in `phase7F_results.json` keeps `rank1_cosine_similarity` and `rank1_cosine_distance` as separate fields, and also holds rank-2 and the gap.

| | n | min | p5 | p25 | median | mean | p75 | p95 | max |
|---|---|---|---|---|---|---|---|---|---|
| In-domain (all) | 144 | 0.131 | 0.238 | 0.387 | **0.491** | 0.474 | 0.567 | 0.676 | 0.725 |
| OOD (7F) | 62 | -0.064 | -0.026 | 0.083 | **0.237** | 0.224 | 0.342 | 0.498 | 0.560 |

In-domain by group (min / median / max): Phase 4 0.244 / 0.554 / 0.725; Phase 5 0.131 / 0.381 / 0.662; 7F in-domain 0.372 / 0.494 / 0.685.

OOD by category (median, max, AUROC against all in-domain):

| Category | median | max | AUROC |
|---|---|---|---|
| unrelated general | 0.025 | 0.127 | 1.000 |
| other software / IT | 0.050 | 0.113 | 1.000 |
| very short unrelated | 0.138 | 0.272 | 0.975 |
| lexical-overlap trap | 0.225 | 0.309 | 0.941 |
| utilities-adjacent, not covered | 0.309 | 0.430 | 0.863 |
| **other SAP modules** | **0.448** | **0.560** | **0.661** |

Rank-1 correct vs wrong among in-domain queries: correct n=120, median 0.507; wrong n=24, median 0.378. AUROC 0.79, so the score is only weakly informative about whether the matched card is right. The rank1-rank2 gap as an OOD signal has AUROC 0.82 (descriptive only; it is not part of the rule).

## 4. How much do they overlap?

- **No clean gap.** The highest OOD score (0.560) is far above the lowest in-domain score (0.131). The overlap interval is [0.131, 0.560].
- **103 of 144 in-domain queries (72%) score at or below the best-scoring OOD query.**
- **40 of 62 OOD queries (65%) score at or above the weakest in-domain query.**
- **5 OOD queries score above the in-domain median and 30 score above the in-domain 5th percentile.**
- **AUROC 0.8715** (pooled). By in-domain group: Phase 4 0.94, 7F in-domain 0.92, Phase 5 0.78.
- The separation is real only for easy OOD: unrelated and other-IT questions are cleanly low (max 0.127), but questions about other SAP modules score as high as in-domain ones. The top OOD scores are all "SAP …" questions, e.g. SAP TM freight order 0.560 matched to M2C-03, SAP CO controlling area 0.507, ECC to S/4 conversion 0.505.
- **Post-hoc observation (added after the first run; descriptive; does not enter the rule):** 11 of 62 OOD queries contain the word "SAP" (median 0.470) against 1 of 144 in-domain queries. Without that word the pooled AUROC is 0.94. The in-domain queries almost never say "SAP", so the embedding model separates "mentions SAP" from "doesn't" more than "covered topic" from "not covered".

## 5. Is a threshold empirically justified?

**No.** The pre-declared rule needs all three criteria. Results:

| Criterion | Requirement | Observed | Pass |
|---|---|---|---|
| C1 sample adequacy | n_in ≥ 100, n_ood ≥ 50, ≥ 25 OOD in dev and test | 144 / 62 / 31 and 31 | yes |
| C2 pooled separation | AUROC ≥ 0.90 **and** some t with in-domain refusal ≤ 5% and OOD acceptance ≤ 20% | AUROC 0.8715. Best OOD acceptance at refusal ≤ 5% is **50%** (t = 0.237: 7 in-domain refused = 4.9%, 31 of 62 OOD accepted; 95% CI 38-62%) | **no** |
| C3 held-out | t* chosen on dev only; on test refusal ≤ 10% and OOD acceptance ≤ 25% | t* = 0.204 (dev: 0% refusal, 48% OOD accepted). On test: 1/72 in-domain refused, **18/31 = 58% OOD accepted** (CI 41-74%) | **no** |

I did not look for a threshold that passes. The rule was fixed first, and the sample passes C1 only.

## 6. If yes: what threshold?

Not applicable. **No threshold is proposed.**

## 7. If no: why not?

- At any threshold that keeps in-domain refusals near 5%, about half of the OOD queries are still accepted. In the other direction, refusing all OOD would also refuse about 72% of in-domain queries.
- The difficult OOD queries (other SAP modules, adjacent utilities topics) look like in-domain queries to this embedding model.
- The 5% in-domain refusal point is not a safe cost. At t = 0.25, 11 in-domain queries are already refused, including 9 of the 54 Phase 5 queries.

Fixed-grid what-if table. **Descriptive only; none of the rows is a proposal.** Refused counts, accept when similarity ≥ t:

| t | in-domain refused /144 | OOD accepted /62 | q26-q30 refused /5 | ambiguous refused /8 |
|---|---|---|---|---|
| 0.10 | 0 (0.0%) | 44 (71.0%) | 3 | 0 |
| 0.15 | 1 (0.7%) | 39 (62.9%) | 3 | 0 |
| 0.20 | 1 (0.7%) | 34 (54.8%) | 3 | 0 |
| 0.25 | 11 (7.6%) | 30 (48.4%) | 3 | 1 |
| 0.30 | 17 (11.8%) | 21 (33.9%) | 3 | 2 |
| 0.35 | 24 (16.7%) | 15 (24.2%) | 3 | 4 |
| 0.40 | 39 (27.1%) | 11 (17.7%) | 3 | 4 |
| 0.45 | 58 (40.3%) | 8 (12.9%) | 5 | 6 |
| 0.50 | 77 (53.5%) | 3 (4.8%) | 5 | 7 |
| 0.55 | 103 (71.5%) | 1 (1.6%) | 5 | 8 |
| 0.60 | 120 (83.3%) | 0 (0.0%) | 5 | 8 |
| 0.65 | 130 (90.3%) | 0 (0.0%) | 5 | 8 |
| 0.70 | 142 (98.6%) | 0 (0.0%) | 5 | 8 |

The legacy `MAX_DISTANCE = 1.0` is a squared-L2 cut-off that equals cosine ≥ 0.5. Row t = 0.50 shows what that cut-off would do on cards: it would refuse 53% of in-domain queries. This confirms that the legacy value must not be reused for cards.

**What evidence would reopen the question**
- A human-written, domain-reviewed OOD and in-domain set, ideally from real user questions. The rule would be re-applied unchanged (or a new rule declared before looking).
- Many more "other SAP module" and adjacent-utility OOD queries, since this is where the score fails. Enough for stable intervals (the OOD acceptance CI is currently ±12 points).
- A stronger signal than the single rank-1 cosine (for example rank-1 similarity combined with the gap, a lexical check or a reranker). That is a retrieval change and is out of scope for 7F.
- Evidence of what refusing wrongly costs (a refusal on an in-domain question) against answering an OOD question with a wrong topic.

## 8. Phase 4/5 regression

The default selector is the existing rank-1 selector, with no refusal.

- Phase 4: 50 of 50 rank-1, top-5, first-expected-rank and 6 dp distances equal the Phase 7E results. Metrics are unchanged: R@1 0.92, R@3 0.96, R@5 1.0, MRR 0.95 (46 hits@1).
- Phase 5: 54 of 54 unchanged. R@1 0.7222, R@3 0.7963, R@5 0.8704, MRR 0.7873 (39 hits@1).
- 0 queries refused; 0 rankings changed. Since no threshold is proposed there is no "intentional refusal" to compare.
- The router file and the 7A-7D files are hash-identical to their pinned values.

## 9. The five known OOD questions (q26-q30)

All five still return a rank-1 card, as in 7E. This is expected because the router has no cut-off.

| Question | Rank-1 | Similarity | Distance |
|---|---|---|---|
| q26 What is SAP HANA licensing cost? | M2C-11 | 0.401 | 0.599 |
| q27 Who is the CEO of SAP? | M2C-01 | 0.414 | 0.586 |
| q28 What is Python? | M2C-14 | 0.083 | 0.917 |
| q29 How do I install Windows 11? | M2C-24 | 0.070 | 0.930 |
| q30 What is the weather today? | M2C-08 | 0.042 | 0.958 |

q28-q30 are low (≤ 0.083), but q26 and q27 sit at about 0.40, above the median of the 7F OOD set and above 40 of the 144 in-domain scores (28%). "SAP" in the question lifts the score. A threshold between 0.09 and 0.40 would catch the three easy ones and leave q26/q27 answered, which is the "easy OOD only" pattern seen above.

## 10. What remains unresolved?

- **No OOD detection exists.** Off-topic questions still get a rank-1 card with a distance. A caller must not read rank 1 as "the question is covered". This is already the 7A contract and 7E's reason for keeping routed mode off.
- **No human-written evaluation set.** The 7F set is by an AI agent. All percentages are specific to it.
- **Small samples:** 62 OOD queries; ±12 point intervals.
- **SAP-module questions** are the hard case for this dense-only router, and the evidence suggests that the single-score approach cannot fix it. Options (reranker, lexical or topic-term check, a refusal prompt in the later answer stage) are not evaluated here.
- Carried over: only 1 of 29 topics has local page content (M2C-17), the four source issues (M2C-05, 14, 18, 23) are unresolved, and 7G (optional CLI switch) has not been started and needs your approval.

## Deviations and housekeeping to know about

- **File names:** I used the names you gave (`scripts/evaluate_ood.py`, `tests/test_phase7f.py`, `data/evaluation/phase7F_ood_queries.json`, `phase7F_results.json`, `phase7F_report.md`). The spec names `data/evaluation/card_out_of_domain_queries.json` and says 7F lives in `evaluate_two_stage.py`. I left `evaluate_two_stage.py` untouched because the 7E document is reproduced byte-identically and pinned.
- **Evaluator-side `make_selector(min_cosine)`** exists in `scripts/evaluate_ood.py` (similarity, inclusive `>=`, validated to [-1, 1], default `None`). It is a tested what-if hook, not wired into the router, orchestrator, `rag_chat.py` or any CLI. `DEFAULT_MIN_COSINE = None`.
- **Store rebuilt:** the sandbox had dropped `data/vector_store/` and the venv. I rebuilt both per the 7B/7E procedure (manifest written to `/tmp`). The protected manifest `5b3a5c30…` is unchanged.
- **Post-hoc analysis:** the "SAP" word breakdown was added after the first run. It is labelled as such and does not feed the decision.
- Nothing is committed. `.git` state has been lost between sessions before, so commit and push soon.

## Tests and artifacts

- Full suite with the store: **497 passed, 0 skipped, 0 failed** (448 before 7F + 49 new). Without the store: 469 passed, 28 skipped (store-gated tests only).
- Results file reproduced byte-identically on a second run (sha256 `40f8e536…`).
- New files: `scripts/evaluate_ood.py`, `tests/test_phase7f.py`, `data/evaluation/phase7F_ood_queries.json`, `data/evaluation/phase7F_results.json`, `data/phase7F_report.md`.
