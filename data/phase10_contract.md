# Phase 10 contract (derived from repository evidence, written before any Phase 10 experiment)

## 1. There is no Phase 10 specification in the repository

Searches for "phase 10", "phase10" and "next phase" in every `.md`, `.py` and `.json` file found no Phase 10 specification. The only forward-looking
statements in the repository are:

| Source | Statement used |
|---|---|
| `data/phase8_report.md` §20 item 3 | "Router quality: the router, not the page stack, limits end-to-end accuracy … Candidate fixes (hybrid retrieval, **page-level re-ranking across the router's top-k**, abstention) must be evaluated on a fresh set — do not tune on `phase8_queries.json`." |
| `data/phase8_report.md` §20 item 4 | "Replace the lexical OOD/abstention gates with a calibrated approach on a larger set; **improve absent-detail abstention**." |
| `data/phase9_report.md` §9–§14, §21 | Router R@1 0.4595 (answerable 0.3333); oracle routing answers 58/69, real routing 20/69; absent-detail abstention 7/14; 26 % of in-domain queries refused by the lexical gate; a threshold is not justified without a held-out set. |
| user hand-off chain (recorded in earlier phases) | "correct 29-topic corpus → embeddings → retrieval eval → answer-quality eval → **RAG optimisation**". Phases 8 and 9 covered the first four stages as far as the environment allows. |

I therefore define Phase 10 as the last stage of that chain, **RAG optimisation, restricted to the changes that Phase 8 §20 and the Phase 9 evidence name**.
This scope is my reading of the repository evidence, not a user-written specification, and the report says so.

## 2. In scope

* **R — router stage:** page-evidence re-ranking of the card router's list (Phase 8 §20 item 3). The card collection and the card-first design stay; no
  page chunk enters the card collection; direct page retrieval does not replace card routing.
* **G — generation stage:** better abstention when the asked-for detail is absent (Phase 8 §20 item 4, Phase 9 absent-detail 7/14), without a
  material loss of correct answers.
* **Evaluation:** a fresh DEV set (design and selection) and a fresh sealed TEST set (one evaluation), both written before any experiment; the Phase 8 and
  Phase 9 sets are regression references only.
* **Integration:** opt-in modules and CLI; the default pipeline, `rag_chat.py` and every protected artefact stay byte-identical.

## 3. Out of scope (not started)

Fetching the 22 missing SAP pages (blocked: TLS to `help.sap.com`), a real Ollama evaluation (blocked: no Ollama or model), a calibrated OOD threshold (needs a
larger set; Phase 9 verdict stands), hybrid lexical retrieval, embedding or chunking changes (Phase 9 §11a: default B kept), UI, deployment, Phase 11.

## 4. Candidates (fixed here; implemented in `scripts/rag_optimised.py`)

**R (evidence-equalised fusion).** For every card `c` in the router's full list: `fused(c) = card_sim(c) + λ · e(c)`. `e(c)` is the best page-chunk cosine
similarity among the chunks of `c`'s page if `c` has a local page, otherwise `card_sim(c)` (the card text is then the only evidence, so unknown pages are not
penalised). `λ ∈ {0, 0.5, 1.0, 2.0}`; `λ = 0` is the current behaviour. Cards are re-ordered by `fused`; distances in the routing record stay the original card
distances; identity, gates, grounding and citations are untouched.

**G (answer-responsiveness).** `ExtractiveGenerator(min_score=θ)` with `θ ∈ {0.34 (current), 0.5, 0.67}` (G1), and a **detail-cue check** (G2): if the question asks
for a specific detail, the selected answer sentences must contain that kind of detail, otherwise the generator abstains. Cue rules, fixed before any run:

| Cue in the question (lower-case) | Required in the selected answer sentences |
|---|---|
| `transaction code`, `which transaction`, `what transaction`, `t-code`, `tcode` | a transaction-code token (regex `\b[A-Z]{2,5}\d{1,3}[A-Z]?\b`) |
| `maximum`, `minimum`, `at most`, `at least`, `limit` | the cue word itself, or a digit |
| `how many`, `how much`, `how long`, `what percentage` | a digit or a number word |
| `default` | the word `default` |
| `cost`, `price`, `fee` | the cue word or a digit |

The cue rules were written after I had seen the Phase 9 failure analysis, so Phase 9 is design-aware and cannot be an unbiased test. The DEV and TEST absent-detail
queries deliberately include questions whose cue is **not** in the table, to show how far G2 generalises.

## 5. Pre-declared selection (DEV only) and adoption (TEST only) rules

**Selection on DEV (`scripts/phase10_select.py`):**
* R: choose the `λ` with the highest DEV answerable Recall@1 of the gold card, subject to the guard "number of non-answerable DEV queries (not_ingested, unresolved,
  out_of_domain, absent_detail) that end with status `answered` is not higher than for `λ = 0`". Ties go to the smaller `λ`.
* G: among `{G0, G1(0.5), G1(0.67), G2, G2+G1(0.5)}` choose the one with the most correctly abstained DEV absent-detail queries (oracle routing), subject to "correctly answered
  DEV answerable queries drop by at most 5 % of the answerable count". Ties go to the simpler candidate.

**Adoption on the sealed TEST set (evaluated once with the selected configuration):**
* R is **supported** only if: TEST answerable gold-card R@1 improves by at least 0.05 absolute, the exact two-sided sign test on the paired R@1 outcomes gives
  p < 0.05, the number of non-answerable queries ending `answered` does not increase, and the routing of `unresolved_identity` and `not_ingested` queries does not get worse.
* G is **supported** only if: net correctly abstained absent-detail queries increase by at least 4 on TEST, correctly answered answerable queries (oracle routing) drop by at most 2,
  the grounding verifier passes on every answer, and there are 0 phantom citations.
* Both are also checked, as regression references, on the Phase 8 and Phase 9 sets (no selection there). A supported candidate that increases wrong-topic answers on those sets
  is reported as a regression and is not recommended.
* "Supported" means **recommended as an opt-in configuration**. The default pipeline is not changed in Phase 10.

## 6. Honest limits fixed in advance

DEV and TEST are AI-authored from the 7 local pages by the same agent that wrote the candidates, so they are independent in wording and time but not in author. n is about 41 answerable
queries per set, so intervals are wide and small effects cannot be shown. Only 7 of 29 pages exist; any gain on the 7-page corpus does not carry over to 29 pages by itself. No LLM is
available, so G is evaluated with the extractive generator only.
