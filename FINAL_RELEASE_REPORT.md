# SURA — pre-deployment hardening: final verification report

**Verdict: NOT READY** for public deployment under this mission's verification gate.
**No public deployment was performed.** Engineering changes are implemented and the Linux verification gate is green, but semantic-quality, native Windows, real-model and security dispositions remain incomplete.

Date: 2026-10-13 · Repository: `Sravan-git7/chatbot` · Release branch: `arena/b450cda2-chatbot`.
**Measured runtime commit: `05ef5e7c99aca8a03ee05b61ba16128093c2e1b9`**, descended from verified baseline `6eb9d9d`, `0c6ebdd`, `a6b1b53`, `9be6553` and `c7527ed`.
The final report/artifact commit is supplied in the delivery message; it changes documentation/results only, not the measured runtime. This avoids assigning a self-referential hash to this report.

## 1. Engineering delivered

Implemented targeted fixes, not a rewrite or an issue-only audit:

- Admission-slot leakage after startup failure fixed; repeated 503s do not permanently saturate the API and recovery works.
- Body limits enforce **received bytes**, including chunked requests; body reception expires after 10 seconds with controlled 408.
- Ollama has a finite default network timeout (60 s); invalid/non-finite settings cannot disable it. `OLLAMA_MODEL` now actually configures the shipped client, with explicit constructor override preserved.
- Request/generation FIFO queue waits are bounded (30 s); expiry returns 504, removes waiters, preserves permit accounting, and avoids conversation mutation.
- Invalid configuration fails closed rather than merely warning. `/api/health` cannot contradict unavailable dependency readiness.
- Copyable environment example keeps debug/privacy/experimental settings safe. Arbitrary request-id text is replaced by a bounded safe identifier; unexpected request logs retain exception type rather than private payload/traceback.
- Missing **preselected/preset/default** detail now abstains rather than returning unrelated instructions. A named-code purpose question cannot be answered from a navigation-only “find more information” pointer on another page. Both fixes have positive controls and shipped-pipeline regressions.
- Admission cap is configurable with a safe unchanged default of four; blank/invalid settings and raised/lowered caps are tested. Benchmarks distinguish completed RAG work from 429 saturation.
- Reproducible preflight, safe byte-exact checkout refresh, dependency snapshot/ranged prerequisites, private API/UI smoke, live-HTTP frontend runner and compact Windows verification automation added.
- Patched vulnerable Vitest/mocker tooling and removed vulnerable Tinypool dependency; preserved all UI assertions. The formerly skipped live UI test was repaired against the current **28-source** contract/current composer and actually executed.
- Fixed versioned workloads, machine-readable latency/quality/security results, stage instrumentation and a strict wrong-source evaluator added. No answer cache, evidence truncation, invented source mapping or paid model service introduced.

Regression additions: **28 backend tests** (8 instrumentation/evaluator, 16 hardening/resource/checkout, 4 admission configuration) and **4 frontend tests** (2 error/recovery, 2 dependency advisory guards). Existing timeout assertions were strengthened to require finite defaults; historical source/gold assertions were not weakened.

Detailed root causes and test disposition: `PRE_DEPLOYMENT_AUDIT.md`.

## 2. Full verification counts and scope

| Gate | Actual result |
| --- | --- |
| Complete backend `pytest tests/ -q -ra`, committed source | **1366 passed, 225 subtests passed, zero failures/skips**, one Starlette deprecation warning; 163.57 s |
| Frontend ordinary component/unit suite | **119 passed, 1 skipped** (120), 12 files |
| Entire frontend suite with real HTTP backend | **120 passed, zero skips/failures**, 12 files (`frontend_live_verification.py`) |
| TypeScript typecheck | passed |
| Production frontend build | passed, 296 modules; JS 366.49 kB (gzip 113.86), CSS 41.28 kB |
| Source/corpus, checkpoints, retrieval, evidence, citations, follow-ups, security, concurrency, readiness, logging | included in the complete green backend suite; no subsets substituted |
| Independent current-production reference quality | 113 cases, real embeddings/stores, deterministic extractive generation; paired baseline/final outputs retained |
| Phase 3 A0 / oracle / A2_mock | executed to **new** files; cache/mock limitations explicitly labelled |
| Private live API/UI-serving smoke | passed nine checks, including supported/follow-up/unsupported/missing evidence/M2C-18/malformed/oversized/debug/headers |
| Real Ollama inference | **BLOCKED** here: runtime/model unavailable. Actual outage contract tested, not a positive inference pass |
| Chromium/Playwright | **BLOCKED**: binary absent, actual launch availability checked; no browser pass claimed |
| Native Windows Python 3.10/full numerical and generated-byte reproduction | **NOT EXECUTED** from Arena; pending handoff gate |

The live frontend run uses jsdom plus actual API requests, not a real browser. Ordinary unit tests use explicit HTTP fixtures. Backend tests include both injected fixtures and real-store cases; stub client success never counts as real Ollama inference.

## 3. New latency evidence — extractive only

Same frozen workload v2, actual baseline `6eb9d9d` archive versus committed `05ef5e7`; 13 items × 100 warm measured final-turn requests = **1300 samples per mode/run**. Warmups/cold start kept separate; nearest-rank percentiles. Every measured sequential response matches status/card expectations.

| Mode | Baseline p50 / p95 / p99 | Final p50 / p95 / p99 |
| --- | --- | --- |
| Full in-process service | **40.61 / 64.78 / 78.78 ms** | **34.82 / 53.83 / 62.59 ms** |
| End-to-end HTTP API | **45.01 / 68.65 / 82.23 ms** | **37.59 / 54.57 / 65.51 ms** |

HTTP mean/stddev: 45.84/16.24 → 38.30/13.02 ms. Expected abstentions: 400/1300; errors/timeouts: zero. Per-item distributions, individual stage windows, sample counts, document/context lengths and all raw summary metadata are preserved in JSON.

Hardware: Linux x86-64, Intel Xeon @2.60 GHz, **2 CPUs**, ~3.85 GiB RAM; Python 3.11.2, Node 22.22.3; MiniLM CPU, Chroma 1.5.9, sentence-transformers 6.1.0, Torch 2.14.1, NumPy 2.4.6. Corpus: 29 cards/28 pages/113 vectors, hash `46e7c63a…`; routing top-k 10, page cap 5, context cap 4, budget 700 tokens.

Model/store construction: **6.881 → 5.404 s**. First service request: 85.77 → 61.30 ms; first HTTP request: 105.82 → 79.88 ms. Final peak RSS: stages 925.8 MiB, API 956.3 MiB. These are sandbox measurements, **not Windows-PC numbers** or causal/statistically established speedup claims.

Baseline already met the initial latency budgets. Existing one-query-embedding/request-local retrieval reuse was preserved; no risky caching or grounding tradeoff was justified. API p95 includes generation and is below 200 ms here, conservatively bounding non-model overhead. Routing dominates extractive cost. Exact stage boundaries and unavailable pure-stage/resource counters are documented rather than invented.

## 4. Throughput and saturation

200 offered mixed requests per concurrency level; per-IP limiter lifted **only for the private benchmark process**. Production admission cap remains four. Completed RPS excludes rejections; accepted/rejection/all-response distributions are separate.

| Clients | Final accepted / 429 | Completed RPS | Accepted p95 |
| --- | --- | --- | --- |
| 1 | 200 / 0 | 27.15 | 51.16 ms |
| 4 | 200 / 0 | 33.58 | 172.03 ms |
| 5 | 53 / 147 | 27.17 | 222.81 ms |
| 10 | 34 / 166 | 26.53 | 241.93 ms |
| 20 | 24 / 176 | 19.99 | 480.53 ms |

All accepted responses correct; zero errors/timeouts. **Four concurrent requests** is the declared default target, not twenty. Small saturation samples cannot support strong tail guarantees.

Separate opt-in admission-cap-20 experiment: all 200 requests at each of 1/5/10/20 complete correctly, zero 429s/errors/timeouts. Completed RPS = **25.96 / 33.27 / 29.94 / 31.92**; accepted p95 = **57.35 / 237.77 / 462.05 / 825.94 ms**. This queues through the same four service slots, not extra compute or silently discarded work. Do not extrapolate it to an unmeasured LLM host.

**Ollama latency/throughput: BLOCKED**, reported separately; no numbers fabricated or mixed with extractive.

Full methodology, before/after tables, stages and goals: `LATENCY_RAG_COMPARISON.md`.

## 5. Independent quality results

Same 113 frozen AI-authored reference cases (not blind expert gold); 65 answerable, 40 negative-labelled, 8 ambiguous. The final evaluator requires expected guide/page in citation **and** context plus expected evidence in the answer.

| Metric | Baseline → final |
| --- | --- |
| Recall@1 / known-gold precision@1 | 95.38% → 95.38% |
| Recall@5 | 100% → 100% |
| MRR, truncated at 10 | 0.9744 → 0.9744 |
| Gold evidence in context | 62/65 → 62/65 |
| Strict reference-evidence answers | **37/65 → 37/65 (56.92%)** |
| Wrong-page answered cases | **1 → 0** (withheld, not assigned an invented replacement source) |
| Answers against frozen negative labels | **11/40 → 10/40** |
| Appropriate abstention under those labels | 72.5% → 75% |
| Phantom citations / citation-context identity mismatches | 0 / 0 → 0 / 0 |
| Lexical supported-sentence rate | 100% → 100%; **not semantic truth** |

The ten remaining negative-label answers correspond to eight formerly missing pages and two formerly unresolved identities now admitted. Frozen labels are not rewritten; independent semantic/source-alternative adjudication remains necessary. Strict evidence coverage/correctness is not sufficient to certify the product's broad answer quality.

Fresh Phase-3 cached A0: **47/70 behavior matches**, mean key-fact recall **52.1%**, citation checks 100%, **10 prohibited-claim flags**, unchanged before/after. Oracle A0: 46/70, 50.7%, ten flags. A2_mock: fixture only (53/70, 28.2%, two flags), **not an LLM result**. Cache retrieval timings remain historical inputs, not current retrieval measurements. Those unresolved quality signals are part of the NOT READY verdict.

## 6. M2C-18, historical artifacts and reproducibility

**M2C-18 stays fail-closed**, no authoritative new SAP mapping available. The page is absent from its card guide's verified TOC and appears only in an unregistered alternate deliverable. Required evidence remains an exact-public-URL capture to a verified registered guide/TOC, or authoritative alternate-guide registration/TOC plus permission to repoint the card. No answer/evidence/source identity fabricated.

Both prior release reports, source corpus/provenance, pinned checkpoint, identity records, historical Ollama/environment/evaluation artifacts and frozen query/gold files remain unchanged. New runs live only under `benchmarks/results/`; early invalid/exploratory attempts are explicitly adjudicated, never blended into final numbers.

`.gitattributes` and the refusal-safe checkout refresh fix Windows checkout newline conversion. The sealed producer's platform-default newline output is a **separate unresolved native Windows gate**. Do not skip/weaken `test_chunk_candidates.py` or rewrite its pins to manufacture green. `test_phase7b.py` also requires exact embedding/store prerequisites; Linux passed, Windows remains pending. Legacy `chroma_db/`, personal caches and backups are not deleted.

Dependency snapshot: 127 runtime/test version pins, Linux/Python-3.11 baseline; not a hash-locked cross-platform wheelhouse. Existing `av`/Python-3.10 uses ranged required prerequisites plus packaged MiniLM; a personal absolute cache path is not required. Native Windows compatibility/numerical reproduction must still be measured.

## 7. Security scope and remaining blockers

- npm audit: initial critical test-tooling chain fixed; **zero final findings**. Two regression guards prevent restoring the vulnerable versions.
- pip consistency: no broken requirements. PyPI advisory audit covers **127 pins** and returns five rows representing **four unique Chroma server CVEs**, no fix versions supplied. Local PersistentClient/chat do not expose the affected collection/model-configuration HTTP endpoints, but this is scoped exposure analysis, not a clean security certification. Keep Chroma servers unexposed and obtain a patched supported version/security disposition.
- Public exposure needs an approved authentication/TLS boundary and per-user authorization/isolation. Client-chosen conversation ids are not an authentication boundary. Tested concurrent isolation is between distinct conversations; overlapping same-id turn ordering is not independently certified.
- Body, FIFO queue, Ollama network operations and browser requests are bounded; arbitrary hung native execution has no hard interruptible server deadline. Direct ASGI-factory operation also requires explicit operator structured-logging configuration; the CLI is the verified start mode.

### Concrete next actions / release impact

1. **Quality:** independently adjudicate reference failures, Phase-3 prohibited flags and corpus-drift cases; publish a new reviewed versioned gold set without overwriting frozen baselines. Improve genuine missing-fact/answerability defects against that evidence. Current 56.9% strict reference correctness is not enough for public approval.
2. **Windows:** execute the compact handoff; retain failures. Resolve native sealed-writer/numerical reproduction with an approved versioned migration or a declared Linux/WSL verification target. Do not silently alter checkpoint pins.
3. **Real model:** use the already installed local Ollama model for a positive round trip and the same workload; capture local hardware, tails, throughput and timeouts. No fixed LLM latency promise before measurement.
4. **Browser:** run the supplied new smoke with existing/approved Chromium binaries. jsdom/live HTTP does not substitute for browser rendering/accessibility certification.
5. **Security/reliability:** obtain Chroma advisory disposition and an approved public access/isolation boundary; evaluate a process-level hard execution deadline if hard cancellation is required.

## 8. Compact Windows handoff

From `D:\chatbot-phase12`, preserve local changes, fetch and fast-forward only, verify the exact pushed release commit from the delivery message, then run one helper:

```powershell
Set-Location D:\chatbot-phase12
if ((git status --porcelain).Length -gt 0) { git stash push -u -m 'pre-hardening-local-backup' }
git fetch origin
# Must be on arena/b450cda2-chatbot; stop and inspect any divergence.
git merge --ff-only origin/arena/b450cda2-chatbot
git log -1 --oneline
.\scripts\verify_windows.ps1 -Python .\av\Scripts\python.exe -InstallPrerequisites -BuildMissingStores
```

For the existing available model: set `OLLAMA_MODEL` to its actual name and run the same helper with `-Ollama` (no `ollama pull`). The helper captures new results in `%TEMP%`, runs the full suite/live UI/API/same benchmarks, preserves caches/manifests and reports failures rather than skipping them. Detailed fresh setup, safe branch switching, byte caveat, local UI start and comparison instructions: `LOCAL_PRODUCTION_VERIFICATION.md`.

## 9. Release preservation and delivery

Changes are confined to intentional source/tests/dependency/tooling/benchmark/docs/results files. No secrets, env files, private backups or vector/model caches are committed. Both branches remain preserved; normal fast-forward push only. Runtime source is committed as `05ef5e7`; a subsequent artifact/report commit carries this report and measurement files, with final remote synchronization verified in the delivery message.

**Final verdict: NOT READY.** The measured Linux extractive configuration is materially hardened and fast, with complete regression and live component/API coverage. That is not enough to pretend the remaining quality, platform, model, browser and public-security gates are satisfied.
