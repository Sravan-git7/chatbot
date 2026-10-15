# SURA — final release-engineering report

**Verdict: NOT READY.** Date: 2026-10-15. This is a reviewed hardening/verification candidate, **not an activated release**. Mandatory product, native-platform, real-model/browser, security and operations gates remain open. No public exposure, production-store migration/repair/replacement, model download, paid model call or candidate activation was performed.

## Candidate, history and preservation

- Branch: `arena/b450cda2-chatbot` throughout. Live GitHub branch tip at audit/recheck: `20cb6daa4c6cd4efd2c1d0ee117380101d843a5d` before publication. The original checkout was shallow/dirty and 11 commits behind; reconciliation there would have risked user work.
- Work used a separate full same-branch clone at `scratch/release-mission-v3/candidate`. Original checkout remains `c7527edeb5d4a2963d8bac0072a8e7e5d0ba091f`; its working/index/untracked/stash state was preserved, not normalized/reset/cleaned.
- Recoverable private baseline: 822 file hashes, binary working patch and user-work copies outside edited files. Baseline JSON SHA256 `a831a4fddf50766772beac663bba6ca54e3ef137782f5d8a75a7c272952b1ca5`. Final comparison: **822/822 original files unchanged; original index/stashes/status unchanged; 222/222 checkpoint pins match; 812 other original candidate baseline files unchanged**.
- Original failing Windows test prefix: first 11,037 bytes SHA256 `fdf52dbbaa0f18ec65db58befe65fe18d202088d5784a308eb3c81b45b017d7b`, unchanged. Original assertions were not weakened. Additional tests follow that prefix.
- Historical report previously at this filename is preserved byte-exact at `release/history/FINAL_RELEASE_REPORT.before-v3.md`, SHA256 `3f45330a10fe2ddbd1481dcf106e70c144ef6df66f7d5eb1be3b15379740d6b3`. Initial gate preregistration is separately archived unchanged. Corpus/model/checkpoint/evaluation artifacts and strict policies were not silently repaired or rebaselined.
- Production/user data, local models, ignored backups/stores and immutable references were distinguished from newly owned disposable test stores. No live card/page store, `chroma_db`, `av`, or `local_backup2` was present here; none was deleted/created in the preserved checkout. Linux native tests used explicitly disposable stores/constant fixture vectors, never production data.

### Reviewed commits

| Commit | Scope |
|---|---|
| `6e1528e9a82acb565e306bcad21b41f849628f2d` | Auth/privacy/owned-client lifecycle/partial-stop quarantine and regressions |
| `c6530aa0b2e32bbac199d3656775c84854cf636d` | Cross-adapter failure quarantine and versioned adversarial evaluation package |
| `855eb04b0712cc66931bc33d86cde8e136604388` | Reject implicit development CORS trust and wildcard production framing |
| `72c43554e919b98d060588a0df617ac48c045f61` | Actual installed-SDK partial bindings failure, directory retention, outside-owner isolation and process-boundary recovery regression |
| `3b95c7df081ff98d1dc9103fe3a92c22d85333cb` | Verify physical stored vector dimension and model identity against the loaded production embedding contract before readiness; actual SDK failure/recovery regressions |
| `c324ffb366511b15385524aa8ed24e956f662780` | Refuse implicit page-database creation before SDK initialization; no-store-mutation regressions |

Final functional source and source/test verification commit: `c324ffb366511b15385524aa8ed24e956f662780`. All are descendants of the audited repository rollback point `20cb6daa...`. Source and reports were published normally at `d4f613b85ba189fe8e716d8a0c833c4c9102348f`; remote Git and GitHub API agreed, the candidate was clean, and rollback ancestry was verified. `release/evidence/publication-receipt.json` records that completed operation. This receipt-only descendant changes no runtime; its final delivery SHA is checked after publication and provided in the completion message. No force push, history rewrite, branch switch or production deployment is part of publication.

## Root-cause fixes and proof

1. **Partial native stop is not idempotent.** Real Chroma 1.5.9 deletes Rust bindings before later components can fail. The helper previously allowed a second stop attempt on an already-partially-stopped cached system. It now retains state/tree and rejects intersecting cleanup/reuse until process restart. Temporary and production-owned adapters coordinate quarantine. File-release timeout after a **successful** stop remains safely retryable without a second native stop.
2. **Owned-client lifetime was lost.** Original retrieval factories retained collections but not their created SDK clients; both evidence/service wrappers constructed new pipelines, losing ownership metadata. New production wrappers own only their clients, transfer the resource list across both wrappers, close partial construction on failure, and release only after admission/draining. Unrelated/external owners remain usable. No global cache/refcount reset is used. Close failures stay visible and terminal.
3. **Public errors leaked private exception messages.** Startup/readiness now return sanitized failures, while logs record exception types. Legacy tests expecting leaked text were strengthened to require sanitized text and reject private payloads, keeping status/failure behavior intact.
4. **Shared deployment lacked a first-party boundary and trusted caller conversation IDs.** Production profile requires bearer secret/explicit hosts, rejects debug/raw logs/experiments/wildcards, has no implicit localhost CORS trust, and supported non-loopback CLI startup fails closed. Production ignores caller IDs, validates explicit client context in request-local state, and removes that state even on errors. Query fingerprints use per-app secret HMAC; request IDs are server-generated. The bearer is a backend/gateway credential, **not user identity or document-level authorization**.
5. **Received-byte limit copied oversized chunks first; IP keys grew unbounded.** Check precedes buffer extension. Rate-limit buckets are bounded/recover after expiry; 429/errors receive privacy-safe headers. Existing queue/admission/timeout/permit recovery tests remain intact.
6. **Readiness could accept unusable vector shapes.** Counts and declared metadata can agree while physical vectors have the wrong dimension. Both production owners now compare an actual stored embedding (public SDK read) and declared model identity against the loaded model dimension/name. A disposable store falsely declaring384 dimensions with actual2-dimensional vectors is rejected; external owners survive; a separate correct fixture recovers. Generic resource-only callers may omit a vector contract, but the production factory is regression-tested to supply it to both owners. This is an operational shape check, not full provenance/semantic certification.
7. **Missing page database could be implicitly initialized.** Ownership wrapper now requires the existing SQLite file before calling the SDK. Empty page/card directories do not invoke the SDK or create a database. No live/default store was initialized by testing.
8. **Undefined typing name.** The reranker omitted `typing.Set`; undefined-name/static checks and a model-independent public type-hint regression now pass. No retrieval score/rank/threshold change.

New runtime tests: 35; evaluator-honesty tests: 6. **41 passed**, with failure/recovery cases. A real Linux native subprocess fault deletes actual Rust bindings, then raises; helper/factory retry is rejected, the tree and failed cache state remain, outside collection works, and another process reopens/queries the retained fixture successfully **after the first process exits**. No real failed registry was forcibly cleared in-process. This is strong Linux/package evidence, not Windows certification.

## Current verification, not historical substitution

Environment: Linux/Python **3.11.2**, isolated non-model venv, Chroma1.5.9/FastAPI0.142.2/Uvicorn0.54.0/Pydantic2.13.5/httpx0.28.1/numpy2.4.6/pytest9.1.1; Node22.22.3/npm10.9.8. No Torch/ST/model weights, Ollama daemon or browser binary. Existing frontend lockfile was installed with scripts disabled; original environment untouched.

| Verification | Current result / scope |
|---|---|
| Full backend at final verification commit | **7 failed, 1312 passed, 137 skipped, 54 errors, 204 subtests passed; 64.08s; exit1** |
| Initial backend baseline | 7F/1247P/136S/54E +200subtests;53.13s. Not green then or now. |
| Release-specific regressions | **41 passed**,see final combined run; no real-model semantic certification |
| Combined lifecycle/evaluation preparation | **86 passed,1 native-sharing skip,1 resource diagnostic deselected,4 subtests**,12.03s; diagnostic is included/failing in the full suite |
| Immutable/source-identity subset | 190P/18S/1deselected+4subtests; current full suite also validates pins/source policy |
| Frontend | **119P/1 live-backend skip**,12 files pass,22.00s; jsdom/fixtures, not browser E2E |
| Typecheck/build | `tsc --noEmit` PASS; Vite6.4.3 build PASS,2.60s; no frontend source/dependency change |
| Lint/format/review | Whole scripts/tests/new evaluator syntax/undefined-name Ruff checks PASS; four new Python files formatter check PASS; `git diff --check` PASS. No unconfigured universal Python type/style guarantee or mass protected-source reformat. |
| Dependency compatibility/audit | Isolated environment `pip check`: no broken requirements. npm audit **0 findings**. Reviewed pip scan: Chroma **2 critical +2 high**, unresolved. |
| Cached Phase3 A0 / oracle | **47/70**,52.1% recall,10 flags / **46/70**,50.7%,10 flags. Cache/lexical metrics, not full RAG or human SAP correctness. |
| Full quality/stages performance | Exit1/missing `sentence_transformers`; no inference, quality JSON or latency/capacity measurements |
| New adversarial package | Hash-protected versioned review cases/all required classes; offline preflight exit2/BLOCKED, not approved gold |
| Native Windows/Q35 | BLOCKED; no host/historical raw reference. Q35 CLI safely refuses absent explicitly quiesced supplied store (exit2). |
| Ollama/browser | Local Ollama tags probe ConnectError; browser smoke exit2 before any server/browser spawn (missing Chromium). No real workflows executed. |
| Backup/restore | Disposable **Linux fixture-only** cold byte-exact copy/new-path restore, corrupt-copy hash rejection and source preservation PASS; actual production rollback BLOCKED |

### Every failure/error/skip reviewed

Complete test IDs and dispositions: `release/evidence/baseline-backend-disposition.json` and `final-backend-disposition.json`. Raw full stdout/XML remain outside edited files at `../backend-final-v7.log` and `../backend-final-v7.xml`; their hashes and reviewed source identities are versioned in `review-manifest.json`.

Final 61 failed/error cases:

- **36** missing ST runtime cases: 31 setup errors (benchmark instrumentation4, golden1, reranker6, hybrid8, concurrency12) plus5 failures (Phase14 two; hardening configured model/absent detail/named-code purpose three). Actual weights/stores are also absent; importing ST alone would not close those gates.
- **24** exact-tokenizer cases: 23 repair-seed setup errors +1 focused115-record diagnostic failure. `make_token_counter()` reports `exact=False`; approximation intentionally rejected. Assertions remain strict.
- **1** original diagnostic child failure: actual separate disposable reproduction confirms FileNotFoundError at `resolve_model`, child exit1, source fixture hashes unchanged. It is **not** evidence that Windows cleanup passed or that the worker completed its full diagnostic.

All137 skips are individually recorded, with aggregated reasons:65 full-stack card/page/model,25 card/model/ST,12 built stores,9 full-stack variant,7 evaluator imports,6 store recreation,4 card-store,3 store/model,2 transformers/local model,1 evaluator imports,1 exact tokenizer resolver,1 embedding tokenizer,1 actual Windows sharing semantics. Frontend skip is the explicit `LIVE_BACKEND=1` integration in `sura_ux.test.tsx`; never counted as real browser/model evidence.

Warnings: provisioning script-location/PATH warnings only (explicit venv executable used); npm reports deprecated **whatwg-encoding3.1.1** (development jsdom dependency path, zero current npm advisory findings, follow-up maintenance rather than arbitrary lock churn). No warning summary was emitted by the final backend/build runs. Native/source-only/mocked limitations are recorded, not concealed.

## Product, security and operations blockers

- **Highest gate — SAP semantic correctness remains inadequate/unverified.** Historical full-RAG37/65, wrong-page/negative-label drift, cached procedure/relevance/ambiguity weaknesses and ten heuristic flags remain open. M2C-18 has no verified guide/page mapping. New positive cases reuse frozen AI references; no invented SAP gold. Independent source/version/claim adjudication and actual full RAG are required; abstention is not substantive correctness.
- Actual approved embedding runtime, exact tokenizer/model hashes, card/page stores and intended hardware are absent. No large alternative Torch/model download was used to disguise that gap.
- Native Windows original assertions/handles/finalizer/retained aliases/same-path/partial-failure proof remains external. GitHub repository is public, but has **zero existing workflows**; Actions administration/permissions inspection is integration-denied403. No hosted runner was provisioned/dispatched, no permission/billing assumption made, and no native environment substituted for the required approved one.
- Q35 historical Windows raw/environment provenance is missing; new rounded/arithmetic output cannot reconstruct it. Strict equality/tolerance unchanged.
- Real Ollama, real supported browser, authenticated gateway/session, accessibility and actual failure/cancel/recovery workflows remain unexecuted. Existing browser smoke is a local workflow, not certification of authenticated production ingress.
- Four Chroma advisories have no listed patch. Their HTTP-server endpoints are not SURA's local Rust architecture, but package/native/model-store risks and actual target reachability still need security disposition/authorized acceptance. Actual production/native/OS/Windows/model graph and hash-lock provenance are incomplete. Scope-tagged 506-component CycloneDX inventory is not a certified production dependency-edge SBOM.
- Native synchronous work is not guaranteed immediately interruptible; no verified absolute full-pipeline deadline/cancellation/drain bound exists. Admission is retained until completion; closing resources under active workers is avoided. Real target recovery proof remains mandatory.
- Full-API performance is **unmeasured**. Versioned p50/p95/p99/RPS/cold/memory targets/reference host are declared, all rejects/difficult/incorrect requests must be counted, and single-IP default60/min cannot be claimed as20RPS production capacity. No sandbox capacity extrapolation.
- Actual deployed known-good release/store backup/platform/monitoring/rollback and human approval are absent. Repository rollback20cb is not proven production rollback. No automatic production store activation or repair.

## Deliverables and safe stopping point

Required reports are present: `RELEASE_GATES.md`, this report, `SECURITY_AUDIT.md`, `RAG_QUALITY_REPORT.md`, `WINDOWS_VERIFICATION_REPORT.md`, `DEPLOYMENT_AND_ROLLBACK.md`. Supporting source/tests, frozen-input adversarial package, complete failure/skip dispositions, inventories, advisory metadata, preservation manifests and fixture rollback proof are versioned.

Remaining affected operations stop at the genuine native/model/content/security/operator resource and approval boundaries described above. This mission's acceptance is **not complete** merely because engineering changes/reporting are delivered. Resume full runtime/adjudication/native/ingress/rollback verification on the required approved resources, fix demonstrated product failures without rebaselining, and re-evaluate every mandatory gate before any deployment decision.

**Only READY FOR APPROVED DEPLOYMENT if every mandatory gate genuinely closes. Current verdict: NOT READY.**
