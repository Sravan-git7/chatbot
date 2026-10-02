# Phase 5 report - retrieval robustness evaluation (evidence only)

Question: does retrieval stay reliable when queries are written like real users instead of being copied from the cards? The Phase 4 collection `sap_m2c_card_v1` and its results are a protected baseline and were **not** changed. Nothing here is integrated into the application, no production hybrid or new production collection exists, the embedding model is unchanged, and no SAP page was fetched. The output is evidence for the architecture decision and nothing more.

**Headline:** on independently worded queries the unchanged dense retriever scores Recall@1 **0.7222** and MRR **0.7873** (Phase 4 wording: 0.92 and 0.95). The controlled hybrid experiment does **not** meet the pre-declared rule for a measurable benefit (failed criteria: C1, C3, C6). **Recommendation: retain dense-only retrieval.**

## 1. Phase 4 baseline

* 29 cards, one vector per card, collection `sap_m2c_card_v1`, all-MiniLM-L6-v2, 384 dimensions, cosine distance, `embedding_text` (only `library_use` and `copyright_note` excluded).
* Recorded Phase 4 results on its 50 questions: Recall@1 0.92, Recall@3 0.96, Recall@5 1.0, MRR 0.95 (failed at rank 1: Q07, Q39, Q42, Q49).
* The baseline was reproduced before anything else: top-5 lists for all 50 questions are identical to the recorded ones (`True`, max similarity difference 0.0).
* The protected store was queried through a temporary copy. Raw store-file hashes are not a stable identity (any process that opens a Chroma store updates its bookkeeping files, and every rebuild creates a new segment id), so they were compared within the run only (unchanged by this evaluation = **True**). The store's identity is its content: the vectors read back from the collection differ from freshly encoded `embedding_text` vectors by at most 9e-08 (consistent = **True**), and the top-5 lists reproduce exactly. The hash of the freshly encoded float32 vectors equals the Phase 4 manifest hash: False (informational only: a bitwise hash is sensitive to encoding batch size, CPU and library version, and the per-vector difference is about 1e-7).
* Important: the Phase 4 questions were worded from the cards' own text, so they share vocabulary with the cards. Section 10 shows the consequence.

## 2. Independent dataset description

* `data/evaluation/independent_queries.json`: **54** queries (sha256 `1ce1306db646981b68245d75a1a912310ad3d760d90593bd005dfcc3500956e4`), each with an expected card, rationale, query type, difficulty and a **verbatim** evidence quote from the expected card's `full_text` (the builder refuses to write the file if a quote is not found).
* **Authorship disclosure:** the queries were written by hand by the AI coding agent working on this repository, inside `scripts/build_independent_queries.py`, before any Phase 5 retrieval was run, and were not changed after seeing results. They were not produced by an automated LLM generation pipeline, retrieval was not in the loop, and labels come from the card text only. They were **not** written by a human domain expert or collected from real users, which would be a stronger test (see limitations).
* Independence rules enforced by the builder: no query equals a Phase 4 question; no query shares more than 3 consecutive words with its expected card(s). Longest verbatim run per query: 1 word x 34, 2 words x 16, 3 words x 4.
* Query types: ambiguous 7, entity 9, keyword 12, natural 14, paraphrase 12.
* Length buckets by word count: long 27, short 7, very_short 20 (very_short = 1-4 words, short = 5-7, long = 8-20; no query is longer than 20 words).
* Difficulty (assigned by hand from written criteria before any run): easy 6, hard 23, medium 25.
* 43 of 54 queries are flagged `ambiguous` (a sibling card is plausible) and 5 have more than one accepted card. The flag is broad, so the `ambiguous` flag is not a clean subset; the query type `ambiguous` (7 queries) is the narrow group.
* Diagnostic slices (defined mechanically before the run): `very_short` 20, `rare_term` 24, `sibling_ambiguous` 43, `fragmented_term` 4, `no_lexical_overlap` 8. `rare_term` = a query term found in at most 2 of the 29 cards; `fragmented_term` = a term the tokenizer splits into 3 or more pieces; `no_lexical_overlap` = no query term appears in the expected card.
* Metric definition is the Phase 4 one: a hit is any expected card; `also_relevant` cards are listed for information and do not count.

## 3. Dense-only results (system A, the unchanged Phase 4 retriever)

| System | Queries | Recall@1 | Recall@3 | Recall@5 | MRR |
|---|--:|--:|--:|--:|--:|
| A dense only | 54 | 0.7222 | 0.7963 | 0.8704 | 0.7873 |

Chance level on 29 cards is about 3% for Recall@1 and 17% for Recall@5 (single expected card). Of 54 queries, 15 miss rank 1 and 11 miss the top 3. Paired Phase 4 vs independent: Recall@1 0.92 to 0.7222, MRR 0.95 to 0.7873.

## 4. BM25-only results (system B)

Transparent Okapi BM25 (k1 1.5, b 0.75) over the same `embedding_text` that is embedded, lowercase alphanumeric tokens, 33 Lucene English stopwords, **no stemming** (a documented limitation), min-max normalised only when combined.

| Set | System | Queries | Recall@1 | Recall@3 | Recall@5 | MRR |
|---|---|--:|--:|--:|--:|--:|
| independent | B BM25 only | 54 | 0.5370 | 0.6481 | 0.7778 | 0.6388 |
| Phase 4 | B BM25 only | 50 | 0.9800 | 1.0000 | 1.0000 | 0.9867 |

BM25 is strongest on the Phase 4 set and weakest on the independent set, which is what copied wording would produce (section 10).

## 5. Hybrid results (system C)

Score = `w_dense * minmax(cosine) + (1 - w_dense) * minmax(BM25)`, min-max per query over the 29 cards. Three fixed weights were chosen **before** any result: 0.75, 0.5 (declared primary, equal weight) and 0.25. No weight, stopword list or token rule was changed after looking at results, and nothing was tuned to an individual query.

| Set | System | Queries | Recall@1 | Recall@3 | Recall@5 | MRR |
|---|---|--:|--:|--:|--:|--:|
| independent | A dense only | 54 | 0.7222 | 0.7963 | 0.8704 | 0.7873 |
| independent | B BM25 only | 54 | 0.5370 | 0.6481 | 0.7778 | 0.6388 |
| independent | C hybrid w_dense=0.75 | 54 | 0.7407 | 0.8519 | 0.8889 | 0.8110 |
| independent | C hybrid w_dense=0.5 (primary) | 54 | 0.6667 | 0.7963 | 0.8704 | 0.7458 |
| independent | C hybrid w_dense=0.25 | 54 | 0.6296 | 0.7963 | 0.8148 | 0.7176 |
| Phase 4 | A dense only | 50 | 0.9200 | 0.9600 | 1.0000 | 0.9500 |
| Phase 4 | B BM25 only | 50 | 0.9800 | 1.0000 | 1.0000 | 0.9867 |
| Phase 4 | C hybrid w_dense=0.75 | 50 | 0.9600 | 1.0000 | 1.0000 | 0.9800 |
| Phase 4 | C hybrid w_dense=0.5 (primary) | 50 | 0.9800 | 1.0000 | 1.0000 | 0.9867 |
| Phase 4 | C hybrid w_dense=0.25 | 50 | 0.9800 | 1.0000 | 1.0000 | 0.9867 |

Paired comparison with dense on the independent set (rank of the first expected card):

| System | Improved | Worsened | Unchanged | Sign-test p (2-sided) | Gained rank 1 | Lost rank 1 |
|---|--:|--:|--:|--:|--:|--:|
| B BM25 only | 9 | 21 | 24 | 0.0428 | 5 | 15 |
| C hybrid w_dense=0.75 | 7 | 7 | 40 | 1.0 | 3 | 2 |
| C hybrid w_dense=0.5 (primary) | 7 | 16 | 31 | 0.0931 | 5 | 8 |
| C hybrid w_dense=0.25 | 7 | 18 | 29 | 0.0433 | 5 | 10 |

Primary hybrid (hybrid_0.5) against dense: MRR 0.7458 vs 0.7873, Recall@1 0.6667 vs 0.7222. Weight 0.75 is the only setting above dense, and only slightly (see section 11).

## 6. Breakdown by query type (independent set)

| Group / system | Queries | Recall@1 | Recall@3 | Recall@5 | MRR |
|---|--:|--:|--:|--:|--:|
| keyword / A dense only | 12 | 0.7500 | 0.8333 | 1.0000 | 0.8250 |
| keyword / B BM25 only | 12 | 0.8333 | 1.0000 | 1.0000 | 0.9167 |
| keyword / C hybrid w_dense=0.75 | 12 | 0.9167 | 1.0000 | 1.0000 | 0.9583 |
| keyword / C hybrid w_dense=0.5 (primary) | 12 | 0.9167 | 1.0000 | 1.0000 | 0.9583 |
| keyword / C hybrid w_dense=0.25 | 12 | 0.9167 | 1.0000 | 1.0000 | 0.9583 |
| entity / A dense only | 9 | 0.7778 | 0.8889 | 0.8889 | 0.8307 |
| entity / B BM25 only | 9 | 0.8889 | 1.0000 | 1.0000 | 0.9259 |
| entity / C hybrid w_dense=0.75 | 9 | 0.8889 | 1.0000 | 1.0000 | 0.9444 |
| entity / C hybrid w_dense=0.5 (primary) | 9 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| entity / C hybrid w_dense=0.25 | 9 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| natural / A dense only | 14 | 0.5714 | 0.7143 | 0.7143 | 0.6754 |
| natural / B BM25 only | 14 | 0.1429 | 0.2857 | 0.5714 | 0.3156 |
| natural / C hybrid w_dense=0.75 | 14 | 0.5714 | 0.7143 | 0.7857 | 0.6734 |
| natural / C hybrid w_dense=0.5 (primary) | 14 | 0.3571 | 0.5714 | 0.7143 | 0.4968 |
| natural / C hybrid w_dense=0.25 | 14 | 0.3571 | 0.6429 | 0.6429 | 0.4920 |
| paraphrase / A dense only | 12 | 0.6667 | 0.6667 | 0.8333 | 0.7236 |
| paraphrase / B BM25 only | 12 | 0.3333 | 0.3333 | 0.5000 | 0.4161 |
| paraphrase / C hybrid w_dense=0.75 | 12 | 0.5833 | 0.6667 | 0.7500 | 0.6556 |
| paraphrase / C hybrid w_dense=0.5 (primary) | 12 | 0.4167 | 0.5833 | 0.7500 | 0.5403 |
| paraphrase / C hybrid w_dense=0.25 | 12 | 0.3333 | 0.5000 | 0.5833 | 0.4606 |
| ambiguous / A dense only | 7 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| ambiguous / B BM25 only | 7 | 0.7143 | 0.8571 | 1.0000 | 0.8214 |
| ambiguous / C hybrid w_dense=0.75 | 7 | 0.8571 | 1.0000 | 1.0000 | 0.9286 |
| ambiguous / C hybrid w_dense=0.5 (primary) | 7 | 0.8571 | 1.0000 | 1.0000 | 0.9048 |
| ambiguous / C hybrid w_dense=0.25 | 7 | 0.7143 | 1.0000 | 1.0000 | 0.8333 |

By difficulty:

| Group / system | Queries | Recall@1 | Recall@3 | Recall@5 | MRR |
|---|--:|--:|--:|--:|--:|
| easy / A dense only | 6 | 0.8333 | 0.8333 | 0.8333 | 0.8571 |
| easy / B BM25 only | 6 | 0.8333 | 0.8333 | 1.0000 | 0.8750 |
| easy / C hybrid w_dense=0.75 | 6 | 0.8333 | 1.0000 | 1.0000 | 0.9167 |
| easy / C hybrid w_dense=0.5 (primary) | 6 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| easy / C hybrid w_dense=0.25 | 6 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| medium / A dense only | 25 | 0.6800 | 0.8400 | 0.8400 | 0.7712 |
| medium / B BM25 only | 25 | 0.4400 | 0.6400 | 0.7600 | 0.5880 |
| medium / C hybrid w_dense=0.75 | 25 | 0.7200 | 0.8400 | 0.8800 | 0.7904 |
| medium / C hybrid w_dense=0.5 (primary) | 25 | 0.6000 | 0.7600 | 0.8400 | 0.6962 |
| medium / C hybrid w_dense=0.25 | 25 | 0.5600 | 0.8000 | 0.8000 | 0.6738 |
| hard / A dense only | 23 | 0.7391 | 0.7391 | 0.9130 | 0.7867 |
| hard / B BM25 only | 23 | 0.5652 | 0.6087 | 0.7391 | 0.6323 |
| hard / C hybrid w_dense=0.75 | 23 | 0.7391 | 0.8261 | 0.8696 | 0.8058 |
| hard / C hybrid w_dense=0.5 (primary) | 23 | 0.6522 | 0.7826 | 0.8696 | 0.7334 |
| hard / C hybrid w_dense=0.25 | 23 | 0.6087 | 0.7391 | 0.7826 | 0.6914 |

Diagnostic slices (a query can belong to several):

| Group / system | Queries | Recall@1 | Recall@3 | Recall@5 | MRR |
|---|--:|--:|--:|--:|--:|
| very_short / A dense only | 20 | 0.8000 | 0.9000 | 1.0000 | 0.8617 |
| very_short / B BM25 only | 20 | 0.8500 | 1.0000 | 1.0000 | 0.9250 |
| very_short / C hybrid w_dense=0.75 | 20 | 0.9500 | 1.0000 | 1.0000 | 0.9750 |
| very_short / C hybrid w_dense=0.5 (primary) | 20 | 0.9500 | 1.0000 | 1.0000 | 0.9750 |
| very_short / C hybrid w_dense=0.25 | 20 | 0.9000 | 1.0000 | 1.0000 | 0.9500 |
| rare_term / A dense only | 24 | 0.7917 | 0.8750 | 0.9583 | 0.8490 |
| rare_term / B BM25 only | 24 | 0.8750 | 0.9583 | 1.0000 | 0.9271 |
| rare_term / C hybrid w_dense=0.75 | 24 | 0.9167 | 1.0000 | 1.0000 | 0.9583 |
| rare_term / C hybrid w_dense=0.5 (primary) | 24 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| rare_term / C hybrid w_dense=0.25 | 24 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| sibling_ambiguous / A dense only | 43 | 0.7442 | 0.7907 | 0.8605 | 0.7986 |
| sibling_ambiguous / B BM25 only | 43 | 0.4651 | 0.5814 | 0.7209 | 0.5755 |
| sibling_ambiguous / C hybrid w_dense=0.75 | 43 | 0.6977 | 0.8140 | 0.8605 | 0.7743 |
| sibling_ambiguous / C hybrid w_dense=0.5 (primary) | 43 | 0.5814 | 0.7442 | 0.8372 | 0.6808 |
| sibling_ambiguous / C hybrid w_dense=0.25 | 43 | 0.5349 | 0.7442 | 0.7674 | 0.6453 |
| fragmented_term / A dense only | 4 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| fragmented_term / B BM25 only | 4 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| fragmented_term / C hybrid w_dense=0.75 | 4 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| fragmented_term / C hybrid w_dense=0.5 (primary) | 4 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| fragmented_term / C hybrid w_dense=0.25 | 4 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| no_lexical_overlap / A dense only | 8 | 0.2500 | 0.3750 | 0.5000 | 0.3902 |
| no_lexical_overlap / B BM25 only | 8 | 0.0000 | 0.0000 | 0.0000 | 0.0714 |
| no_lexical_overlap / C hybrid w_dense=0.75 | 8 | 0.2500 | 0.3750 | 0.3750 | 0.3556 |
| no_lexical_overlap / C hybrid w_dense=0.5 (primary) | 8 | 0.0000 | 0.1250 | 0.1250 | 0.1299 |
| no_lexical_overlap / C hybrid w_dense=0.25 | 8 | 0.0000 | 0.0000 | 0.0000 | 0.1007 |

Reading: lexical and hybrid retrieval help on keyword and entity queries and on the rare-term slice; they hurt on natural and paraphrase queries, where users' words are absent from the card text. Groups have 4 to 14 queries each, so single-digit differences are not reliable.

## 7. Breakdown by query length (independent set)

| Group / system | Queries | Recall@1 | Recall@3 | Recall@5 | MRR |
|---|--:|--:|--:|--:|--:|
| very_short / A dense only | 20 | 0.8000 | 0.9000 | 1.0000 | 0.8617 |
| very_short / B BM25 only | 20 | 0.8500 | 1.0000 | 1.0000 | 0.9250 |
| very_short / C hybrid w_dense=0.75 | 20 | 0.9500 | 1.0000 | 1.0000 | 0.9750 |
| very_short / C hybrid w_dense=0.5 (primary) | 20 | 0.9500 | 1.0000 | 1.0000 | 0.9750 |
| very_short / C hybrid w_dense=0.25 | 20 | 0.9000 | 1.0000 | 1.0000 | 0.9500 |
| short / A dense only | 7 | 0.8571 | 0.8571 | 0.8571 | 0.8776 |
| short / B BM25 only | 7 | 0.7143 | 0.8571 | 1.0000 | 0.7976 |
| short / C hybrid w_dense=0.75 | 7 | 0.7143 | 1.0000 | 1.0000 | 0.8571 |
| short / C hybrid w_dense=0.5 (primary) | 7 | 0.8571 | 1.0000 | 1.0000 | 0.9048 |
| short / C hybrid w_dense=0.25 | 7 | 0.8571 | 1.0000 | 1.0000 | 0.9048 |
| long / A dense only | 27 | 0.6296 | 0.7037 | 0.7778 | 0.7089 |
| long / B BM25 only | 27 | 0.2593 | 0.3333 | 0.5556 | 0.3856 |
| long / C hybrid w_dense=0.75 | 27 | 0.5926 | 0.7037 | 0.7778 | 0.6776 |
| long / C hybrid w_dense=0.5 (primary) | 27 | 0.4074 | 0.5926 | 0.7407 | 0.5348 |
| long / C hybrid w_dense=0.25 | 27 | 0.3704 | 0.5926 | 0.6296 | 0.4969 |

Very short = 1-4 words, short = 5-7, long = 8-20. The `short` bucket has only 7 queries.

## 8. Failure analysis

### 8.1 Dense failures on the independent set

| ID | Query | Expected | Dense rank | Dense top-1 (cos) | Expected cos | BM25 rank | Hybrid 0.5 rank | Pattern |
|---|---|---|--:|---|--:|--:|--:|---|
| P5-01 | Where do I start if I need to understand how customers, premises and meters fit together in the system? | M2C-01 | 9 | M2C-05 (0.4431) | 0.3502 | 8 | 12 | no_lexical_path |
| P5-02 | What happens in the system when a new tenant gets connected? | M2C-03 | 2 | M2C-29 (0.3562) | 0.2789 | 13 | 3 | no_lexical_path |
| P5-03 | A customer is leaving the property. What needs to happen with their last bill and meter reading? | M2C-04 | 8 | M2C-08 (0.5031) | 0.388 | 4 | 4 | no_lexical_path |
| P5-05 | How do I follow up on customers who have not paid on time? | M2C-26 | 13 | M2C-16 (0.217) | 0.1441 | 26 | 16 | no_lexical_path |
| P5-06 | Can I spread a large overdue balance over several payments? | M2C-23 | 2 | M2C-20 (0.2417) | 0.2404 | 25 | 7 | no_lexical_path |
| P5-07 | Where can I find out how a payment that just arrived gets matched to what the customer owes? | M2C-20 | 7 | M2C-22 (0.3112) | 0.2837 | 4 | 3 | no_lexical_path |
| P5-24 | reversal | M2C-22 | 5 | M2C-29 (0.1305) | 0.0828 | 1 | 1 | lexical_signal_present |
| P5-25 | KPIs | M2C-16 | 2 | M2C-08 (0.2068) | 0.194 | 1 | 1 | lexical_signal_present |
| P5-26 | FI-CA document | M2C-14 | 5 | M2C-18 (0.4521) | 0.3678 | 1 | 1 | lexical_signal_present |
| P5-31 | Filling gaps in usage data between two known readings | M2C-09 | 6 | M2C-10 (0.3879) | 0.2795 | 13 | 13 | no_lexical_path |
| P5-32 | Checking the quality of submitted consumption figures and fixing wrong ones before charging | M2C-06 | 15 | M2C-11 (0.3692) | 0.215 | 8 | 16 | no_lexical_path |
| P5-33 | Looking into money received from customers that can't be assigned | M2C-19 | 5 | M2C-27 (0.2586) | 0.2248 | 21 | 9 | no_lexical_path |
| P5-34 | Different situations in which open amounts get settled against payments | M2C-21 | 4 | M2C-20 (0.42) | 0.2668 | 6 | 5 | no_lexical_path |
| P5-39 | Point of Delivery and Connection Object | M2C-01 | 7 | M2C-29 (0.3326) | 0.2468 | 1 | 1 | lexical_signal_present |
| P5-43 | catch-up bill | M2C-08 | 3 | M2C-16 (0.2505) | 0.2229 | 1 | 1 | lexical_signal_present |

### 8.2 The four known Phase 4 failures under every system

| ID | Query | Expected | A dense only | B BM25 only | C hybrid w_dense=0.75 | C hybrid w_dense=0.5 (primary) | C hybrid w_dense=0.25 |
|---|---|---|--:|--:|--:|--:|--:|
| Q07 | Installment Plan Overview | M2C-23 | 2 | 1 | 1 | 1 | 1 |
| Q39 | payment clarification | M2C-19 | 4 | 1 | 1 | 1 | 1 |
| Q42 | subledger processing | M2C-17 | 4 | 1 | 1 | 1 | 1 |
| Q49 | What is needed for final billing when a customer moves out? | M2C-04 | 2 | 1 | 2 | 1 | 1 |

Cells are the rank of the expected card (1 = correct). All four known failures reach rank 1 under BM25 and the primary hybrid. That is a fact about these four queries, which are copied from card wording; it does not show the hybrid is better in general.

Counts: 15 dense misses at rank 1; {'lexical_signal_present (BM25 ranks the expected card 1-2)': 5, 'no_lexical_path (BM25 ranks the expected card 4 or worse)': 10} ; near-ties (top-1 gap below 0.02): 2; top-1 card in the expected card's category: 3; failures containing a fragmented query term: 0; fixed to rank 1 by the primary hybrid: 5.

Card similarity structure: mean cosine between cards of the same category 0.8248 (40 pairs), across categories 0.662 (366 pairs).

### 8.3 Analysis (hand-written, evidence-referenced)


Scope: the four known Phase 4 failures (Q07, Q39, Q42, Q49) and the 15 independent queries (of 54) for which the
unchanged dense retriever does not return an expected card at rank 1. The numbers below are read from
`data/evaluation/phase5_results.json` (`failure_diagnostics`, `tokenization`, `failure_pattern_counts_phase5`,
`datasets.*.slices`). Where the evidence does not isolate a cause, this file says so.

Method limits. Both query sets are small (one query moves R@1 by about 2 points). The failure-pattern labels are
assigned by a mechanical rule (BM25 rank of the expected card: 1-2 = "lexical signal present", 4 or worse = "no lexical
path"), not by judgement about the cause. Section-level similarities (query vs each section of a card, computed on the
fly, nothing stored) are a diagnostic only, not a proposed representation.

#### 8.3.1 What the independent failures look like

| pattern (mechanical rule) | count of 15 | members |
|---|---|---|
| Lexical signal present: BM25 ranks the expected card 1-2 | 5 | P5-24, P5-25, P5-26, P5-39, P5-43 |
| No lexical path: BM25 ranks the expected card 4 or worse | 10 | P5-01, 02, 03, 05, 06, 07, 31, 32, 33, 34 (BM25 rank 8, 13, 4, 26, 25, 4, 13, 8, 21, 6) |

All five "lexical signal" failures are short keyword or entity queries (`reversal`, `KPIs`, `FI-CA document`,
`Point of Delivery and Connection Object`, `catch-up bill`). Dense similarity is low for all of them (expected-card
cosine 0.08 to 0.37) and BM25 and the primary hybrid both put the expected card at rank 1. This is the clearest
demonstrated benefit of a lexical signal.

All ten "no lexical path" failures are natural or paraphrase queries in which few or none of the content words appear in
the expected card (for example P5-05 "follow up on customers who have not paid on time" against the dunning card,
dense rank 13, expected-card cosine 0.144). BM25 cannot repair these and the hybrid does not either: at w=0.5 the
expected card reaches rank 1 for none of them, and ranks worsen for several (P5-05 13 to 16, P5-32 15 to 16,
P5-01 9 to 12). Across the whole independent set the 8 queries with zero BM25 score on the expected card score
R@1 0.25 (dense), 0.00 (BM25) and 0.00 (hybrid 0.5). This is a vocabulary gap between the user's words and the card
text. Neither retriever bridges it reliably, and dense does better than lexical on it.

#### 8.3.2 Q39-style short queries ("payment clarification", Phase 4, dense rank 4)

- The query has 2 content words. Both occur in the expected card M2C-19. Only `payment` occurs in the top-1 card
  (M2C-20). `clarification` occurs in exactly one card (document frequency 1).
- Dense cosine: expected 0.3464, top-1 0.3839. All similarities are low.
- BM25 and every hybrid weight rank M2C-19 first.
- On the independent set the 20 very short queries (1-4 words) show: dense R@1 0.80 and MRR 0.8617. BM25 is 0.85 and
  0.925. Hybrid 0.5 is 0.95 and 0.975. The lexical signal helps this slice, but the slice is 20 queries and made up
  largely of keyword and entity queries with a distinctive word.
- Cause attribution: a lexical signal is available and dense similarity is weak. The data supports "query context" as a
  contributing factor (very few words give the encoder little to work with), but no experiment here isolates it.

#### 8.3.3 Q42-style rare compound terms ("subledger processing", Phase 4, dense rank 4)

- `subledger` occurs in exactly one card (M2C-17), and `processing` is a generic word. Top-1 (M2C-15, "Processing Budget
  Billing Plans") matches only `processing`. Expected cosine 0.2278, top-1 0.2484.
- BM25 and every hybrid weight rank M2C-17 first.
- Tokenizer: `subledger` becomes `sub ##led ##ger` (3 pieces). **But tokenizer fragmentation is not shown to be the
  cause.** Evidence: (a) none of the 15 independent dense failures contains a fragmented query term
  (`with_fragmented_query_terms` = 0); (b) the same failure signature appears for unfragmented words (`reversal`,
  `KPIs`, `catch-up bill`); (c) independent queries whose expected card contains a fragmented term (4 queries: P5-16,
  P5-23, P5-45, P5-49) all rank the expected card first under dense, while on the Phase 4 set the 15 such queries have
  dense MRR 0.90 against 0.9714 for the 35 without. The two sets disagree in direction, and both groups are small.
  The Phase 4 statement that the split is associated with the miss is therefore weakened: the common factor in
  these failures is a single rare word with weak dense signal, whether or not it is fragmented.
- Card representation: for M2C-17 the best-matching section scores 0.4939 (`what_it_covers`) against 0.2278 for the
  whole-card embedding. The vector for the whole card is a blend, and a one-word query scores low against a blend.
  In all 15 independent failures the expected card's best section also scores above its whole-card similarity
  (see `section_level`). Caution: the best section is a maximum over several sections, so it is biased upward
  by construction. This shows that a single blended vector can score lower than one of its parts, not that dilution
  caused any particular miss. A prose-only representation does not help (see analysis section 6).

#### 8.3.4 Q07-style near-duplicate families ("Installment Plan Overview", Phase 4, dense rank 2)

- The query equals the title of M2C-23. Expected 0.6299, top-1 sibling M2C-24 ("Creating Installment Plans") 0.6323.
  Gap 0.0024. Card-to-card cosine of the pair is 0.9187 and they share a category.
- BM25 and every hybrid weight rank M2C-23 first, because `overview` occurs only in M2C-23.
- Card representation: the title section alone scores 1.0 against this query for M2C-23 and 0.9006 for M2C-24, but the
  whole-card vectors differ by only 0.0024 in the wrong direction. The title match is diluted by the rest of the card
  text.
- Across the collection, mean cosine between cards of the same category is 0.8248 (40 pairs), against 0.662 across
  categories (366 pairs). Sibling similarity is high by construction. It makes near-ties likely, and near-ties
  flip on small differences.
- Near-ties alone explain little on the independent set: only 2 of the 15 failures have a top-1 gap below 0.02
  (P5-06 gap 0.0013 and P5-25 gap 0.0128 are the two smallest, and P5-06 is cross-category). Three of 15 have the top-1 card
  in the same category as the expected card. Most independent failures are a different kind of failure
  (vocabulary gap or weak signal), not sibling confusion.

#### 8.3.5 Q49-style overlaps ("What is needed for final billing when a customer moves out?", Phase 4, dense rank 2)

- Expected M2C-04 (Move-Out Process) 0.4335, top-1 M2C-02 (Move-In/Out Overview, also relevant) 0.4415. Gap 0.008.
  The pair share a category (card-to-card cosine 0.8567).
- Five of the query's content terms appear in both cards; `moves` and `needed` appear in no card. Dense and lexical
  signals are both close for this pair. BM25 and the hybrids at w=0.5 and 0.25 rank M2C-04 first. At w=0.75 it stays at rank 2.
- This is an overlap where the top-1 card is also a legitimate answer. The metric is strict by design (only the expected
  card counts), so the miss is partly a label-granularity effect. The 7 independent queries labelled `ambiguous`
  (several plausible cards) score dense R@1 1.00, so the label-granularity effect is not driving the independent result.

#### 8.3.6 Card representation checks

- URL tokens. Each `embedding_text` contains the printed SAP URL. Its hexadecimal identifiers account for 45.6% to
  55.1% of the wordpieces in a card's embedding text (mean 50.8%). The identifiers are noise from a search point of view.
- Ablation: re-encoding each card with the URL and reference line removed (prose-only, computed in memory, not stored)
  does **not** improve retrieval. Independent set: R@1 0.5556, MRR 0.6793 (dense 0.7222, 0.7873). 17 queries are worse
  and 5 better. On the Phase 4 set: MRR 0.9049 (dense 0.95). So the URL block is not shown to hurt, and removing it is
  not supported by this evidence. We do not know why the URL block helps (the query sets are small and the block is
  shared by every card), and no reason is asserted.
- This ablation does not justify any change to `embedding_text`. It is evidence only.

#### 8.3.7 Query-wording effects

- Dense R@1 by query type (independent set): ambiguous 1.00 (n=7), entity 0.78 (9), keyword 0.75 (12), paraphrase 0.67
  (12), natural 0.57 (14). The long natural and paraphrase queries are where dense is weakest. R@1 by length bucket:
  very short 0.80 (20), short (5-7 words) 0.86 (7), long (8-20 words) 0.63 (27).
- BM25 collapses on the same queries: natural R@1 0.14 and paraphrase 0.33. Hybrid 0.5 lowers natural R@1 from 0.57 to
  0.36 and paraphrase from 0.67 to 0.42. This is where the hybrid harm comes from.
- `cash desk` (P5-18) is a demonstrated stemming gap: the expected card contains `desks` twice and `desk` never, so the
  BM25 tokenizer (no stemming, by design) scores it on `cash` alone (BM25 rank 2). Dense gets it at rank 1.

#### 8.3.8 Causes: what is and is not supported

| candidate cause | verdict | evidence |
|---|---|---|
| Lexical signal | **Supported** for short keyword and entity queries | 5 of 15 independent failures and all 4 Phase 4 failures have BM25 rank 1 or 2 for the expected card. The primary hybrid fixes all 4 of the known failures and 5 of the 15 independent ones. |
| Vocabulary gap (user words absent from the card) | **Supported** as the largest group | 10 of 15 independent failures; 8 queries with zero BM25 score score R@1 0.25 (dense) and 0.00 (hybrid 0.5). |
| Tokenizer fragmentation | **Not supported** as a cause | Zero fragmented query terms in the 15 independent failures, and the Phase 4 vs independent comparison disagrees in direction (small groups). Fragmentation of the four Phase 4 terms is factual and is reported in report section 9. |
| Sibling similarity | **Partly supported** for Q07 and Q49 | Gaps 0.0024 and 0.008 with high card-to-card cosine. Only 2 of 15 independent failures are near-ties. |
| Query context (few words) | **Plausible, not isolated** | Very short queries have low absolute cosine, but they also perform better than long queries in rank terms. |
| Card representation (single blended vector) | **Weak evidence only** | Best-section similarity exceeds whole-card similarity in all 15 failures, but that is a maximum over sections and biased upward. The URL block is half of the tokens but removing it does not help. |
| Other | not investigated | For example label granularity (Q49) and the small sample sizes. |

## 9. Tokenization findings

`BertTokenizer` (vocabulary 30522), the tokenizer of the unchanged model (`max_seq_length` 256). Terms of the card vocabulary that split into 3 or more word pieces (4.9% of 287 alphabetic card terms; 16 of 327 query terms are fragmented):

| Term | Word pieces | Cards containing it (- = not a query term, not counted) |
|---|---|---|
| `clarification` | `cl ##ari ##fication` | 1 |
| `delinquency` | `del ##in ##que ##ncy` | 1 |
| `disconnect` | `disco ##nne ##ct` | - |
| `disconnection` | `disco ##nne ##ction` | - |
| `escalation` | `es ##cala ##tion` | - |
| `extrapolation` | `extra ##pol ##ation` | 1 |
| `interpolation` | `inter ##pol ##ation` | 1 |
| `invoices` | `in ##vo ##ices` | - |
| `invoicing` | `in ##vo ##icing` | - |
| `receivables` | `rec ##ei ##vable ##s` | - |
| `reconnection` | `rec ##onne ##ction` | - |
| `redistributed` | `red ##ist ##ri ##bu ##ted` | - |
| `subledger` | `sub ##led ##ger` | 1 |
| `troubleshooting` | `troubles ##hoot ##ing` | - |

* The hexadecimal identifiers inside the printed SAP URLs fragment into many pieces and take 45.6% to 55.1% of each card's `embedding_text` word pieces (mean 50.8%). See the ablation in 8.3.6: removing them did not improve retrieval.
* Fragmentation of the failed Phase 4 terms is factual (`clarification`, `subledger`). Fragmentation as the **cause** of the failures is not supported (8.3.3): no independent failure contains a fragmented query term, and the effect on retrieval points in opposite directions on the two sets.
* Effect of a fragmented term in the expected card (MRR with / without, dense | BM25 | hybrid 0.5):

  * phase5: 4 queries with / rest without: dense 1.0 / 0.7703 | bm25 1.0 / 0.6099 | hybrid_0.5 1.0 / 0.7255
  * phase4: 15 queries with / rest without: dense 0.9 / 0.9714 | bm25 1.0 / 0.981 | hybrid_0.5 1.0 / 0.981

The model was not changed. The study only shows the splits and correlates them with outcomes.

## 10. Comparison against Phase 4

| Retriever | Phase 4 R@1 | Independent R@1 | Phase 4 MRR | Independent MRR | Drop in MRR |
|---|--:|--:|--:|--:|--:|
| A dense only | 0.9200 | 0.7222 | 0.9500 | 0.7873 | 0.1627 |
| B BM25 only | 0.9800 | 0.5370 | 0.9867 | 0.6388 | 0.3479 |
| C hybrid w_dense=0.75 | 0.9600 | 0.7407 | 0.9800 | 0.8110 | 0.1690 |
| C hybrid w_dense=0.5 (primary) | 0.9800 | 0.6667 | 0.9867 | 0.7458 | 0.2409 |
| C hybrid w_dense=0.25 | 0.9800 | 0.6296 | 0.9867 | 0.7176 | 0.2691 |

* Dense drops from MRR 0.9500 to 0.7873 and Recall@5 from 1.0000 to 0.8704. The Phase 4 figures overstate retrieval quality for user-style wording.
* On the Phase 4 set a plain lexical retriever (BM25) scores MRR 0.9867, **higher than dense** (0.9500); on the independent set the order reverses (0.6388 vs 0.7873). That reversal is consistent with the Phase 4 questions sharing words with the cards. The Phase 4 set is therefore used here only as a harm check for hybrid, not as evidence for it.
* Both sets are small (one query is about 2 points) and share the same 29 cards, so neither number is a production estimate.
* Phase 4 control (`full_text` embedded in memory): R@1 0.88, MRR 0.9262 against 0.92 and 0.95 - inconclusive, unchanged. Prose-only ablation (8.3.6): independent MRR 0.6793 and Phase 4 MRR 0.9049, both below the evaluated `embedding_text`, so no representation change is indicated by this phase.

## 11. Whether hybrid gives a measurable benefit

The decision rule was written into `scripts/evaluate_phase5.py` before any Phase 5 result existed. Hybrid counts as beneficial only if every criterion holds for the primary weight (0.5):

| Criterion | Rule | Evidence | Result |
|---|---|---|---|
| C1 | MRR gain >= 0.03 | dense 0.7873, hybrid 0.7458, delta -0.0415 | **FAIL** |
| C2 | Recall@3 and Recall@5 not lower | delta R@3 0.0, delta R@5 0.0 | pass |
| C3 | improved > worsened and sign-test p <= 0.10 | improved 7, worsened 16, p 0.0931 | **FAIL** |
| C4 | very_short and rare_term slices do not lose MRR | very_short: 0.8617 to 0.975; rare_term: 0.849 to 1.0 | pass |
| C5 | Phase-4 set: MRR and Recall@1 drop <= 0.02 | hybrid minus dense on the Phase 4 set: MRR +0.0367, R@1 +0.0600 (no drop) | pass |
| C6 | MRR improves for >= 2 of 3 weights | delta MRR by dense weight: 0.75: +0.0237, 0.5: -0.0415, 0.25: -0.0697 | **FAIL** |

**Verdict from the rule: NOT convincing under the pre-declared rule: retain dense-only retrieval.**

What the evidence does and does not show:

* Recall@1 alone is not the criterion, and it is not even favourable for the primary weight (0.6667 vs 0.7222).
* Where hybrid clearly helps: very short queries, keyword and entity queries and the rare-term slice (sections 6-7), and it fixes the four known Phase 4 failures and 5 of the 15 independent dense misses at rank 1.
* Where it clearly hurts: natural-language and paraphrase queries (R@1 at w=0.5: natural 0.57 to 0.36; paraphrase 0.67 to 0.42) and queries with no lexical overlap with the card. More queries worsen than improve at w=0.5 (7 improved vs 16 worsened).
* Weight 0.75 changes less: MRR +0.0237 and Recall@3 +0.0556 over dense, but 7 queries improve and 7 worsen (sign test p = 1.0) and the MRR gain is below the +0.03 threshold. It is the only weight of three that beats dense, so it cannot be called robust.
* The per-slice gains are a post-hoc reading of a 54-query set. They are a hypothesis for a new held-out set, not a finding to act on. The weights were not adjusted to rescue the hybrid.
* The benefit of a lexical signal therefore depends on the mix of queries users actually send. This report cannot estimate that mix.

## 12. Recommendation for the next phase

1. **Retain dense-only retrieval** (`sap_m2c_card_v1`, unchanged) as the retriever. The evidence does not justify a hybrid in production, and it does not justify changing the embedding text or the model.
2. Do not treat the Phase 4 scores as the expected quality. With user-style wording, about 13% of queries miss the top 5 and about 28% miss rank 1. Any downstream answer-quality evaluation should run with top-k of at least 5 and should report retrieval misses separately from generation errors.
3. The largest group of independent failures (10 of 15) is a vocabulary gap between the user's words and the card text, which neither BM25 nor the hybrid fixed. Candidate remedies (for example how user queries are phrased or expanded, or whether card descriptions cover user vocabulary) would each need their own phase and their own evidence; none is tested here, and no source content may be invented.
4. If a lexical component is revisited, test it on a **new** query set written before looking at these results, ideally by a human or from real user questions, and pre-declare any condition (for example a query-length rule) in advance. The short-query and rare-term gains seen here are the hypothesis to test, not a result.
5. Enlarge the evaluation set beyond 54 queries before drawing conclusions from differences of a few points. One query is about 2 points.
6. Keep the application, `sap_docs` and the protected RAG scripts untouched until an integration is explicitly approved.

## Limitations

* Small query sets (54 and 50 on 29 cards); one query is about 2 points; per-group tables have 4 to 27 queries.
* The independent queries were written by the AI coding agent, not by domain experts or real users (section 2); they may share the writer's habits of phrasing with any other model-written text.
* BM25 uses no stemming. A lexical retriever with stemming would behave differently (example: `cash desk` vs `desks`), and was not tested.
* Failure-pattern labels are mechanical and do not prove a cause; section-level similarities are diagnostic only.
* The embedding model weights come from the third-party PyPI package `gt-all-minilm-l6-v2`, validated earlier by reproducing the baseline; this is not the official download.
* Unresolved source-review items (#05, #14, #18, #23) are carried unchanged as metadata and were not touched.

## Appendix A. Per-query results (dense, the unchanged retriever)

Rank = position of the first expected card among 29. Top 5 = `card id (cosine)`.

| ID | Type | Len | Diff | Query | Expected | Rank | Top 5 (cosine) | Pass |
|---|---|---|---|---|---|--:|---|---|
| P5-01 | natural | long | medium | Where do I start if I need to understand how customers, premises and meters fit together in the system? | M2C-01 | **9** | M2C-05 (0.4431); M2C-06 (0.4374); M2C-02 (0.4327); M2C-10 (0.4235); M2C-07 (0.4065) | FAIL |
| P5-02 | natural | long | medium | What happens in the system when a new tenant gets connected? | M2C-03 | **2** | M2C-29 (0.3562); M2C-03 (0.2789); M2C-02 (0.2427); M2C-04 (0.2197); M2C-25 (0.1751) | FAIL |
| P5-03 | natural | long | medium | A customer is leaving the property. What needs to happen with their last bill and meter reading? | M2C-04 | **8** | M2C-08 (0.5031); M2C-10 (0.4784); M2C-06 (0.444); M2C-02 (0.4259); M2C-29 (0.4129) | FAIL |
| P5-04 | natural | long | easy | Why did a customer get a bill based on an estimate instead of an actual reading? | M2C-08 | 1 | M2C-08 (0.5429); M2C-09 (0.3853); M2C-13 (0.3628); M2C-11 (0.3565); M2C-06 (0.3319) | PASS |
| P5-05 | natural | long | hard | How do I follow up on customers who have not paid on time? | M2C-26 | **13** | M2C-16 (0.217); M2C-22 (0.1987); M2C-13 (0.1969); M2C-08 (0.195); M2C-27 (0.1746) | FAIL |
| P5-06 | natural | long | medium | Can I spread a large overdue balance over several payments? | M2C-23 | **2** | M2C-20 (0.2417); M2C-23 (0.2404); M2C-13 (0.2199); M2C-25 (0.2145); M2C-22 (0.201) | FAIL |
| P5-07 | natural | long | medium | Where can I find out how a payment that just arrived gets matched to what the customer owes? | M2C-20 | **7** | M2C-22 (0.3112); M2C-27 (0.308); M2C-14 (0.3021); M2C-11 (0.2972); M2C-23 (0.2934) | FAIL |
| P5-08 | natural | long | easy | How is electricity supply switched off and back on when a customer doesn't pay? | M2C-29 | 1 | M2C-29 (0.3539); M2C-02 (0.2653); M2C-03 (0.2618); M2C-13 (0.2467); M2C-22 (0.2446) | PASS |
| P5-09 | natural | long | medium | Which topic explains how an invoice gets created after the bill has been calculated? | M2C-14 | 1 | M2C-14 (0.5455); M2C-15 (0.5096); M2C-16 (0.4819); M2C-11 (0.4092); M2C-13 (0.3855) | PASS |
| P5-10 | natural | long | hard | How can I keep an eye on meter reads that came in wrong or are stuck? | M2C-07 | 1 | M2C-07 (0.4678); M2C-06 (0.4578); M2C-08 (0.4448); M2C-10 (0.3777); M2C-05 (0.3136) | PASS |
| P5-11 | natural | long | medium | Is there a way to hand unpaid accounts over to an external debt collector? | M2C-27 | 1 | M2C-27 (0.3032); M2C-28 (0.2712); M2C-22 (0.2665); M2C-17 (0.2464); M2C-18 (0.2451) | PASS |
| P5-12 | natural | long | medium | How do system interfaces to outside collection companies work? | M2C-28 | 1 | M2C-28 (0.4532); M2C-27 (0.4136); M2C-03 (0.356); M2C-22 (0.3247); M2C-05 (0.3117) | PASS |
| P5-13 | natural | long | hard | What does a customer's financial account in the billing system control? | M2C-18 | 1 | M2C-18 (0.5175); M2C-17 (0.4785); M2C-11 (0.4728); M2C-12 (0.4538); M2C-13 (0.4392) | PASS |
| P5-14 | natural | long | medium | How do customers pay a steady monthly amount instead of variable bills? | M2C-13 | 1 | M2C-13 (0.4242); M2C-15 (0.3624); M2C-12 (0.3241); M2C-24 (0.3175); M2C-16 (0.315) | PASS |
| P5-15 | keyword | very_short | hard | budget billing | M2C-13, M2C-15 | 1 | M2C-13 (0.574); M2C-15 (0.5042); M2C-11 (0.4421); M2C-12 (0.4038); M2C-16 (0.3458) | PASS |
| P5-16 | keyword | very_short | easy | extrapolation | M2C-09 | 1 | M2C-09 (0.2379); M2C-08 (0.1377); M2C-10 (0.0767); M2C-11 (0.0701); M2C-13 (0.0397) | PASS |
| P5-17 | keyword | very_short | medium | open items | M2C-20 | 1 | M2C-20 (0.2159); M2C-27 (0.0652); M2C-03 (0.0382); M2C-10 (0.0381); M2C-26 (0.0333) | PASS |
| P5-18 | keyword | very_short | medium | cash desk | M2C-22 | 1 | M2C-22 (0.3504); M2C-13 (0.2191); M2C-21 (0.2181); M2C-26 (0.2176); M2C-27 (0.2058) | PASS |
| P5-19 | keyword | very_short | hard | dunning | M2C-26 | 1 | M2C-26 (0.2296); M2C-08 (0.0814); M2C-27 (0.0763); M2C-28 (0.0751); M2C-29 (0.061) | PASS |
| P5-20 | keyword | very_short | hard | meter estimation | M2C-08, M2C-09 | 1 | M2C-08 (0.5328); M2C-09 (0.4628); M2C-06 (0.3948); M2C-07 (0.3827); M2C-10 (0.3435) | PASS |
| P5-21 | keyword | very_short | hard | billing schema | M2C-11, M2C-12 | 1 | M2C-11 (0.5467); M2C-12 (0.5172); M2C-14 (0.4625); M2C-13 (0.4584); M2C-16 (0.4267) | PASS |
| P5-22 | keyword | very_short | hard | installment plan display | M2C-25 | 1 | M2C-25 (0.6007); M2C-23 (0.5471); M2C-24 (0.5286); M2C-13 (0.3693); M2C-15 (0.3201) | PASS |
| P5-23 | keyword | very_short | easy | delinquency | M2C-29 | 1 | M2C-29 (0.2133); M2C-04 (0.1543); M2C-03 (0.0945); M2C-21 (0.0829); M2C-27 (0.0758) | PASS |
| P5-24 | keyword | very_short | hard | reversal | M2C-22 | **5** | M2C-29 (0.1305); M2C-04 (0.1253); M2C-25 (0.0839); M2C-03 (0.0837); M2C-22 (0.0828) | FAIL |
| P5-25 | keyword | very_short | medium | KPIs | M2C-16 | **2** | M2C-08 (0.2068); M2C-16 (0.194); M2C-10 (0.1881); M2C-06 (0.1848); M2C-07 (0.182) | FAIL |
| P5-26 | keyword | very_short | hard | FI-CA document | M2C-14 | **5** | M2C-18 (0.4521); M2C-28 (0.415); M2C-17 (0.3858); M2C-26 (0.3772); M2C-14 (0.3678) | FAIL |
| P5-27 | paraphrase | long | hard | Explain how a household is registered as using a service point for the first time | M2C-03 | 1 | M2C-03 (0.4161); M2C-02 (0.3769); M2C-05 (0.3242); M2C-10 (0.2898); M2C-01 (0.2783) | PASS |
| P5-28 | paraphrase | long | medium | Stopping service for a customer and finishing up the account | M2C-04 | 1 | M2C-04 (0.3407); M2C-29 (0.3044); M2C-02 (0.2818); M2C-03 (0.2313); M2C-16 (0.1872) | PASS |
| P5-29 | paraphrase | long | hard | Calculating what to charge from usage figures using price tables | M2C-11 | 1 | M2C-11 (0.3829); M2C-13 (0.3368); M2C-12 (0.2809); M2C-16 (0.2706); M2C-15 (0.2672) | PASS |
| P5-30 | paraphrase | long | medium | What do I do when a meter cannot be read and a figure has to be guessed? | M2C-08 | 1 | M2C-08 (0.4552); M2C-06 (0.3966); M2C-07 (0.3672); M2C-10 (0.3258); M2C-05 (0.2876) | PASS |
| P5-31 | paraphrase | long | hard | Filling gaps in usage data between two known readings | M2C-09 | **6** | M2C-10 (0.3879); M2C-08 (0.3835); M2C-07 (0.3241); M2C-06 (0.3239); M2C-26 (0.3104) | FAIL |
| P5-32 | paraphrase | long | medium | Checking the quality of submitted consumption figures and fixing wrong ones before charging | M2C-06 | **15** | M2C-11 (0.3692); M2C-16 (0.3277); M2C-27 (0.3234); M2C-13 (0.3159); M2C-15 (0.3135) | FAIL |
| P5-33 | paraphrase | long | hard | Looking into money received from customers that can't be assigned | M2C-19 | **5** | M2C-27 (0.2586); M2C-22 (0.2521); M2C-16 (0.2389); M2C-13 (0.2293); M2C-19 (0.2248) | FAIL |
| P5-34 | paraphrase | long | hard | Different situations in which open amounts get settled against payments | M2C-21 | **4** | M2C-20 (0.42); M2C-19 (0.3222); M2C-22 (0.2753); M2C-21 (0.2668); M2C-27 (0.2657) | FAIL |
| P5-35 | paraphrase | long | hard | Shop-counter payments from outside partners being posted immediately | M2C-22 | 1 | M2C-22 (0.3791); M2C-20 (0.3109); M2C-27 (0.2708); M2C-19 (0.2521); M2C-23 (0.2228) | PASS |
| P5-36 | paraphrase | long | medium | Changing a payment agreement after it has been set up for a customer | M2C-25 | 1 | M2C-25 (0.3107); M2C-23 (0.2431); M2C-20 (0.236); M2C-24 (0.2231); M2C-19 (0.2193) | PASS |
| P5-37 | paraphrase | long | medium | Setting up a new payment arrangement and checking whether the customer qualifies | M2C-24 | 1 | M2C-24 (0.2931); M2C-25 (0.2786); M2C-19 (0.272); M2C-20 (0.2646); M2C-23 (0.2607) | PASS |
| P5-38 | paraphrase | long | hard | Dashboards for how well the bill runs are doing | M2C-16 | 1 | M2C-16 (0.416); M2C-15 (0.3838); M2C-02 (0.3648); M2C-13 (0.3627); M2C-11 (0.334) | PASS |
| P5-39 | entity | short | easy | Point of Delivery and Connection Object | M2C-01 | **7** | M2C-29 (0.3326); M2C-03 (0.2807); M2C-10 (0.2678); M2C-22 (0.2641); M2C-04 (0.2619) | FAIL |
| P5-40 | entity | very_short | medium | operand and rate type | M2C-12 | 1 | M2C-12 (0.2937); M2C-11 (0.2112); M2C-21 (0.196); M2C-09 (0.1948); M2C-19 (0.1709) | PASS |
| P5-41 | entity | very_short | medium | print documents | M2C-14 | 1 | M2C-14 (0.2068); M2C-27 (0.1001); M2C-06 (0.0767); M2C-16 (0.0738); M2C-11 (0.0701) | PASS |
| P5-42 | entity | very_short | hard | technical installations and devices | M2C-05 | 1 | M2C-05 (0.2949); M2C-03 (0.2137); M2C-01 (0.204); M2C-09 (0.192); M2C-29 (0.1755) | PASS |
| P5-43 | entity | very_short | medium | catch-up bill | M2C-08 | **3** | M2C-16 (0.2505); M2C-15 (0.2374); M2C-08 (0.2229); M2C-13 (0.2157); M2C-26 (0.2132) | FAIL |
| P5-44 | entity | short | easy | SAP enterprise services for collection agencies | M2C-28 | 1 | M2C-28 (0.6619); M2C-27 (0.5572); M2C-17 (0.5094); M2C-26 (0.5058); M2C-02 (0.5054) | PASS |
| P5-45 | entity | very_short | medium | recall of receivables | M2C-27 | 1 | M2C-27 (0.5618); M2C-26 (0.3064); M2C-23 (0.261); M2C-20 (0.2401); M2C-28 (0.2313) | PASS |
| P5-46 | entity | very_short | medium | debt arrangement | M2C-23 | 1 | M2C-23 (0.3709); M2C-24 (0.3383); M2C-25 (0.2985); M2C-15 (0.274); M2C-27 (0.2572) | PASS |
| P5-47 | entity | short | hard | meter hardware and technical setup | M2C-05 | 1 | M2C-05 (0.4427); M2C-06 (0.4256); M2C-07 (0.4032); M2C-08 (0.3702); M2C-10 (0.3538) | PASS |
| P5-48 | ambiguous | long | hard | What do I need to know about move-in? | M2C-03 | 1 | M2C-03 (0.3275); M2C-02 (0.2067); M2C-04 (0.1798); M2C-10 (0.1438); M2C-01 (0.0829) | PASS |
| P5-49 | ambiguous | short | medium | Explain budget billing in the invoicing context | M2C-15 | 1 | M2C-15 (0.6436); M2C-14 (0.5489); M2C-13 (0.5261); M2C-16 (0.4881); M2C-11 (0.4602) | PASS |
| P5-50 | ambiguous | short | medium | How do installment plans work? | M2C-23 | 1 | M2C-23 (0.5939); M2C-24 (0.5896); M2C-25 (0.5169); M2C-15 (0.3425); M2C-13 (0.3361) | PASS |
| P5-51 | ambiguous | short | hard | How is meter reading handled? | M2C-06 | 1 | M2C-06 (0.5711); M2C-10 (0.5408); M2C-07 (0.5305); M2C-08 (0.5184); M2C-05 (0.4838) | PASS |
| P5-52 | ambiguous | short | hard | Payments that come in from customers | M2C-19, M2C-20, M2C-22 | 1 | M2C-20 (0.3499); M2C-22 (0.3484); M2C-19 (0.3415); M2C-23 (0.3208); M2C-24 (0.3143) | PASS |
| P5-53 | ambiguous | very_short | hard | Contract account | M2C-17, M2C-18 | 1 | M2C-18 (0.5248); M2C-17 (0.4783); M2C-24 (0.271); M2C-12 (0.2679); M2C-23 (0.2612) | PASS |
| P5-54 | ambiguous | very_short | medium | Billing process overview | M2C-11 | 1 | M2C-11 (0.5669); M2C-15 (0.553); M2C-14 (0.5278); M2C-16 (0.519); M2C-12 (0.4774) | PASS |

## Appendix B. Rank of the expected card per query and system (independent set)

| ID | Query | A dense only | B BM25 only | C hybrid w_dense=0.75 | C hybrid w_dense=0.5 (primary) | C hybrid w_dense=0.25 |
|---|---|--:|--:|--:|--:|--:|
| P5-01 | Where do I start if I need to understand how customers, premises and meters fit together in the system? | 9 | 8 | 9 | 12 | 12 |
| P5-02 | What happens in the system when a new tenant gets connected? | 2 | 13 | 2 | 3 | 3 |
| P5-03 | A customer is leaving the property. What needs to happen with their last bill and meter reading? | 8 | 4 | 6 | 4 | 3 |
| P5-04 | Why did a customer get a bill based on an estimate instead of an actual reading? | 1 | 1 | 1 | 1 | 1 |
| P5-05 | How do I follow up on customers who have not paid on time? | 13 | 26 | 15 | 16 | 16 |
| P5-06 | Can I spread a large overdue balance over several payments? | 2 | 25 | 3 | 7 | 10 |
| P5-07 | Where can I find out how a payment that just arrived gets matched to what the customer owes? | 7 | 4 | 4 | 3 | 3 |
| P5-08 | How is electricity supply switched off and back on when a customer doesn't pay? | 1 | 4 | 1 | 1 | 1 |
| P5-09 | Which topic explains how an invoice gets created after the bill has been calculated? | 1 | 2 | 1 | 1 | 1 |
| P5-10 | How can I keep an eye on meter reads that came in wrong or are stuck? | 1 | 8 | 1 | 4 | 7 |
| P5-11 | Is there a way to hand unpaid accounts over to an external debt collector? | 1 | 5 | 1 | 3 | 3 |
| P5-12 | How do system interfaces to outside collection companies work? | 1 | 2 | 1 | 1 | 1 |
| P5-13 | What does a customer's financial account in the billing system control? | 1 | 1 | 1 | 1 | 1 |
| P5-14 | How do customers pay a steady monthly amount instead of variable bills? | 1 | 16 | 1 | 6 | 6 |
| P5-15 | budget billing | 1 | 1 | 1 | 1 | 1 |
| P5-16 | extrapolation | 1 | 1 | 1 | 1 | 1 |
| P5-17 | open items | 1 | 2 | 1 | 1 | 1 |
| P5-18 | cash desk | 1 | 2 | 1 | 2 | 2 |
| P5-19 | dunning | 1 | 1 | 1 | 1 | 1 |
| P5-20 | meter estimation | 1 | 1 | 1 | 1 | 1 |
| P5-21 | billing schema | 1 | 1 | 1 | 1 | 1 |
| P5-22 | installment plan display | 1 | 1 | 1 | 1 | 1 |
| P5-23 | delinquency | 1 | 1 | 1 | 1 | 1 |
| P5-24 | reversal | 5 | 1 | 1 | 1 | 1 |
| P5-25 | KPIs | 2 | 1 | 1 | 1 | 1 |
| P5-26 | FI-CA document | 5 | 1 | 2 | 1 | 1 |
| P5-27 | Explain how a household is registered as using a service point for the first time | 1 | 4 | 1 | 1 | 2 |
| P5-28 | Stopping service for a customer and finishing up the account | 1 | 1 | 1 | 1 | 1 |
| P5-29 | Calculating what to charge from usage figures using price tables | 1 | 5 | 1 | 2 | 3 |
| P5-30 | What do I do when a meter cannot be read and a figure has to be guessed? | 1 | 1 | 1 | 1 | 1 |
| P5-31 | Filling gaps in usage data between two known readings | 6 | 13 | 10 | 13 | 13 |
| P5-32 | Checking the quality of submitted consumption figures and fixing wrong ones before charging | 15 | 8 | 15 | 16 | 16 |
| P5-33 | Looking into money received from customers that can't be assigned | 5 | 21 | 6 | 9 | 9 |
| P5-34 | Different situations in which open amounts get settled against payments | 4 | 6 | 5 | 5 | 5 |
| P5-35 | Shop-counter payments from outside partners being posted immediately | 1 | 1 | 1 | 1 | 1 |
| P5-36 | Changing a payment agreement after it has been set up for a customer | 1 | 1 | 1 | 1 | 1 |
| P5-37 | Setting up a new payment arrangement and checking whether the customer qualifies | 1 | 14 | 3 | 5 | 10 |
| P5-38 | Dashboards for how well the bill runs are doing | 1 | 18 | 1 | 3 | 7 |
| P5-39 | Point of Delivery and Connection Object | 7 | 1 | 2 | 1 | 1 |
| P5-40 | operand and rate type | 1 | 1 | 1 | 1 | 1 |
| P5-41 | print documents | 1 | 1 | 1 | 1 | 1 |
| P5-42 | technical installations and devices | 1 | 1 | 1 | 1 | 1 |
| P5-43 | catch-up bill | 3 | 1 | 1 | 1 | 1 |
| P5-44 | SAP enterprise services for collection agencies | 1 | 1 | 1 | 1 | 1 |
| P5-45 | recall of receivables | 1 | 1 | 1 | 1 | 1 |
| P5-46 | debt arrangement | 1 | 1 | 1 | 1 | 1 |
| P5-47 | meter hardware and technical setup | 1 | 3 | 1 | 1 | 1 |
| P5-48 | What do I need to know about move-in? | 1 | 1 | 1 | 1 | 1 |
| P5-49 | Explain budget billing in the invoicing context | 1 | 1 | 1 | 1 | 1 |
| P5-50 | How do installment plans work? | 1 | 1 | 1 | 1 | 1 |
| P5-51 | How is meter reading handled? | 1 | 4 | 2 | 3 | 3 |
| P5-52 | Payments that come in from customers | 1 | 1 | 1 | 1 | 1 |
| P5-53 | Contract account | 1 | 1 | 1 | 1 | 1 |
| P5-54 | Billing process overview | 1 | 2 | 1 | 1 | 2 |

## Appendix C. Files and integrity

* `data/evaluation/independent_queries.json` sha256 `1ce1306db646981b68245d75a1a912310ad3d760d90593bd005dfcc3500956e4`
* `data/evaluation/phase5_results.json` sha256 `2ca554287c9c2397f125e086cd121e5bd67983588bf798011e0298b286f0ef6d`
* protected, read only: `data/evaluation/card_retrieval_results.json` sha256 `c1b0459779eeb0ac0f4dbf26c6e128302c91ad7be0aa75db6a2d657e45c49206`; `data/card_collection_manifest.json` sha256 `5b3a5c30bc637c8b61573983a16cf252f7899d2c279eae3895e06476482d2731`
* retrieval units sha256 `f5e9b908c9b7374ffab5adbc6f8afb9b5597de91cb50ec3fea8b9b3db2d3ff21`; source corpus sha256 `0ee5cb8bda192250a14acdde95617e15b71f6fd803847fe25bae9999ea7e9e76`
* Phase 5 code: `scripts/build_independent_queries.py`, `scripts/phase5_retrievers.py`, `scripts/evaluate_phase5.py`, `scripts/build_phase5_report.py`; tests in `tests/test_phase5.py`.
* Reproduce: `python scripts/build_independent_queries.py && python scripts/evaluate_phase5.py && python scripts/build_phase5_report.py` (the store must exist; rebuild it with `build_card_collection.py --manifest <tmp path>` so the Phase 4 manifest is not overwritten). No network is used.

## Tests

260 passed (full suite: pytest tests -q; 219 existing + 41 new Phase 5 tests)
