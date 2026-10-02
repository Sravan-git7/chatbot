# Phase 9 report — Real corpus completion, retrieval validation & LLM evaluation

**Status: PARTIALLY COMPLETE.** Corpus completion (9A.2) and the Ollama evaluation (9C) are **BLOCKED** by the environment (re-verified in the completion pass: `help.sap.com` drops the TLS handshake, and there is no Ollama, no model and no route to download one). Fresh retrieval validation (9B), page retrieval, the chunking comparison, the gate analysis, the source chains and the extractive end-to-end evaluation were completed on the 7-page corpus.

> **Ollama evaluation blocked: local model unavailable.**
> No LLM metric in this report was measured. No LLM metric was estimated or inferred.

All numbers below come from `data/evaluation/phase9_results.json` (deterministic) and `phase9_failure_audit.json`; timings are in `phase9_performance.json`.

## 1. Executive summary

| Item | Result |
|---|---|
| Cards / pages with real text | 29 cards, **7 pages available, 22 missing** (help.sap.com unreachable; 0 pages fetched) |
| Fresh query set | 127 AI-authored queries, frozen before retrieval (sha256 `28f03e57…5309`) |
| Card router, all 111 gold-card queries | R@1 **0.4595**, R@3 0.7027, R@5 0.8018, MRR 0.6133 |
| Card router, 69 answerable queries | R@1 **0.3333**, R@3 0.5942, R@5 0.6957, MRR 0.5051 |
| Page retrieval, inside the gold page | R@1 0.7971, R@3 0.9275, R@5 1.0, MRR 0.8756 (evidence in context 100 %) |
| Extractive answer, oracle routing | 58/69 answerable answered, grounded and cited from the gold page (0.8406) |
| Extractive answer, real router | 20/69 answerable answered (0.2899) |
| Phantom citations / grounding failures among answers | 0 / 0 |
| Ollama / LLM metrics | **BLOCKED — not measured** |
| Regression | Phase 4, Phase 5 and Phase 8 results unchanged |

Main finding: with the real router the pipeline answers fewer than one in three answerable questions. The loss is in card routing and in the lexical gates, not in page retrieval or grounding. All of this is on a 7-page corpus and an AI-authored query set.

## COMPLETED / BLOCKED / NOT CLAIMED

**COMPLETED (executed and measured):** 29-card corpus audit; frozen 127-query set; card router metrics and failure classification; page retrieval metrics; controlled chunking comparison (default kept); extractive end-to-end evaluation in router and oracle modes; gate distribution analysis; 238 source chains (127 real-router + 111 oracle) with six traceability checks each; CLI runs (`--generator extractive`, and `--generator ollama` failing loudly); verifier tests with six stub fabrications; performance for the extractive path; Phase 4/5/8 regression; full test suite; determinism of all result files.

**BLOCKED (needs something this environment does not have):**
* **Remaining official SAP Help pages (22 of 29 cards):** `help.sap.com` resolves and accepts the TCP connection, then closes the TLS handshake (`SSL_ERROR_SYSCALL` from curl, `SSLZeroReturnError` from requests). Two runs of `page_fetch.py` (`fetch_attempt_log.json`, `fetch_attempt_log_run2.json`) saved 0 pages. I did not try to evade the block.
* **Real Ollama / local-LLM evaluation:** no `ollama` binary, nothing on 127.0.0.1:11434, no `ollama` Python package, and `ollama.com` / Hugging Face are unreachable, so no model can be obtained. Ollama evaluation blocked: local model unavailable.
* **Extractive-vs-LLM comparison, real-LLM grounding, citation, abstention and fabrication rates, LLM latency.**

**NOT CLAIMED (could not be truthfully established):**
* Coverage of all 29 cards. Only 7 pages are real.
* Any property of a real LLM. The six stub fabrications test the verifier only; they do not show how an LLM behaves.
* Multi-section / multi-chunk question behaviour. The frozen set has no query with more than one evidence passage, so this was not evaluated.
* A justified OOD threshold or a better chunking or router configuration. No held-out set exists.
* That the 22 missing pages would route or retrieve like the 7 present ones.

## 2. Scope and disclosure of how this work was done

* The first Phase 9 task text began with "verify HEAD, clean tree, baseline; do not modify anything yet". I treated that as covering verification only and worked additively (new files only) until the completion request, which explicitly authorises the commit and push.
* The local branch pointer had been reset to `d85c31e` while the Phase 8 commit `30bbc95` existed on `origin/arena/01a0ed60-chatbot`. In the completion pass I moved the pointer with `git update-ref` (old value checked) and refreshed the index with `git read-tree 30bbc95`. This is not a reset: the working tree was not touched and nothing was lost. `git status` then showed only the Phase 9 files as untracked, which confirms that the tree equalled `30bbc95` plus Phase 9. History is `d85c31e → 30bbc95 → Phase 9 commit`.
* PR #1 is not merged. `main` is not touched. `rag_chat.py` is byte-identical.

## 3. Phase 8 baseline verification

* Tests before Phase 9 work: 671 passed, 0 skipped, 0 failed. Protected hashes were unchanged.
* The generated stores (git-ignored) had vanished and were rebuilt with the existing builders. The page-collection rebuild is deterministic: its manifest differs from the committed one only in `created_utc` (fingerprint `c50e951f…`).
* After this phase: `evaluate_phase8.py` re-run, `phase8_results.json` still `735f7061…`.

## 4. Corpus audit (9A.1)

`data/phase9/corpus_status.{json,md}` is a read-only 29-card table (card id, title, category, source URL, identity status, effective guide id, page id, page URL, availability, provenance, hash, page status, fetched-this-phase, previously present, verification status, review flag).

| Identity status (7C) | Cards |
|---|---|
| `resolved_local_page` | M2C-17 |
| `corrected_identity` | M2C-05 |
| `identified_not_local` | 23 cards (of which M2C-02, 07, 11, 14, 24 have saved page text) |
| `card_identity_only` | M2C-01, 13, 16 |
| `conflicting_identity` | M2C-18 |

Review flags remain on M2C-14, 18, 23. Nothing was rewritten or "repaired".

## 5. Official-page retrieval (9A.2) — BLOCKED

`page_fetch.py --allow-network` was run against the 18-page plan. `robots.txt` could not be read (SSL error, TLS EOF). The first three plan pages (M2C-03, 04, 06) also failed with the same error and the circuit breaker stopped the run. **0 pages were saved.** The attempts are recorded in `data/phase9/fetch_attempt_log.json`. A second run in the completion pass (`fetch_attempt_log_run2.json`) failed the same way (robots unreadable, 3 attempts, circuit breaker, 0 saved). `curl` shows the TCP connection succeeding and the TLS handshake being closed by the peer. Only URLs from the existing plan were used; none were guessed. No third-party source was used.

## 6. Corpus availability

**7 available / 22 missing.** Available: M2C-02, 05, 07, 11, 14, 17, 24. Missing: 18 `identified_not_local` pages (M2C-03, 04, 06, 08, 09, 10, 12, 15, 19, 20, 21, 22, 23, 25, 26, 27, 28, 29), 3 identity-only cards (M2C-01, 13, 16) and the conflicting M2C-18. The three identity-only cards and M2C-18 would need identity resolution as well as a fetch. They are not counted as covered. **29/29 is not claimed.**

## 7. Corpus validation and chunking (9A.3–9A.5)

* No new page was admitted, so the corpus fingerprint is unchanged (`fd55d20f…`). Every saved page hash matches its text; page ids are unique.
* Chunking is unchanged: B_heading_200, 32 chunks over 7 pages, tokens mean 118.8 / p90 190 / max 226 (exact MiniLM tokenizer), none over the model limit, no overlap chunks.
* Tests check on the real corpus: no text loss (every block appears in a chunk of its page), no duplicated chunks or ids, deterministic rebuild, provenance per chunk, token limit.
* No chunking, embedding, hybrid or reranking change was made. The controlled chunking comparison (§11a) used a decision rule declared before the first run, and no candidate met it.

## 8. Fresh query set (9B.1)

127 queries (`P9-001`…`P9-127`), written by an AI assistant with the page text in view, **before any retrieval**. The file hash is recorded and the evaluator refuses to run if it changes. Labels were not changed after retrieval.

| Type | n |
|---|---|
| answerable (evidence quoted verbatim from a saved page) | 69 |
| absent_detail (page present, asked detail not on the page) | 14 |
| not_ingested (card known, page missing) | 20 |
| unresolved_identity (M2C-18 and identity-only cards) | 8 |
| out_of_domain | 16 |

Facets: keyword, natural language, paraphrase, entity, rare term, multi-concept, section-specific, sibling-ambiguous, terminology mismatch. Every query was checked against the Phase 4/5/7F/8 sets (no exact or near duplicate) and against card text (no more than 3 contiguous shared words, except for OOD queries). Per-card and per-facet n are small (facets 6–10; cards 1–16 queries). The queries were written by the same agent that built the system, so they are an independent set in time and wording but not an independent-author set.

## 9. Card router results (9B.2)

| Set | n | R@1 | R@3 | R@5 | MRR |
|---|---|---|---|---|---|
| Phase 9, all gold-card queries (primary) | 111 | **0.4595** | 0.7027 | 0.8018 | 0.6133 |
| Phase 9, answerable only | 69 | 0.3333 | 0.5942 | 0.6957 | 0.5051 |
| Phase 5 recorded (independent, 54) | 54 | 0.7222 | 0.7963 | 0.8704 | 0.7873 |
| Phase 4 recorded (50) | 50 | 0.92 | 0.96 | 1.00 | 0.95 |
| Phase 8 recorded (80) | 80 | 0.4625 | 0.775 | 0.875 | 0.623 |

Phase 4 (card-text derived questions) overstated routing quality. The Phase 9 figure agrees with Phase 8. The Wilson 95 % interval for R@1 on 111 queries is 0.37–0.552.

* Gold-card rank distribution: rank 1 = 51, rank 2 = 22, rank 3 = 5, rank 4 = 8, and a tail to rank 26.
* Mean rank-1 similarity: 0.448 when correct, 0.368 when wrong. The mean rank-1/rank-2 gap is 0.047 when correct and 0.029 when wrong (AUROC 0.63). This is descriptive; no threshold was derived (7F: `min_cosine` stays `None`).
* Per facet (answerable, R@1): entity 0/8, rare_term 1/6, section_specific 2/8, terminology_mismatch 2/8, multi_concept 2/7, keyword 4/9, natural 4/10, sibling_ambiguous 4/6, paraphrase 4/7.
* Per gold card (R@1): M2C-02 0/8, M2C-17 2/12, M2C-07 5/16, M2C-24 6/16, M2C-05 5/12, M2C-14 6/12, M2C-11 3/7.
* Diagnostic only: if the 22 cards without a page are removed from the router's list, answerable R@1 is 0.6522 (R@3 0.8116, MRR 0.7582), against 0.3333 with all 29 cards. Page retrieval with no card stage has a page-level hit@1 of 0.7971 over the same 7 pages. This is **not a like-for-like deployable comparison**; it shows that most of the router loss comes from competition with cards that have no page, and that the remainder is detail-level queries against topic-level card text.

## 10. Rank-1 failure analysis (9B.3)

60 of 111 gold-card queries fail at rank 1. Labels are rule-based hypotheses made from query and card text, not proven root causes.

| Heuristic cause | n |
|---|---|
| sibling_card_ambiguity | 30 |
| other_unexplained | 11 |
| vocabulary_mismatch | 10 |
| rare_terminology | 8 |
| query_ambiguity | 1 |

Observed confusions: M2C-17 → M2C-18 (6 of 12 queries; the conflicting card absorbs ten wrong routes in total), M2C-02 → M2C-03 (4), M2C-24 → M2C-20/23/25 (8; two more go to M2C-18), M2C-14 → M2C-13 (2), M2C-11 → M2C-12 (2). A query routed to M2C-18 can only produce `unresolved_identity`, even though M2C-17's page holds the answer. Failures are listed per query in `phase9_results.json` (`router_failures`).

## 11. Page retrieval (9B.4)

Default chunking B_heading_200 only.

| Scope | n | R@1 | R@3 | R@5 | MRR |
|---|---|---|---|---|---|
| Inside the gold page (oracle) | 69 | 0.7971 | 0.9275 | 1.0 | 0.8756 |
| Gold page only when the router's rank-1 is the gold card | 23 | 0.6957 | 0.8696 | 1.0 | 0.808 |
| Corpus-wide over 7 pages, no card stage (chunk with evidence) | 69 | 0.6087 | 0.8696 | 0.9855 | 0.7529 |

Evidence in the top-5 context: 69/69 inside the gold page. The router-mode subset has n = 23, so its figures are weak.

### 11a. Chunking: controlled comparison on the frozen set (`phase9_extras.json`)

Decision rule declared in `scripts/phase9_extras.py` before the first run: a candidate counts as supported on this set only if its in-gold-page MRR is at least 0.03 higher, its R@5 is not lower, and the exact sign test on R@1 gives p < 0.05. Even then it would not be adopted without a held-out set.

| Strategy | Chunks | Tokens mean (max) | R@1 | R@3 | R@5 | MRR | Heading path kept |
|---|---|---|---|---|---|---|---|
| A_legacy_1000c | 23 | 158.9 (231) | 0.7826 | 0.9855 | 1.0 | 0.8853 | no |
| **B_heading_200 (default)** | 32 | 118.8 (226) | 0.7971 | 0.9275 | 1.0 | 0.8756 | yes |
| C_heading_128 | 38 | 101.4 (226) | 0.7971 | 0.8841 | 0.9855 | 0.8630 | yes |

* Paired R@1: A vs B 6 vs 7 discordant (p = 1.0); C vs B 1 vs 1 (p = 1.0). Neither candidate meets the rule (A's MRR gain is 0.0097). **B stays the default.**
* Overlap: none in any strategy. Chunk metadata (chunk id, guide, page, URL, title, content hash) is preserved by all three; the legacy strategy A has no heading path, so it cannot cite a section.
* Sibling-section confusion: for B, 12 of the 14 R@1 misses return a chunk from a different section than the evidence (C: 12). The right section is nearly always still in the top 3 (R@3 0.9275).
* Multi-section questions: not evaluated, because the set has no query with more than one evidence passage.
* Corpus-wide page-hit@1 (no card stage): A 0.7826, B 0.7971, C 0.8406.

## 12. Extractive end-to-end results (9C baseline)

Status match against the expected status (extractive generator, no LLM):

| Query type | n | Real router (rank-1) | Oracle routing |
|---|---|---|---|
| answerable | 69 | 0.2899 (20) | **0.8406** (58) |
| absent_detail | 14 | 0.1429 | 0.5 |
| not_ingested | 20 | 0.65 | 0.7 |
| unresolved_identity | 8 | 1.0 | 1.0 |
| out_of_domain | 16 | 0.875 (14/16) | n/a |

* Grounding verifier passed for 58/58 (oracle) and 20/20 (router) answers.
* Citations: 0 phantom citations, 0 topic pointers counted as evidence, 0 answer sources whose URL differs from the card's `source_url`. Of the answer sources, 64 % (oracle) and 61 % (router) contain the gold evidence; the rest are extra context chunks from the right page.
* M2C-18 and identity-only cards were never answered; the M2C-05 correction was preserved in every case.
* The error taxonomy (§14) covers 24 oracle-routing failures and 71 real-router failures. The rows are in `phase9_failure_audit.json`.

## 13. Ollama evaluation (9C) — BLOCKED

**Ollama evaluation blocked: local model unavailable.** There is no `ollama` executable, nothing is listening on 127.0.0.1:11434, the `ollama` Python package is absent, and the model weights cannot be downloaded in this sandbox. Nothing was installed, downloaded or substituted, and no external API was used.

Not measured: answer correctness, LLM grounding, LLM citation correctness, abstention, unsupported-claim rate, latency, failure rate, extractive-vs-LLM comparison. The code path is ready and tested with stub clients (`run_llm_eval`). The CLI requires `--generator ollama` explicitly and exits with code 3 on a runtime failure; it never falls back to extractive. Stub clients show that failures are recorded as `model_runtime_failure` and produce no answer.

## 14. Failure audit

Taxonomy per failed row: query, selected card, identity status, retrieved and cited chunk ids, answer, expected evidence, category. Counts:

| Category | Oracle routing | Real router |
|---|---|---|
| wrong_route | 0 | 57 |
| ood_or_context_gate_false_refusal | 8 | 3 |
| ood_gate_false_positive (not_ingested query stopped by the OOD gate) | 6 | 5 |
| failure_to_abstain (absent detail answered) | 7 | 3 |
| correct_retrieval_incorrect_synthesis (extractive refused) | 3 | 1 |
| other_status_mismatch | 0 | 2 |

`unsupported_claim`, `hallucinated_detail` and `model_runtime_failure` cannot occur with the extractive generator and have count 0 here. They are untested for a real LLM.

* The 7 absent-detail failures under oracle routing are the extractive generator returning a related sentence for a detail the page does not contain. The sentences are real page text and are cited, but they do not answer the question (for example, the serial-number-length question returns a sentence about equipment and serial-number naming). This is the unsupported-detail case that grounding verification cannot catch, because the sentence is supported but not responsive.
* 29 of 111 in-domain gold-card queries (26.1 %) were flagged `out_of_domain` by the lexical gate (Phase 8: 11/80). The gate is an uncalibrated heuristic.
* Of the 16 OOD queries, 14 were refused by the gate. Two were not: P9-126 (a household meter-dial question) reached `page_not_ingested`, and P9-127 (reducing a household electricity bill) reached `unresolved_identity`. Neither produced an answer. The OOD similarity AUROC (in-domain vs OOD) is 0.878, descriptive only.

### 14a. OOD / context gate distribution (`phase9_extras.json`)

The gate constants are unchanged: topic coverage 0.25, context coverage 0.5. Coverage is the share of query content words found in the routed card text plus the page text.

| Real router, rank-1 | n | Coverage min / median / mean / max |
|---|---|---|
| In-domain queries | 111 | 0.0 / 0.429 / 0.456 / 1.0 |
| Out-of-domain queries | 16 | 0.0 / 0.0 / 0.041 / 0.4 |

* The two distributions **overlap** (the highest OOD value, 0.4, is above the lowest in-domain value, 0.0 and above the 0.25 cut).
* False refusals by the topic gate: 29/111 in-domain queries (26.1 %, Wilson 18.9–35.0 %); 20/69 answerable queries (29.0 %). The context gate refuses a further 4/69 answerable queries.
* False accepts: 2/16 OOD queries got past the topic gate (12.5 %); neither produced an answer.
* Under oracle routing (correct card supplied) the same gate refuses 8/111 in-domain queries (7.2 %) and 2/69 answerable ones; the context gate refuses 6/69. So most false refusals come from wrong routing (the gate compares the query with the wrong card), not from the gate wording alone.
* **A threshold is not justified.** The distributions overlap, there is no held-out set, and the gate is a lexical heuristic. No threshold was proposed or changed.

### 14b. Source chains and traceability (`phase9_source_chains.json`)

238 source chains were recorded (127 real-router + 111 oracle). Each holds: query → card (+ rank) → effective identity → page → context chunks → answer → cited chunks → citation URLs. Six checks ran on every chain, and all 238 passed each of them:

1. Answer citation URLs equal the card's `source_url` (no rewriting).
2. The topic-pointer URL equals the card's `source_url`.
3. Every cited chunk was in the generator's context.
4. Every cited chunk belongs to the effective identity page.
5. The card is never used as answer text or as verified evidence.
6. No source is listed unless the status is `answered`.

88 of the 238 chains are answered. No answer was produced for M2C-18.

### 14c. CLI evidence

* `rag_answer.py --generator extractive --question "EL31 monitoring selection criteria"` → exit 0, `answered`, card M2C-07, 1 answer source.
* `rag_answer.py --generator extractive --question "What is the capital of France?"` → exit 0, `out_of_domain`, no sources.
* `rag_answer.py --generator ollama` on the same answerable question → **exit 3, nothing on stdout**, stderr `generation failed: ModuleNotFoundError: No module named 'ollama'`. No extractive fallback.
* Note: a question routed to M2C-18 or to a card without a page stops at the identity step, before generation. The `ollama` flag then exits 0 without ever calling a model. That is correct behaviour, but it means a successful exit with `--generator ollama` does not prove an LLM ran.

## 15. Fabrication resistance (stub generators)

Six fabrication stubs (invented number, transaction code, URL, off-context claim, phantom citation, uncited claim) were run over the 69 answerable queries with oracle routing. The faithful control was shown 61 times; every fabricated answer was withheld by the verifier (61/61 per type, 0 shown). This is a **verifier test**, not a **real-LLM fabrication evaluation**: it does not show how any real model behaves.

## 16. Performance (`phase9_performance.json`)

Extractive, router mode, 127 queries (stage timings are reported separately and are never mixed with model latency): routing median 14.9 ms (p95 17.7); page retrieval median 14.2 ms (p95 16.9, n = 30 queries that reached retrieval); context assembly median 2.4 ms; extractive generation median 0.3 ms; end-to-end median 15.8 ms, p95 39.0 ms. Peak RSS about 954 MB; embedder load 4.2 s. **Ollama latency: not measured (blocked).**

## 17. Determinism

`evaluate_phase9.py` was run twice on the final code. `phase9_results.json` (`a8872e58…`) and `phase9_failure_audit.json` (`6a99f78e…`) were byte-identical across both runs. The performance file is excluded. The chunk fingerprint is stable. `phase9_extras.json` (`78fb9106…`) and `phase9_source_chains.json` (`4432dadc…`) were also byte-identical across two runs. The query file hash is verified before every run.

## 18. Tests

* **With stores present: 734 passed, 0 skipped, 0 failed** (671 before Phase 9, 63 in `tests/test_phase9.py`).
* **With the git-ignored stores absent** (a copy of the tree without `data/vector_store`): 691 passed, 43 skipped, 0 failed (734 collected). Store-dependent tests skip with a reason and the pipeline start failure is graceful (CLI exit 2, "cannot start the pipeline").
* Phase 9 tests cover: corpus completeness and provenance, the fetch logs, query-set integrity and freeze hash, real-corpus chunking invariants, frozen-query pipeline behaviour (oracle answers, not-ingested, unresolved/conflicting identity, no candidate, OOD, absent detail, generator failure, empty query, determinism), the chunking decision rule and verdicts, the gate analysis, 238 source chains, CLI evidence, Ollama detection and the no-fallback contract, the stub-client LLM path, results and report consistency, regression pins and the no-network import rule.
* `git diff --check` is clean.

## 19. Regression

* Phase 4 router metrics recomputed live: 0.92 / 0.96 / 1.00 / 0.95 (match).
* Phase 5 recomputed live: 0.7222 / 0.7963 / 0.8704 / 0.7873 (match).
* `phase8_results.json` unchanged (`735f7061…`) after re-running `evaluate_phase8.py`. `phase8_performance.json` was restored after the re-run, because it holds timings.
* `rag_chat.py` (`e862ce38…`), `rag_core.py` (`881316e4…`), `rag_modes.py`, the card collection and its manifest (`5b3a5c30…`), page identity data (`fccb0bb8…`) and the Phase 7 modules are unchanged; the pinned-hash tests pass. No `chroma_db` was created. `rag_two_stage.py` does not exist.

## 20. Limitations

1. 7 of 29 pages. Routing and OOD figures cover the whole card set, but answerability is limited to 7 pages, so the router is penalised for 22 cards whose pages do not exist.
2. The query set is AI-authored with the page text visible. Small per-facet and per-card n (see Wilson intervals in the results file).
3. Router-mode page and citation figures rest on 23 queries.
4. The OOD and context gates are lexical and uncalibrated.
5. Failure-cause labels are heuristic.
6. No real LLM was run; no claim is made about LLM behaviour.
7. The `/tmp/av/...` model path is recorded inside three protected JSON files. I left it.

## 21. Evidence-based observations (no recommendation beyond the data)

* The 0.4595 R@1 is the same order as Phase 8 (0.4625) on a different query set, so the weakness is not specific to one set.
* Under oracle routing, answerable status match is 0.84; with the real router it is 0.29. Card routing is the largest single loss.
* Page retrieval is not the bottleneck inside a correct page (R@5 = 1.0).
* Absent-detail resistance of the extractive generator is 50 % under oracle routing.
* The OOD gate wrongly blocks 26 % of in-domain queries.
* Whether any change helps cannot be shown without a pre-declared decision rule and a held-out set. None was run in this phase.

## 22. Completion checklist

| Item | Status |
|---|---|
| Verify HEAD / tree / baseline | DONE (HEAD ref reset noted) |
| 29-card status table | DONE |
| Fetch remaining official pages | **BLOCKED** (help.sap.com unreachable; 0 saved) |
| Verify card → guide → page for new pages | **BLOCKED** (no new pages) |
| Rebuild/validate for expanded corpus | N/A (corpus unchanged); chunking re-validated |
| Fresh frozen query set (100–150) | DONE (127) |
| Router metrics, failure classification | DONE |
| Page retrieval metrics | DONE |
| Extractive end-to-end evaluation | DONE |
| Ollama evaluation | **BLOCKED** — Ollama evaluation blocked: local model unavailable. |
| Extractive vs Ollama comparison | **BLOCKED** |
| Failure audit | DONE (extractive only) |
| `phase9_results.json`, `phase9_extras.json`, performance files | DONE; determinism verified |
| Phase 9 tests | DONE (63 new; 734 total pass with stores; 691 pass + 43 skipped without) |
| Regression (Phase 4/5/7/8) | DONE, unchanged |
| Chunking controlled comparison | DONE (default kept) |
| Gate distribution analysis | DONE (threshold not justified) |
| Source chains (238) | DONE |
| Commit and push to the PR branch | DONE (one Phase 9 commit; see the PR) |
| PR #1 merge | NOT DONE, by instruction |

## 23. Reproducibility commands

Run from the repository root (PowerShell: set the variables with `$env:NAME="1"`).

```bash
# environment (pins match the committed tests)
pip install pytest pypdf beautifulsoup4 lxml requests numpy chromadb==1.5.9 sentence-transformers==6.1.0 gt-all-minilm-l6-v2==0.1.0
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
# stores (git-ignored); always pass a manifest path outside data/ so the committed manifests are not overwritten
python scripts/build_card_collection.py --manifest /tmp/card_manifest.json
python scripts/build_page_collection.py --rebuild --manifest /tmp/page_manifest.json
# corpus status and (when help.sap.com is reachable) the opt-in fetch
python scripts/phase9_corpus_audit.py
python scripts/page_fetch.py --allow-network --delay 1 --max-requests 18 --log data/phase9/fetch_attempt_log_next.json
# evaluation on the frozen set (do NOT re-run build_phase9_queries.py: it would rewrite the frozen file)
python scripts/evaluate_phase9.py
python scripts/phase9_extras.py
# answers
python scripts/rag_answer.py --generator extractive --json --question "EL31 monitoring selection criteria"
python scripts/rag_answer.py --generator ollama --json --question "..."        # needs a running Ollama with the configured model
# tests
python -m pytest tests -q
```

When Ollama and a model are available, `evaluate_phase9.py` runs the real LLM evaluation automatically (`run_llm_eval`) and fills the `ollama_evaluation` block; until then it records BLOCKED. When new pages are fetched, rebuild the page collection and re-run both evaluators. The frozen queries then no longer match the corpus hash, so a new frozen set has to be written before measuring the larger corpus.

**Phase 9 is partially complete.**
