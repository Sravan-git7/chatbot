# Private isolation, capacity, restore and rollback rehearsal

**PLAN ONLY — NOT EXECUTED / NOT APPROVED.** Never run this against production, expose a public endpoint/preview, migrate/repair/replace a live store or activate a release. No services were launched for this package. The service-manager/gateway/backup system and deployed known-good release are unknown; an executable operations runbook must be supplied by their owners, not invented here.

## Mandatory preconditions and authority

Obtain a signed rehearsal ticket naming security authority, operations commander, storage/backup owner, IAM/browser owner, model/runtime owner, independent SAP reviewer and rollback/release approver; scope/time window/data permissions, allowed private hosts/ports/network/volumes, explicit private launch/failure-injection/restore approval and abort contact. Private-test approval is not production activation approval.

Before any runtime launch:

- Verified source/tested-runtime equality and frozen artifact preservation; approved complete model/runtime/native graph and six model pins; [cold-copy chain](COLD_COPY.md) completed with independent sealed backup and unused run path. No original/user/production tree mounted writable or opened via SDK. Native Windows testing uses an actual separate approved Windows host.
- Security has supplied actual target process/listener/route/provider/SDK/config/ACL/SBOM evidence and accepted the **private rehearsal containment** conditions for all five [OPEN advisories](SECURITY_DECISIONS.md). This does not close release security gates. No public ingress, Arena preview/server launch, direct Chroma HTTP exposure or unapproved egress. Non-admin service account, only owned fixture volumes, secret-manager injection, minimal trusted artifact/config provenance, private logs/monitoring.
- Supply actual known-good **deployed** rollback tuple: code/build, frontend, interpreter/packages/native libraries, model/digest, card/page/corpus/identity/config schemas, secret references, service/ingress config, storage snapshot and signed byte inventories. Demonstrate compatibility as a tuple. Ancestor `20cb6daa4c6cd4efd2c1d0ee117380101d843a5d` is only a repository rollback reference, **not proof it was deployed/healthy/safe or store-compatible**. Do not downgrade code onto a newly modified database.
- Owner supplies two independently addressable private principals/resources, intended authorization policy and synthetic known-positive/known-negative document/tenant/collection fixtures in separately owned trees. Define principal→resource mapping, allowed shared public SAP content, forbidden documents and expected status/side-effect for each route. Do not add synthetic evidence to frozen SAP data or relabel evaluations.
- The application's production bearer guard/stateless behavior is not by itself tenant/document ACL enforcement. If target policy needs isolation the application/gateway cannot demonstrate, the gate is BLOCKED; use separately reviewed process/storage boundaries or a separate approved implementation task, not a claim that conversation IDs provide isolation.
- Owner declares intended hardware, workload/rate/concurrency/queue limits, memory/disk budgets, latency/error/cancel/drain limits, RTO, RPO and acceptable recovery criteria **before** measurements. No fabricated universal thresholds or sandbox extrapolation.
- Provide reviewed exact private-only start/stop/drain/health/gateway/backup/restore/release-pointer commands, units/config IDs, secret references (not values) and evidence destinations. These target-specific commands are **unknown**, so the operations sequence below is deliberately not runnable automatically. Existing generic runtime commands are in [COMMANDS](COMMANDS.md).

Use new exported release bundles for candidate and known-good directories; never switch/create another Git branch, reset/clean a checkout or overwrite an existing tree. Any Git clone remains on `arena/b450cda2-chatbot`. Immutable historical code bundles may be supplied by owner-approved archives without branch changes.

## Sequence and retained evidence

### 1. Seal the starting point

Record ticket/owners, UTC/clock source, actual source SHA, hardware/OS/native graph, signed model/store/build/config inventories, private listeners/ACLs, gateway route rules and current **rehearsal-only** service/release pointer. Hash the complete approved cold export; verify sealed backup and independently restored unused run path before any SDK call. Retain source quiescence/snapshot/ACL attestations and all commands/exits/stdout/stderr. Abort on mismatch or unexpected existing destination. Immutable sealed/original trees are never SDK inputs.

### 2. Prove boundary isolation first

With synthetic fixtures and private auth ingress, exercise anonymous, principal A, principal B and privileged role; own/other/default tenant/database/collection/document, guessed/swapped IDs, sessions and conversation IDs. Cover every supported list/get/query/count/add/upsert/update/delete/create/get-or-create/config/admin operation and API version/direct route/alias/encoded-path bypass. For direct Chroma interfaces expected blocked/nonexistent routes must be verified along with absence of network bypass. Intended valid own-resource operations must succeed; unauthorized requests must fail with no data/metadata/embedding leakage or mutation.

Check no cross-user cache/history/debug/source leakage, correct per-request identity mapping, expiry/logout/session replay, ingress 401/403 behavior and server-side credential handling. Do not place a privileged backend token in browser assets/storage or report it. Use inert marker config only if specifically approved; never exploit/poison a production store. If any required identity/document policy cannot be enforced, stop; a shared SAP corpus does not by itself prove arbitrary tenant isolation.

### 3. Private runtime, browser and full semantic evidence

Only after boundary success, use the owned disposable candidate service. Run full backend/current strict extractive quality and native tests via [COMMANDS](COMMANDS.md); real local Ollama uses the approved digest without pull/fallback. Preserve raw request/answer/source/context/generator identity for independent SAP review, including M2C-18 fail-closed, list/payment/remaining procedure/polarity cases, all negatives and ambiguity. A successful five-workflow smoke does not replace full current-production real-model replay.

Use the installed supported browser on the private test host or approved private gateway. Verify principal/session isolation, source rendering/complete answers, keyboard-only navigation, focus restoration/live-region announcements, meaningful errors, axe/accessibility results, and 401/403/413/429/timeout/outage/cancel/recovery. Keep traces/screenshots/network evidence privately with approved redacted references; jsdom or a public proxy is not this test.

### 4. Failure/capacity/cancellation matrix

Run approved fixed workloads on intended hardware with pinned driver/argv/config and complete request accounting. Measure cold/warm HTTP and per-stage p50/p95/p99, throughput/RPS, queue/rate/rejection behavior, memory/CPU/handles/disk, model load/unload, cancellation and shutdown/drain. Include multiple legitimate private client identities/IPs if required; never evade rate limits in production. Count **every** reject, 429, error, timeout, unsupported/incorrect answer and cancellation; do not omit difficult requests or report only completed successful responses.

Against **owned test** daemon/network/service only, inject Ollama unavailable, bounded slow generation, cancellation while queued and generating, disconnect, saturated permits, drain during active work and restart. Assert finite failure, accurate error/status (not silent extractive fallback), no leaked permits/threads/handles, subsequent legitimate request success, source/version correctness and preserved identity isolation. Record all resource and cancel/drain evidence. A controlled outage result is not inference PASS.

### 5. Restore and rollback drill — independent new paths

1. On an approved **private rehearsal** source, stop/drain writers under owner control, record snapshot/quiescence and full byte inventory. Never stop production. Restore the signed cold backup to a **new unused path** with [COLD_COPY](COLD_COPY.md); verify every byte and associated model/corpus/config/release tuple before SDK access. Include WAL/SHM/HNSW as supplied; no repair/checkpoint to force success.
2. Prepare the known-good release tuple in a separate unused directory/process/storage root; do not share a writable store with candidate. Verify secrets by reference/authorization, not by disclosure. Record compatible schema/runtime/model/corpus identities and actual private readiness plus authenticated semantic/negative/isolation smoke.
3. Through owner-supplied **rehearsal-only** gateway/service-manager/release-pointer controls, direct private synthetic traffic to candidate. Inject candidate failed readiness and the approved failure condition; verify fail-closed routing, alerts and no acknowledged work silently lost. Do not route real customers.
4. Execute the reviewed rehearsal pointer/service rollback to the independent known-good tuple. Stop/drain candidate; wait for actual handle release with supported bounded owned lifecycle controls. Point old code only at its own compatible restored store/config/model, never at candidate-mutated storage. Verify authenticated substantive/source/version/negative/isolation behavior and no stale processes/writers/credentials/routes. Capture exact actual commands, pointer before/after, logs, exits and recovery timing.
5. Negative restore drill: corrupt **another owned disposable backup copy** or supply a mismatched inventory/schema/model tuple. Restoration/readiness must reject it **before SDK loading/traffic**. Preserve the sealed good backup and both prior trees; restore a new good copy and repeat verified recovery. No overwrite/delete of the corrupt fixture as a way to erase failure.
6. Measure actual RTO/RPO against values declared before testing; include time for artifact verification, startup/model readiness, semantic verification and pointer/gateway recovery. Rehash untouched sealed/source trees and original fixture/reference inventories. A byte match, Git ancestry or successful process start alone is not a restore/rollback PASS.

## Immediate abort criteria

Abort on unauthorized/public reachability, wrong host/path/owner, missing approval/fixture permission, source/backup hash drift, mixed generations, existing destination, active writer/unsupported cleanup, unexpected configuration/provider constructor, unknown model/digest/native graph, cross-identity data/config access, secret/PII leakage, wrong source/version factual answer, failed mandatory safe negative, unbounded cancel/permit/handle leak, failed readiness/health, missing logs or exceeded declared safety/resource/RTO/RPO limit.

On abort: stop admitting **private test traffic** through the approved test gateway; preserve logs/traces/failed owned trees and notify named security/operations owners. Use approved private stop/drain controls only; do not kill unrelated processes or reset global Chroma caches/refcounts. If safe, restore a **new** known-good tuple and roll back only the rehearsal pointer using the reviewed command sequence. If restore/readiness/cleanup fails, keep rehearsal ingress denied and escalate; no retry-overwrite, live repair, swallowed error or production fallback. Cleanup/deletion requires a separately scoped owner approval after evidence retention, not this plan.

## Success record and remaining authority

Require all input/source/backup inventories unchanged where intended; zero unauthorized data/config access and no secret/debug leakage; valid own-resource operations; all mandatory runtime/native/browser/cancel/restore assertions genuinely executed; independent substantive SAP/source/version/safe-negative gates; complete error/skip/warning accounting; capacity/RTO/RPO within declared limits; proven private rollback tuple/pointer and failed-restore rejection; signed security/operations/SAP/release evidence. Unsupported/missing facilities and skipped mandatory native checks are BLOCKED, not PASS.

Return signed ticket/runbook, exact commands/exits/timestamps, input/output inventories, full test/HTTP/browser/capacity/restore evidence, advisory dispositions, every unresolved issue and separate approvals. **A successful private rehearsal still does not authorize public exposure, production migration, store replacement or candidate activation. Overall NOT READY until every mandatory gate and release approval closes.**
