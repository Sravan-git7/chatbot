# Phase 5 failure analysis (hand-written from `phase5_results.json`)

Scope: the four known Phase 4 failures (Q07, Q39, Q42, Q49) and the 15 independent queries (of 54) for which the
unchanged dense retriever does not return an expected card at rank 1. The numbers below are read from
`data/evaluation/phase5_results.json` (`failure_diagnostics`, `tokenization`, `failure_pattern_counts_phase5`,
`datasets.*.slices`). Where the evidence does not isolate a cause, this file says so.

Method limits. Both query sets are small (one query moves R@1 by about 2 points). The failure-pattern labels are
assigned by a mechanical rule (BM25 rank of the expected card: 1-2 = "lexical signal present", 4 or worse = "no lexical
path"), not by judgement about the cause. Section-level similarities (query vs each section of a card, computed on the
fly, nothing stored) are a diagnostic only, not a proposed representation.

## 1. What the independent failures look like

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

## 2. Q39-style short queries ("payment clarification", Phase 4, dense rank 4)

- The query has 2 content words. Both occur in the expected card M2C-19. Only `payment` occurs in the top-1 card
  (M2C-20). `clarification` occurs in exactly one card (document frequency 1).
- Dense cosine: expected 0.3464, top-1 0.3839. All similarities are low.
- BM25 and every hybrid weight rank M2C-19 first.
- On the independent set the 20 very short queries (1-4 words) show: dense R@1 0.80 and MRR 0.8617. BM25 is 0.85 and
  0.925. Hybrid 0.5 is 0.95 and 0.975. The lexical signal helps this slice, but the slice is 20 queries and made up
  largely of keyword and entity queries with a distinctive word.
- Cause attribution: a lexical signal is available and dense similarity is weak. The data supports "query context" as a
  contributing factor (very few words give the encoder little to work with), but no experiment here isolates it.

## 3. Q42-style rare compound terms ("subledger processing", Phase 4, dense rank 4)

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

## 4. Q07-style near-duplicate families ("Installment Plan Overview", Phase 4, dense rank 2)

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

## 5. Q49-style overlaps ("What is needed for final billing when a customer moves out?", Phase 4, dense rank 2)

- Expected M2C-04 (Move-Out Process) 0.4335, top-1 M2C-02 (Move-In/Out Overview, also relevant) 0.4415. Gap 0.008.
  The pair share a category (card-to-card cosine 0.8567).
- Five of the query's content terms appear in both cards; `moves` and `needed` appear in no card. Dense and lexical
  signals are both close for this pair. BM25 and the hybrids at w=0.5 and 0.25 rank M2C-04 first. At w=0.75 it stays at rank 2.
- This is an overlap where the top-1 card is also a legitimate answer. The metric is strict by design (only the expected
  card counts), so the miss is partly a label-granularity effect. The 7 independent queries labelled `ambiguous`
  (several plausible cards) score dense R@1 1.00, so the label-granularity effect is not driving the independent result.

## 6. Card representation checks

- URL tokens. Each `embedding_text` contains the printed SAP URL. Its hexadecimal identifiers account for 45.6% to
  55.1% of the wordpieces in a card's embedding text (mean 50.8%). The identifiers are noise from a search point of view.
- Ablation: re-encoding each card with the URL and reference line removed (prose-only, computed in memory, not stored)
  does **not** improve retrieval. Independent set: R@1 0.5556, MRR 0.6793 (dense 0.7222, 0.7873). 17 queries are worse
  and 5 better. On the Phase 4 set: MRR 0.9049 (dense 0.95). So the URL block is not shown to hurt, and removing it is
  not supported by this evidence. We do not know why the URL block helps (the query sets are small and the block is
  shared by every card), and no reason is asserted.
- This ablation does not justify any change to `embedding_text`. It is evidence only.

## 7. Query-wording effects

- Dense R@1 by query type (independent set): ambiguous 1.00 (n=7), entity 0.78 (9), keyword 0.75 (12), paraphrase 0.67
  (12), natural 0.57 (14). The long natural and paraphrase queries are where dense is weakest. R@1 by length bucket:
  very short 0.80 (20), short (5-7 words) 0.86 (7), long (8-20 words) 0.63 (27).
- BM25 collapses on the same queries: natural R@1 0.14 and paraphrase 0.33. Hybrid 0.5 lowers natural R@1 from 0.57 to
  0.36 and paraphrase from 0.67 to 0.42. This is where the hybrid harm comes from.
- `cash desk` (P5-18) is a demonstrated stemming gap: the expected card contains `desks` twice and `desk` never, so the
  BM25 tokenizer (no stemming, by design) scores it on `cash` alone (BM25 rank 2). Dense gets it at rank 1.

## 8. Causes: what is and is not supported

| candidate cause | verdict | evidence |
|---|---|---|
| Lexical signal | **Supported** for short keyword and entity queries | 5 of 15 independent failures and all 4 Phase 4 failures have BM25 rank 1 or 2 for the expected card. The primary hybrid fixes all 4 of the known failures and 5 of the 15 independent ones. |
| Vocabulary gap (user words absent from the card) | **Supported** as the largest group | 10 of 15 independent failures; 8 queries with zero BM25 score score R@1 0.25 (dense) and 0.00 (hybrid 0.5). |
| Tokenizer fragmentation | **Not supported** as a cause | Zero fragmented query terms in the 15 independent failures, and the Phase 4 vs independent comparison disagrees in direction (small groups). Fragmentation of the four Phase 4 terms is factual and is reported in report section 9. |
| Sibling similarity | **Partly supported** for Q07 and Q49 | Gaps 0.0024 and 0.008 with high card-to-card cosine. Only 2 of 15 independent failures are near-ties. |
| Query context (few words) | **Plausible, not isolated** | Very short queries have low absolute cosine, but they also perform better than long queries in rank terms. |
| Card representation (single blended vector) | **Weak evidence only** | Best-section similarity exceeds whole-card similarity in all 15 failures, but that is a maximum over sections and biased upward. The URL block is half of the tokens but removing it does not help. |
| Other | not investigated | For example label granularity (Q49) and the small sample sizes. |
