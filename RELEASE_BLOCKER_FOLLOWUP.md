# Release follow-up — NOT READY

2026-10-15. Continued from **8c636d56676a190a80d2e14b045189685a71d2a8** on `arena/b450cda2-chatbot`. Final tested functional source: **29ca4ba2182b47f8452630ae5dd856ac946afe70**. Subsequent changes package reports/evidence only. No activation, public deployment, production migration/store repair, model download, dependency change or frozen evaluation change.

## Results at a glance

| Gate | Observed result / scope |
|---|---|
| Historical 37/65 versus 38/65 | Reconciled as **different predicates and pipeline configurations on the same 65 answerable / 113 frozen queries**. Not a one-case regression; historical files preserved. Exact past shell argv/dirty producing bytes cannot be attested. |
| Full backend, published baseline | **7 failed, 1330 passed, 137 skipped, 49 errors, 204 subtests**, 67.70 s. |
| Full backend, final candidate | **7 failed, 1365 passed, 137 skipped, 49 errors, 204 subtests**, 64.91 s, exit 1. Identical failure/error and skip/reason sets. **Not a full-suite pass.** |
| New focused regressions | **35 passed**, 1.50 s: provenance 3, list relevance 10, payment/service/HTTP 9, sampled-vector safety 9, no-create readers 4. |
| Full current strict 113-case production evaluation | **BLOCKED**, factory exits 1 on missing `sentence_transformers`; no result/score written. Models/tokenizer/stores are also absent. Not replaced with cached results. |
| Separately named cached generation | Normal **47/70 → 46/70** behavior matches; fact recall **49.5% → 49.0%**. Oracle **46/70 → 45/70**, **48.1% → 47.6%**. Prohibited-claim heuristic flags **9 → 5** in each. No claim of accuracy/completeness promotion. |
| Frontend | **119 passed, 1 skipped**, 20.64 s; typecheck/build exit 0; fresh npm audit 0 vulnerabilities. jsdom, **not** an authenticated real-browser test. Live-backend skip remains BLOCKED. |
| Static/environment checks | Fatal Python lint (`E9,F63,F7,F82`), new-code E/F/I checks, scoped formatting, compilation and installed-graph pip check pass. Broader unconfigured style audit is **not clean**: 139 unchanged legacy diagnostics plus one reviewed new test-only SIM117 suggestion. Preflight exits 2: missing runtime/resources. |
| Chroma | All four advisories remain **OPEN**; 1.5.9 affected, latest PyPI 1.5.9, no first patched version; PR 7602 open/unmerged. Source investigation expanded to all three Python cross-tenant layers; containment plan requires actual infrastructure/security evidence and approval. |
| External mandatory gates | Native Windows, historical strict Q35 provenance, full model/RAG, real Ollama, authenticated browser/IAM/accessibility, independent authoritative SAP review, production isolation/capacity/restore/rollback and approvals remain BLOCKED / NOT RUN. |

## 1. Provenance first: what was established

[`release/closure_v2/PROVENANCE.md`](release/closure_v2/PROVENANCE.md) and [`historical-provenance.json`](release/closure_v2/historical-provenance.json) pin exact artifact SHA256, commit/Git blob versions, configurations, counts and all case differences.

- **37/65** occurs in `benchmarks/results/v1_baseline_quality.json` (runtime reference **6eb9d9d25dda75bf9092838b813faa7a51cd8473**) and `release_05ef5e7_quality.json` (**05ef5e7c99aca8a03ee05b61ba16128093c2e1b9**). `benchmarks/run_quality.py` requires expected guide/page in **both** cited source and context item, and the quote in **both answer and cited context**; it uses the production service configuration.
- **38/65** is `data/evaluation/phase12_results.json`, `configs.evidence.answers_real_routing`. `evaluate_phase12.py` → `phase10_lib.correct` checks cited identity and quote in cited context, **not necessarily the answer**; its wrapper uses default pipeline settings rather than production flags.
- Same query SHA256 **`3c5a9ddd2d62e9cb1919a4fbb7c81cd5239994ff230abbbe6440fb6fa5c132ac`**, 65 answerable + 40 negative + 8 ambiguous. **15** answerable correctness disagreements and **10** selected-source disagreements, not merely one changed answer.
- The 38 artifact stores HEAD **c7527edeb5d4a2963d8bac0072a8e7e5d0ba091f**, but was published with the later corpus/evaluator changes in **9be6553473fa27abbf915c395d4204ca4beae123**. A HEAD string does not pin dirty producing bytes. The old report documents a command; independently retained exact shell argv/clean-tree attestation is absent. Equivalent reproduction commands are explicitly labelled reconstructions. Historical summaries lack complete debug contexts, so both predicates cannot be retroactively applied to identical full raw outputs from these summaries.
- Read-only reconciliation was rerun to a new file and is **byte-identical** to the published reconciliation JSON. Three model-free tests preserve the distinction, including refusal not counting as answer correctness. The earlier closure-v1 provenance uncertainty is superseded, not silently erased.

The current full attempt is [`candidate-delivery-full-phase12-attempt.json`](release/closure_v2/candidate-delivery-full-phase12-attempt.json), exact source/argv/offline environment/traceback included. Earlier separately named attempts remain honest BLOCKED evidence.

## 2. Review of every remaining backend failure/error

[`backend-review.json`](release/closure_v2/backend-review.json) retains each of the **56** exact identifiers, baseline/final outcomes, current traceback, dependency review, all **137** skips/reasons and **54** passing safety-labelled observations. Original assertion sources and separate reproductions remain in closure-v1.

- **36** cases (31 setup errors + 5 failures) encounter missing `sentence_transformers` at the real production factory.
- **19** (18 setup errors + 1 failure) retain the strict `info["exact"]` tokenizer guard. The fallback is not the exact tokenizer and cannot certify the 113 frozen chunks. [`runtime-capabilities.json`](release/closure_v2/runtime-capabilities.json) independently records `exact=False` and local-model `FileNotFoundError`.
- **1** failure expects a successful diagnostic child, which exits 1 at missing local model resolution. The prior independently captured child traceback remains in `release/closure_v1/diagnostic-child.traceback.txt`; a failed worker is not a completed check failure or PASS.

No integration assertion was weakened, real rankings/vectors replaced, expected result changed, new skip added, or missing setup relabelled PASS. Missing prerequisites can mask later genuine defects: these tests are **not declared defect-free**. All feasible newly reproduced defects below were fixed separately. The older tests' bytes remain unchanged.

## 3. Narrow semantic fixes, with retrieval → selection → construction evidence

[`semantic-case-review.json`](release/closure_v2/semantic-case-review.json) includes before/after answers, selected units, unchanged metric output, historical route/chunk IDs and all eight targeted/flagged cases in both normal/oracle modes. Full candidate-unit/context traces and all 70 raw outputs per mode are losslessly archived under `release/closure_v2/raw/` and indexed by the manifest. **Retrieval/status/latency are historical snapshots, not newly executed retrieval.** Null source URLs/IDs are not filled in or promoted to authoritative guide/version proof.

- **CASE-012 / CASE-040:** one retrieved Master Data chunk contains separately labelled business and technical lists. Shared generic terms previously selected both; rendering then appended all technical entries to a business-only answer. The selector now compares explicit same-chunk sibling-list subjects and a uniquely requested qualifier, omitting only the unrequested list/attached lines. Broad/both-subject requests retain both. Requested business members stay verbatim and complete; no SAP object taxonomy/identity or benchmark IDs are hardcoded in runtime code.
- Two supporting bugs were exposed: valid attached noun-phrase members were stripped from the guarded generator's prompt as fragments, and generic enumeration-frame “objects” could incorrectly fail the asked-term check after removing the wrong sibling. Explicit complete membership lists now preserve their members; the generic frame is recognized **only** for a named matching list subject, without bypassing identifier, detail-kind or coverage gates. Tests cover shared values, reverse scope, broad/comparison requests, missing-topic/authorization/default refusal, prompt isolation, post-check rejection, grounding and original-context immutability.
- **CASE-052:** a generic payment-process request previously inherited the router's external-cash-desk scope without user authorization. Bare payment-processing language now refuses evidence selection with `AMBIGUOUS_PAYMENT_PROCESS`; the service asks **“Please clarify which payment process you mean, including the payment type or channel.”** It returns no factual answer/source or assumed-topic reference. Actual pipeline/service and in-process ASGI tests verify propagation. Qualified requests are not blocked by this narrow policy; real Ollama remains unverified.
- **Residual five flags:** CASE-020/023/024 concern procedure-completeness wording; the notice is scoped to **selected evidence**, not a claim that an entire SAP page lacks steps. CASE-037/039 do not literally assert the prohibited negative, but the unchanged stem-overlap matcher flags them without polarity/relationship understanding. These are **review candidates, not five proven hallucinations and not five cleared facts**. Completeness and independent claim/source/version adjudication remain mandatory. No matcher/label was edited or flag suppressed.

The fixed benchmark classifier credits some partial answers against “clarify”; the old cash-desk partial answer received that relaxed match. The generator-only replay now records refusal (not public service clarification), so its raw behavior score loses one and its keyword recall decreases. The service/HTTP regression proves a clarification contract in the hermetic fixture, **not** current full-RAG substantive accuracy. We retain the worse unchanged metrics rather than modifying the evaluator to manufacture improvement. M2C-18 remains excluded.

## 4. Helper and resource safety

- `frontend_live_verification.py --help` / `--unknown` exit **0 / 2**, no backend launch; listener sets unchanged and port 8000 absent. [`helper-no-launch.json`](release/closure_v2/helper-no-launch.json) plus the unchanged mocked-Popen assertions establish this limited CLI behavior.
- Original owned-client, partial/failed-shutdown quarantine, retained-client/outside-owner, retry/finalizer and no-implicit-creation assertions remain in the full run. Real Linux SDK observations are not native Windows sharing/drain proof.
- **New genuine stored-vector gap:** matching metadata/dimension alone accepted sampled NaN/Inf or zero cosine vectors. The existing sampled actual vector must now be finite/nonzero. Rejection closes only the newly owned client, propagates visible errors and never rewrites/normalizes a store. Nine added tests include both card/page owners; invalid numeric fixtures are mocked **before native HNSW**, not inserted into production. This is sampled startup validation, **not** an exhaustive authenticity/audit of every stored vector/configuration.
- **New genuine legacy-reader gap:** the legacy `PageRetriever.from_store` checked only for a directory, so an existing empty directory reached the SDK's database-creating constructor. It now also requires an existing `chroma.sqlite3` before opening. Four regressions cover absent/empty paths for legacy and owned readers, assert no constructor call and no new database/path. Existing validation tests for real disposable stores remain unchanged.
- No global Chroma stop/cache/refcount reset, ignored close error, production-store repair or candidate activation was introduced. Strict native Windows/Q35 and full repair/diagnostic integrations remain blocked by their real prerequisites.

## 5. Security and external handoff

[`CHROMA_SECURITY_PLAN.md`](release/closure_v2/CHROMA_SECURITY_PLAN.md) contains all four identifiers/ranges/prerequisites, installed vulnerable-function hashes/excerpts, local SDK versus Python/Rust server reachability, fresh upstream/PyPI responses, the three-layer cross-tenant analysis, and concrete no-patch network/identity/artifact/OS/isolation/patch-watch controls with responsible owners and required proof. **PR 7602 is open/unmerged, not a patched release.** Following those references also found high, unreviewed **GHSA-x97m-f58v-9cwg / CVE-2026-45832**, with no package ranges/patch metadata; its Python v1 condition is corroborated and retained as a related OPEN risk, not assumed unaffected. No server/API/SDK architecture alone grants an exemption. Actual topology, IAM/document ACLs, containment enforcement, native/OS/model closure and security acceptance are absent; all four advisories stay OPEN.

[`HANDOFF.md`](release/closure_v2/HANDOFF.md) gives the minimal Windows/strict-Q35/real-Ollama/authenticated-browser/authoritative-SAP/deployment-rollback procedures, exact existing CLI interfaces and missing prerequisites/approvals. Preserve >=95% substantive correctness, 100% identity, zero unsupported/wrong-guide/version factual answers and 100% safe negatives. Abstention is not substantive correctness. No mandatory gate is promoted to READY.

## 6. Executed validation, warning/skip review and preservation

Primary commands (from the isolated candidate; frontend commands from `web/`):

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 ../.venv/bin/python -m pytest tests -q -ra --tb=long --junitxml=../closure-v2/delivery-backend.xml
../.venv/bin/python -m pytest tests/test_quality_provenance.py tests/test_list_subject_scope.py tests/test_payment_scope_clarification.py tests/test_stored_vector_safety.py tests/test_page_reader_no_implicit_create.py -q -ra
../.venv/bin/python release/closure_v2/reconcile_provenance.py --out ../closure-v2/provenance-reproduced.json
../.venv/bin/python release/closure_v2/replay_quality.py --out ../closure-v2/candidate-final-cached.json
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 ../.venv/bin/python benchmarks/run_quality.py --source-commit 29ca4ba2182b47f8452630ae5dd856ac946afe70 --out ../closure-v2/candidate-delivery-full-phase12.json
../.venv/bin/python -m ruff check --isolated --select E9,F63,F7,F82 scripts tests release/closure_v2
../.venv/bin/python -m compileall -q scripts tests release/closure_v2
python -m pip --python ../.venv/bin/python check
# cwd web/: npm test; npm run typecheck; npm run build
```

No emitted pytest warning summary or frontend/build warning was observed; this is not a claim about all warnings under every filter. All 137 backend skips are enumerated with their unchanged reasons; one requires actual Windows and the rest require unavailable models/tokenizers/stores/imports. The frontend's single skip is its explicit real-HTTP workflow (`LIVE_BACKEND != 1`), not a passing browser test. The broader default Ruff audit is reviewed in [`lint-scope-review.json`](release/closure_v2/lint-scope-review.json), not hidden behind the narrower fatal gate.

Development red regressions (list 4 failures, payment 5, vector 8, reader 2) reproduced the defects before their fixes; all final added tests pass. Intermediate list failures exposed the attached-member/enumeration-frame bugs and were fixed, not suppressed. Two mistyped test filenames collected no tests before the corrected expanded run (70 passed/21 resource skips). The first new replay-report script used an incorrect result key and failed after writing only a separately named scratch normal-mode output; it was corrected and rerun to new names. `../.venv/bin/python -m pip check` failed because that venv lacks pip; the host pip's supported `--python` check subsequently passed without installing anything. None of these incomplete attempts is counted as a successful verification.

The manifest/preservation report pins tested runtime/new-test hashes, published artifact hashes and lossless raw-content/gzip identities. Original checkout byte/status/index/stash/HEAD checks, protected data/evaluation/cache/checkpoint/requirements/web files, older assertion bytes and closure-v1 evidence are checked without normalization or cleanup. Only **five** existing runtime files changed from 8c636d5. Original user work stays untouched. Publication uses small reviewed commits and a normal push to this branch; the final delivery ID and real remote/API verification are returned separately.

**Next human action:** supply the approved exact local model/tokenizer and cold disposable stores, assign native-Windows/historical-Q35 and independent SAP reviewers, and have security/operations provide actual private target configuration and authorize a containment/isolation/rollback rehearsal. Production exposure, migration, replacement and activation remain unauthorized. **NOT READY.**
