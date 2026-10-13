# SURA pre-deployment audit and trustworthy baseline

Date: 2026-10-13. Scope: correctness, reproducibility, performance, independent quality, security and local handoff.
**No public deployment was performed.** Current decision is in `FINAL_RELEASE_REPORT.md`; this document records the starting state and disposition, not an assertion that old green suites prove readiness.

## Git and evidence boundary

- Starting release tip verified on GitHub: `6eb9d9d25dda75bf9092838b813faa7a51cd8473`, branch `arena/b450cda2-chatbot`.
- History is linear through `c7527ed`, `9be6553`, `a6b1b53`, `0c6ebdd`, `6eb9d9d`.
- The re-provisioned workspace initially had stale Git metadata at `c7527ed` with restored file contents. 107 dirty files already matched the remote release tip; the remaining two matched its parent (`0c6ebdd`). Those two were reconciled to the already-committed remote versions, then a **mixed**, non-worktree-discarding reset aligned metadata. No unique local content was discarded; the resulting baseline was clean and synchronized. No hard reset, clean, force push, branch deletion or history rewrite was used.
- `arena/4fe57164-chatbot` remains at `c7527ed`; all other branches are preserved.
- `RELEASE_REPORT.md` and `docs/RELEASE_REPORT.md` were inspected as historical reports and are not rewritten as new measurements. The latter contains older Windows/browser claims; they are not current sandbox results.
- `LOCAL_PRODUCTION_VERIFICATION.md` was **absent** from this Git checkout at baseline. The user's `D:\chatbot-phase12` and its local verification evidence are inaccessible from Arena. A new handoff document is supplied; native Windows results are not invented.
- Runtime review covered the API/service/follow-up path, card routing and reranking, page retrieval, context/evidence guards, generation, verification/citations, UI request handling, readiness/logging, build/provisioning scripts, evaluators and all test modules. `benchmarks/results/v1_source_inventory.json` records the inspected tracked-code inventory; it is not a claim of exhaustive human review of every historical artifact.

## Fresh baseline measurements (not historical)

The missing venv, frontend dependencies/build and ignored stores were provisioned locally. Builders used scratch manifest outputs, not sealed provenance files. The same MiniLM weights were supplied by the existing third-party packaged model wheel. No new generative model or paid API was introduced.

| Baseline gate at `6eb9d9d` | Newly executed result |
| --- | --- |
| Entire backend `pytest tests/ -q` | 1338 passed, 225 subtests passed, zero failed; 176.30 s |
| Frontend typecheck | passed |
| Frontend component suite | 115 passed, 1 skipped (116); the skipped live-API workflow was later investigated |
| Production frontend build | passed, 296 modules |
| Paired workload v2 in-process | 1300 measured requests; p50 40.61 / p95 64.78 / p99 78.78 ms |
| Paired workload v2 HTTP | 1300 measured requests; p50 45.01 / p95 68.65 / p99 82.23 ms |
| Independent frozen Phase-12 reference evaluation | 113 cases: 37/65 strict evidence answers; 1 wrong-page answer; 11/40 answers against frozen negative labels |
| Fresh Phase-3 A0 run of sealed cached evidence | 47/70 behavior matches; mean key-fact recall 52.1%; citation checks 100%; 10 prohibited-claim flags |

Timing source: `v2_baseline_stages.json` and `v2_baseline_e2e.json`, using an immutable Git archive of **the actual baseline commit**, the same model/stores and workload. Quality source: `v1_baseline_quality.json`; cached Phase-3 source: `v2_phase3_baseline_a0.json`. Earlier exploratory benchmark attempts are retained and adjudicated in `benchmarks/results/README.md`, never blended into the release comparison.

Hardware: Linux x86-64, Intel Xeon @2.60 GHz, 2 logical/affinity CPUs, ~3.85 GiB RAM; Python 3.11.2, Node 22.22.3. Chroma 1.5.9, sentence-transformers 6.1.0, Torch 2.14.1, NumPy 2.4.6; MiniLM all-MiniLM-L6-v2 on CPU; deterministic extractive generation. Corpus: 29 cards, 28 admitted pages, 113 vectors, corpus hash `46e7c63a…`. This is **not** the user's Windows hardware.

## Functional defects and blockers found by inspection/live execution

| Finding | Root cause | Disposition / regression |
| --- | --- | --- |
| Failed startup consumes admission slots permanently | `current()` ran before the `try/finally` decrement | Moved inside guarded region; six repeated 503s leave zero active slots and subsequent recovery succeeds (`test_predeployment_hardening`) |
| Chunked oversized bodies bypass the size guard | Only Content-Length was checked | Received-byte cap now applies without that header; 413 and recovery tested |
| Slow body reception can wait indefinitely | No body-read deadline | 10-second reception deadline, controlled 408, tested cancellation path/recovery |
| Unbounded default Ollama calls | Default module-level client had no enforced finite timeout | Finite 60-second Client timeout, configurable; invalid/non-finite values cannot disable it (`test_health_ready`) |
| Configured local model ignored | Client chose only hardcoded default/explicit argument, not OLLAMA_MODEL | Shipped chain now respects environment model; explicit override remains authoritative (`test_predeployment_hardening`) |
| Queued requests/generations can wait indefinitely | FIFO semaphore acquired without timeout | 30-second queue wait bound; typed 504, waiter cleanup, permit accounting and conversation recovery tested |
| Invalid configuration only warns but keeps serving | Lifespan caught validation errors without closing readiness | Invalid configuration fails closed (health 200, ready/chat 503), tested |
| Legacy `/api/health` can contradict readiness | It reported any initialized service as ready | Delegates dependency readiness; unavailable model remains 503/ready false, tested |
| Debug-enabled copyable example | `.env.example` had RAG_ENABLE_DEBUG=1 | Example now off; regression locks privacy/experimental flags off |
| Request error logs can expose exception payloads | Raw exception message and traceback logged | Log only type + safe request id; regression rejects private query/secret text |
| Arbitrary request-id text forwarded into logs | Header had no bound/character validation | Bounded ASCII ids accepted; arbitrary values replaced with generated UUID, tested |
| “Preselected” questions answered from generic instructions | Default-detail cue recognized only “default” | Cue family expanded; missing preselected interval detail abstains, positive default evidence tested |
| Named-code purpose answered from a cross-reference pointer on a different page | Mere code occurrence passed sufficiency | Navigation-only pointers cannot answer named-code required/used-for questions; incorrect answer withheld, supported transaction positive control retained |
| High-concurrency benchmarks appeared very fast because of 429s | Per-IP limiter and four-request admission cap conflated with RAG completions | Harness lifts only benchmark per-IP limit; accepted/rejected latency and throughput separate; configurable admission cap defaults to four and is tested |
| Skipped live UI test was stale | It assumed 25 pages, old “pages” wording and a removed suggested button | Correct 28-source contract + current composer; all 120 frontend tests pass with actual HTTP backend |
| Vulnerable development test tooling | Vitest/mocker/Tinypool advisory chain | Patched Vitest 4.1.11, explicit DOM test peer + lock; two advisory regression tests; npm audit now zero findings |

The benchmark also strengthens success criteria: expected card identity, grounding and citations matter, not merely an HTTP 200/“answered” status. The independent quality evaluator rejects plausible answers citing the wrong page/context identity and requires expected evidence in the answer.

## Reproducibility and legacy test disposition

- No `.gitattributes` existed. Windows autocrlf conversion changes checkpoint-pinned bytes. New `* -text` policy preserves both LF and historically committed CRLF blob bytes; no renormalization is performed.
- Safe `refresh_checkout_bytes.py` fixes only newline-converted tracked files; genuine/staged edits abort before writes. Regression exercises converted bytes, real edits and untouched private backup files.
- The sealed `build_chunk_candidates.py` still writes with platform-default newlines. Its native Windows byte-equivalence test remains a **pending gate**; preserving the checkpoint forbids quietly rewriting that producer/artifact/pin chain. Linux reproduction passes. A versioned producer/checkpoint migration needs explicit approval, or use Linux/WSL for the historical gate.
- `test_phase7b.py` requires actual stores and the exact local embedding weights. Both suites passed in the complete Linux baseline/final runs; the user's native Windows environment remains unverified.
- `chroma_db/` is ignored legacy data, not a current runtime dependency. Current builders explicitly refuse its name/path. It was not present here and was not deleted on any machine.
- `resolve_model` accepts explicit path, M2C_MODEL_DIR, or the pinned packaged model. Its old docstring mentions an HF-cache fallback, but the actual function does **not** scan the personal HF cache. New setup docs reflect the actual code; the checkpoint-pinned module itself is preserved.
- `requirements.lock.txt` records the Linux Python-3.11 environment, with Linux-only markers. It is a **version lock**, not a hash-locked wheelhouse or a verified Windows/Python-3.10 closure. `requirements-verification.txt` supplies required ranged prerequisites to the existing `av` environment without personal cache assumptions.
- `pip check` reports no broken requirements. Full native Windows numerical reproduction remains pending.

## Evaluation modes and integrity boundary

| Evaluation / test | What actually executes |
| --- | --- |
| Workload v2 stages/HTTP + 113-case independent quality | Real local MiniLM + real Chroma stores, deterministic extractive generator; no LLM |
| Full backend suite | Mix of explicit fake backends/clients, deterministic generators and real-store tests; passing model-client tests are **not** real inference |
| Frontend ordinary suite | Mock HTTP fixtures; 119 pass + one live test skipped |
| Frontend LIVE_BACKEND suite | All 120 pass; ordinary fixtures plus one real HTTP/jsdom UI workflow; **not a Chromium browser run** |
| Phase-3 A0/oracle | Current deterministic generator against the sealed evidence cache; retrieval timings from that cache are historical, not new retrieval measurements |
| Phase-3 A2_mock | Fixture/plumbing only; never LLM quality/performance evidence |
| Real Ollama | BLOCKED here; missing runtime/model. Outage /health 200, /ready 503, chat 502 verified; no real generated answer claimed |
| Playwright | BLOCKED: Chromium binaries absent, launch checked. No browser pass claimed |

Sealed corpora, source identities, query/gold sets, historical reports/results, checkpoint and model provenance were not regenerated. New runs are written only under `benchmarks/results/`.

## M2C-18 and remaining release blockers

M2C-18 remains fail-closed. Its page `b1a202c9…` is absent from the card guide `94424864…`'s verified 1481-node TOC and appears only in deliverable `40374490` / unregistered guide `e4375c1c…`. Missing authoritative evidence: capture of the exact card URL to a registered verified guide whose TOC contains the page, **or** verified registration/TOC for `e4375c1c…` plus authority to repoint the card. help.sap.com is unavailable in this sandbox. No mapping is invented; `test_map_root_identity` remains the machine-checked gate.

Current blockers are not concealed by the green suites: incomplete independently reviewed gold coverage/answer correctness, native Windows sealed-byte/numerical reproduction, real local Ollama measurements, absent browser binaries, and Python dependency advisories requiring scoped review. See final release report for impact and concrete next actions. Public exposure also requires authentication/TLS/per-user state isolation; client-provided conversation ids are not an authorization boundary. Queue/network/client timeouts are bounded, but arbitrary hung native code is not forcibly cancelled by a hard end-to-end server deadline.

## Dependency advisory scope (new measurements)

`npm audit`: initial three vulnerable dependency nodes, including critical Tinypool/Vitest findings; patched tooling now reports zero. This scans the installed frontend dependency graph against npm advisories, not source-code security or the browser/runtime OS.

`pip-audit --vulnerability-service pypi --disable-pip --no-deps -r requirements.lock.txt`: 127 pinned dependency rows; five finding rows (one duplicate), **four unique Chroma advisories**, no fix versions supplied: CVE-2026-45829, CVE-2026-45833, CVE-2026-45831, CVE-2026-45830. They concern Chroma HTTP collection/configuration endpoints and tenant/permission checks. SURA uses local `PersistentClient` stores and exposes neither a Chroma server nor arbitrary collection/model configuration through chat. That narrows the current exposure, but does **not** turn the advisory audit into a clean bill of health. Keep Chroma HTTP servers unexposed; obtain a patched supported release/security disposition before public approval. No arbitrary dependency upgrade was made that would invalidate pinned numerical/source reproduction.

The documented CLI is the verified structured-logging entrypoint. Direct ASGI-factory operation requires an explicit operator logging configuration; it is no longer presented as equivalent to the verified CLI logging setup. No authentication/TLS boundary or hard kill deadline for arbitrary native-code hangs was added. These are explicit remaining operating-boundary limitations, not silently certified capabilities.
