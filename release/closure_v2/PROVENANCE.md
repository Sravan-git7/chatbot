# Historical quality reconciliation — 37/65 is not 38/65's metric

Follow-up to delivery `8c636d56676a190a80d2e14b045189685a71d2a8`. **NOT READY.** Historical files are unchanged. Machine-verifiable input/artifact hashes, full Git commit/blob IDs, configurations, counts and all case-level differences are in [`historical-provenance.json`](historical-provenance.json).

| Result | Evaluator and producing runtime reference | Scope / recorded output |
|---|---|---|
| **37/65** | `benchmarks/run_quality.py` introduced at **05ef5e7c99aca8a03ee05b61ba16128093c2e1b9**, SHA256 `ba5304c341212cd274dbb34ad0d96315c79a68985800a5fbf69d677c164403c4`; metadata/manifest identify runtime **6eb9d9d25dda75bf9092838b813faa7a51cd8473** | `benchmarks/results/v1_baseline_quality.json`, SHA256 `23b1ce2b96ace774decd1fc31a212cbcb8501dfcfdadba173c0b658b19f3eb0c`; 2026-10-13T15:53:50.597905Z; production extractive service, real routing, strict answer **and** cited-context quote/identity check. 53/65 answered; gold context 62/65; 11/40 frozen negatives answered. |
| **37/65** | Same evaluator; runtime **05ef5e7c99aca8a03ee05b61ba16128093c2e1b9** | `benchmarks/results/release_05ef5e7_quality.json`; 2026-10-13T16:29:44.408581Z; 52/65 answered; gold context 62/65; 10/40 frozen negatives answered. |
| **38/65** | `scripts/evaluate_phase12.py` → `phase10_lib.correct/_correct_by_context`; file last published in **9be6553473fa27abbf915c395d4204ca4beae123**. Stored run HEAD is **c7527edeb5d4a2963d8bac0072a8e7e5d0ba091f**, not an attestation of a clean producing tree. | `data/evaluation/phase12_results.json`, `configs.evidence.answers_real_routing.answerable.answered_correct`; default pipeline wrapped by evidence generator, not production flags; expected cited identity and quote in cited context, **not** necessarily in answer. 46/65 answered: 38 context-correct + 2 wrong-page + 6 citation/evidence failures; 19 abstained. Gold context 52/65; 11/40 frozen negatives answered. |

**Same denominator and dataset:** SHA256 `3c5a9ddd2d62e9cb1919a4fbb7c81cd5239994ff230abbbe6440fb6fa5c132ac`; 113 queries = 65 answerable + 40 negative + 8 ambiguous. This is not an off-by-one or different sample. Baseline37 versus evidence38 differs on **15** answerable correctness booleans and **10** selected sources; both retrieval/configuration and metric semantics differ. The 37 run's corpus SHA is `46e7c63af630de1a99f924320092b3bce4e29751add1eb3177b357cabd136008`; its frozen-label corpus SHA is `fd55d20fd1a4ede8418a624684305854dd16a386b2475b4f1f82580c75702e8d`. Do not infer a one-case regression or rewrite either historical score.

## Exactness and reproducibility limits

- The old release report table row 9 documents `.venv/bin/python scripts/evaluate_phase12.py`. No independently retained shell argv/environment or clean-tree attestation establishes the exact 38 producing bytes. That report describes a corpus/evaluator regeneration before 9be6553; its stored c752 HEAD does not identify uncommitted files. Git blobs at **both** references are recorded, not silently conflated.
- The benchmark manifest pins evaluator/runtime/artifact hashes, but **has no `commands` key**. It cannot prove the exact original absolute `--source-root`, output argument or shell command. Equivalent reproducible commands are below, explicitly reconstructions rather than asserted past invocations. The newer evaluator supports an older runtime archive via `--source-root`, explaining why it is absent at 6eb9d9d.
- Neither summary preserves all raw debug contexts. We cannot retrospectively apply both predicates to identical full raw outputs from these summaries alone. The difference in predicates is directly testable without models; `tests/test_quality_provenance.py` preserves that distinction.
- Frozen references are AI-authored, not independently adjudicated SAP ground truth. Neither score satisfies the standing substantive quality gates. The earlier closure-v1 statement that 37 was not traceable is superseded by this discovery, not erased from history.

### Read-only reconciliation, executed

```sh
../.venv/bin/python release/closure_v2/reconcile_provenance.py --out release/closure_v2/historical-provenance.json
```

The script refuses to overwrite an existing output, verifies the old manifest's artifact hashes, and records Git SHA256/blob identities. Rerun to a **new** filename.

### Equivalent historical full-run commands — NOT executed here

On an approved existing model/tokenizer/runtime and disposable cold copies of the historical stores/corpus, use the pinned evaluator from 05ef5e7 and byte-exact archived runtime roots:

```sh
P benchmarks/run_quality.py --source-commit 6eb9d9d25dda75bf9092838b813faa7a51cd8473 --source-root <6eb9d9d-runtime-copy> --out <new-baseline37.json>
P benchmarks/run_quality.py --source-commit 05ef5e7c99aca8a03ee05b61ba16128093c2e1b9 --source-root <05ef5e7-runtime-copy> --out <new-release37.json>
# In an isolated 9be6553 reproduction root (candidate reference, NOT proof of original dirty bytes):
P scripts/evaluate_phase12.py --configs baseline,evidence --out <new-phase12.json> --perf-out <new-phase12-perf.json>
```

Do not delete sealed outputs to bypass the evaluator's immutable-output guard. `P` and angle-bracket paths are explicit operator substitutions. Matching source is insufficient without original model, tokenizer, corpus, embeddings/stores and dependencies.

## Separately named current-candidate attempt, executed

[`candidate-full-phase12-attempt.json`](candidate-full-phase12-attempt.json) records exact argv, source, offline environment, exit and full traceback for:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 ../.venv/bin/python benchmarks/run_quality.py --source-commit 8c636d56676a190a80d2e14b045189685a71d2a8 --out ../closure-v2/candidate-full-phase12.json
```

**BLOCKED**, exit 1, `ModuleNotFoundError: sentence_transformers` in `build_page_collection.load_embedder`; no quality result/score written. No models/downloads, stores or frozen labels were substituted. Subsequent cached-context generation results have a different name and scope; they cannot close this full-pipeline gate.
