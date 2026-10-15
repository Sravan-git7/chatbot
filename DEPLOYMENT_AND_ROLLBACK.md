> **2026-10-15 closure follow-up — NOT READY.** The assessment below is the published `a027cd64` record, not the latest result. See [RELEASE_BLOCKER_CLOSURE.md](RELEASE_BLOCKER_CLOSURE.md) for the exhaustive current blocker classification, all61 independent failure reproductions, narrow fixes and external procedures. Tested source: `47e1e09aece4feb03aeae3abd06c5458b983ba07`; backend **7F/1330P/137S/49E +204 subtests**. All four Chroma advisories remain open. Frozen `phase12_results.json` reports38/65 and two wrong-page cases; the older37/65 narrative remains provenance-unreconciled, not a new run or baseline change. No production activation authorized.

# Deployment and rollback — prepared, NOT activated

**NOT READY. Human approval is required before exposure, migration, store replacement or activation.** No public server, production-store repair, deployment, model download or candidate activation occurred.

## Identity and prerequisites

- Session/release branch: `arena/b450cda2-chatbot`; repository rollback point `20cb6daa4c6cd4efd2c1d0ee117380101d843a5d` (the observed live GitHub tip before this mission).
- Final functional candidate: `c324ffb366511b15385524aa8ed24e956f662780`. Package report commits do not alter runtime. Original checkout remains at `c7527ed...`, unchanged. **The actual deployed known-good version/production backup is unknown:** a repository rollback point is not verified production rollback.
- Require every release gate, authoritative SAP adjudication, native Windows/Q35 provenance, actual runtime advisories/artifact hashes and authorized security dispositions before approval. Do not use historical report passes as current certification.
- Preserve existing models, `av`, backups, `scratch`, legacy stores and all manifest/evaluation/checkpoint files. Never repair originals or silently overwrite a destination. A model/package/production graph change requires a separate reviewed candidate and compatibility verification.

## Private staging preparation

1. Create a fresh immutable source artifact/release directory from the reviewed commit. Use a new private target, not the original dirty checkout. Build frontend with the existing lockfile (`npm ci --ignore-scripts`, typecheck, tests, build). Retain bundle hashes and an actual-target SBOM; do not add generated bundles/models/stores to Git.
2. Provision only approved existing local embedding/Ollama resources and the supported target dependency closure. Linux Python 3.11 lock does not certify Windows/Python 3.10. No automatic model pulls, paid LLM services, Docker/public exposure or speculative package upgrades.
3. Quiesce **all** source-store writers/processes under an approved maintenance plan. Inventory owners and every file, including SQLite WAL/SHM and HNSW files. Only then copy the complete card store tree (including the nested page store), corpus/manifests, approved model/config identity and runtime/artifact inventories to a **new** private backup path. Source before/after hashes must match; copied hashes must match before anything opens it. Incomplete/changed snapshots abort; retain evidence and originals.
4. Restore into another **new** release/store path, never over the live tree. The application resolves stores relative to its source release root; there is no newly invented store-path environment override. Preserve the expected manifest/provenance contract. Run child-process diagnostics on cold copies and wait for children to exit before cleanup. Opening a copy can change Chroma bookkeeping; compare exact backup bytes **before** opening and semantic integrity afterwards.
5. Verify exact collection IDs/counts/documents/metadata/source identity/chunk/model hashes and strict historical numerical policy. Wrong records, missing exact tokenizer, drift, unavailable historical raw scores or mismatched guide versions stop promotion. The existing repair utility remains opt-in, backup-first, exact approved two-record scope and abort-on-drift; do not invoke it automatically.
6. Validate authenticated private staging, health/readiness, full frozen/new quality and performance workloads, real browser/axe/accessibility, real Ollama fail/recovery/cancel and actual Windows cleanup. Run with production limits and report every error, timeout, rejected/difficult/incorrect request and resource profile.

## Configuration boundary

Use a secret manager/service manager, not committed `.env` files, command-line token arguments, shell trace or frontend variables:

```text
SURA_PROFILE=production
SURA_API_TOKEN=<secret-manager supplied high-entropy secret, 32–256 ASCII characters>
SURA_ALLOWED_HOSTS=<explicit private ingress host names; no wildcard>
HOST=127.0.0.1
RAG_ENABLE_DEBUG=0
SURA_LOG_QUERIES=0
SURA_INTENT_AWARE=0
SURA_SECTION_SELECTION=0
SURA_ADDITIONAL_EVIDENCE=0
SURA_MAX_CONCURRENT_REQUESTS=4
SURA_RATE_LIMIT_PER_MINUTE=60
SURA_QUEUE_TIMEOUT_SECONDS=30
SURA_OLLAMA_TIMEOUT_SECONDS=60
RAG_GENERATOR=extractive
RAG_CORS_ORIGINS=<explicit trusted origin, or empty for same-origin only>
RAG_CSP_FRAME_ANCESTORS='none'
```

Production has no implicit development CORS origins; wildcard framing/CORS is rejected. These are configuration instructions, **not real credentials**. Use an approved local model path/digest when enabling Ollama; require configured-model readiness and no fallback to extractive.

Supported startup, only after approval in private staging:

```sh
<approved-python> scripts/rag_api.py --host 127.0.0.1 --port 8000 --generator extractive
```

Gateway authenticates/authorizes actual users, strips incoming Authorization and forwarding headers, injects the backend secret server-side, preserves an allowed Host and forwards only over private transport. Restrict trusted proxy addresses explicitly (never `FORWARDED_ALLOW_IPS=*`), or do not trust forwarded headers. Enforce TLS, request/connection/body/time limits and credential-redacted logs at ingress. Authenticate static content too; tokenless direct browser access to the protected backend is not the supported production UX. Real gateway/browser integration is not certified here.

Liveness `/health` is not readiness. Route traffic only after `/ready` is healthy and semantic/integrity gates pass; startup failure may keep liveness healthy while readiness is 503. Do not put secrets in health URLs or probes.

## Performance and shutdown

Versioned targets and frozen workload hash: `eval/release_v1/cases.json`. Reference host is 8 x86_64 vCPU/16 GiB RAM with approved local resources, **not this sandbox**. Extractive warm p50/p95/p99 <=100/200/500 ms, >=20 aggregate completed RPS; generative preliminary target p50/p95/p99 <=5/15/20 seconds, >=0.2 completed RPS at one generation permit. Zero accepted-work errors/timeouts/incorrect answers. Cold readiness <=120 seconds; declared memory/plateau budgets are recorded separately. None measured here.

Single-IP default rate limit cannot certify 20 RPS; aggregate proof requires multiple actual client IPs through trusted ingress. Do not disable limits, hide 429s or cherry-pick successful/correct requests to claim capacity. Current benchmark harness cannot complete without model resources and does not yet certify the production authenticated/stateless gateway workload.

Shutdown stops admission and drains in-flight workers for up to five seconds. Owned resources close only after a full drain; on drain expiry resources are retained until process exit, not closed under active native workers. Native/HTTP cancellation is not immediate; there is no verified absolute full-pipeline deadline. Demonstrate bounded real cancellation, process shutdown, restart and handle release on target. Any partial native close/stop is terminal: preserve its tree, do not reopen through raw SDK clients, and restart the process. Do not declare a successful shutdown after a close exception.

## Backup/restore evidence and rollback

Current **disposable Linux fixture-only** cold-restore experiment passed: child exited before copy, byte-exact backup and new-path restore before open, restored count/ID verified in another exited child, injected corrupt-backup hash rejected, source fixture unchanged. See `release/evidence/cold-restore-fixture.json`. It is not production backup/restore or Windows certification.

Before activation, identify the actual deployed known-good code, compatible store/model/corpus and cold verified backup; prove restore into an unused path and run the same authenticated semantic smoke. Prepare a release-pointer/service-manager rollback plan with explicit approver, observation window and data-write policy. Never roll back by `git reset --hard`, force-push, normalization, blanket restore or overwriting a store.

If approved rollout fails: stop new ingress/admission, retain logs/artifacts and both store trees, stop affected processes safely, point the service to the **verified** previous immutable code+compatible restored store under approval, re-run readiness/authentication/quality smoke, and verify no acknowledged data/work is lost. An incompatible backup or unknown rollback point is a stop condition, not a rebuild invitation.

Monitor readiness transitions, all HTTP status classes/429s, queue/admitted/generation utilization, p50/p95/p99/cold latency, timeouts/cancel/drain, process memory/CPU/disk, privacy-safe log health, claim/citation failures, quality drift and dependency advisories. Define owners/alerts on the actual platform; none deployed here.

## Completed repository publication (not deployment)

Source and reports were normally pushed on the same branch at `d4f613b85ba189fe8e716d8a0c833c4c9102348f`. Remote Git/GitHub API identity and rollback ancestry agree; see `release/evidence/publication-receipt.json`. A receipt-only descendant does not change runtime. The final delivery SHA is independently checked after pushing that receipt. Repository publication is PASS; actual production activation and rollback remain BLOCKED and were not attempted.
