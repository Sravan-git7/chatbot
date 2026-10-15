> **2026-10-15 closure follow-up — NOT READY.** The assessment below is the published `a027cd64` record, not the latest result. See [RELEASE_BLOCKER_CLOSURE.md](RELEASE_BLOCKER_CLOSURE.md) for the exhaustive current blocker classification, all61 independent failure reproductions, narrow fixes and external procedures. Tested source: `47e1e09aece4feb03aeae3abd06c5458b983ba07`; backend **7F/1330P/137S/49E +204 subtests**. All four Chroma advisories remain open. Frozen `phase12_results.json` reports38/65 and two wrong-page cases; the older37/65 narrative remains provenance-unreconciled, not a new run or baseline change. No production activation authorized.

# SURA security audit — 2026-10-15

**NOT READY. No security acceptance or deployment authorization is implied.** Runtime under review: `c324ffb366511b15385524aa8ed24e956f662780`. Python 3.11.2/Linux non-model test environment; actual production/Windows/model environments remain unavailable.

## Fixed, with regressions

- Readiness/startup exceptions no longer disclose model paths or raw exception payloads. Operator logs record exception **types**, not private messages.
- `SURA_PROFILE=production` requires a 32–256-character non-whitespace ASCII bearer secret and explicit non-wildcard allowed hosts. Debug, raw-query logging, experimental flags and wildcard CORS are rejected. App-argument overrides cannot bypass those checks. Invalid configuration fails closed even without ASGI lifespan startup.
- Non-loopback binding through the supported CLI requires the production profile; invalid configuration is rejected before Uvicorn listens. Default local profile remains loopback-only through that CLI. **An arbitrary external ASGI launcher can bypass CLI binding policy:** operations must enforce private binding/firewall and the production profile; configuration alone is not a network security boundary.
- Token comparison uses constant-time comparison; oversized credentials are rejected. Protected routes/static assets require bearer authentication. `/health` and `/ready` expose only sanitized operational readiness; CORS preflight is intentionally unauthenticated.
- Production ignores caller conversation IDs and uses request-scoped conversations, deleting their state in `finally`, including failures. Explicit UI context is still validated by the existing service. No cross-user history lookup or shared context cache was added.
- Production query fingerprints use a per-app secret HMAC, not dictionary-guessable unsalted hashes. Raw query logs remain opt-in only in the local profile. Production request IDs are server-generated. Backend secrets are never passed to the RAG prompt, logged, or placed in browser assets by this change.
- Received-body limits are checked **before** copying an oversized chunk. All middleware early errors receive no-store/privacy/security headers. IP rate-limit storage is bounded at 4096 buckets; expired buckets recover capacity; live capacity exhaustion returns 429, not unbounded growth.
- Production startup validates physical stored vector dimension/model identity against the loaded embedding contract, not counts/metadata alone. Real-SDK forged-shape failure and correct-fixture recovery pass; full model/corpus provenance still requires independent integrity gates.
- Explicitly owned Chroma clients are closed after draining, including partial construction failures. Failed close/stop paths are quarantined until process restart; no global cache clear/refcount reset or false cleanup success.

Evidence: `tests/test_release_runtime.py` (35 current tests), `tests/test_release_evaluation.py` (6), existing API/security/health/observability tests, and the full backend dispositions. Earlier focused API run: 92 passed/5 resource skips. Latest release-specific run: 41 passed. Full current suite has 7 failures/54 errors due to unavailable resources; it is not green.

## Fresh dependency scan

Evidence: `release/evidence/python-advisories.json`, `npm-audit-final.json`, `component-inventory.cdx.json`. Reviewed GitHub pip advisories queried via authenticated `gh api /advisories`, exact `affects=name@version` batches: 127 intended Linux lock packages plus 96 installed test packages, 136 distinct name/version queries. Frontend lock audit: **0 findings**, metadata covers 370 dependencies (110 prod, 261 dev, overlapping/optional classifications). This is not an OS/native or complete Windows advisory scan.

| Advisory | Severity / CVE | Chroma affected range; patch listed | Reachability and disposition |
|---|---|---|---|
| [GHSA-f4j7-r4q5-qw2c](https://github.com/advisories/GHSA-f4j7-r4q5-qw2c) | Critical / CVE-2026-45829 | >=1.0.0, <=1.5.9; none | Pre-auth HTTP collection creation can load attacker repository with remote-code trust. SURA exposes no Chroma collection-create HTTP endpoint. **Unresolved package advisory**, not an accepted risk. |
| [GHSA-36p7-vc44-83pf](https://github.com/advisories/GHSA-36p7-vc44-83pf) | Critical / CVE-2026-45833 | >=0.4.17, <=1.5.9; none | Chroma HTTP collection update permits malicious model configuration. SURA HTTP input only queries the fixed local corpus, not collection configuration. **Unresolved**, security-owner review required. |
| [GHSA-xph7-9rjv-w5fr](https://github.com/advisories/GHSA-xph7-9rjv-w5fr) | High / CVE-2026-45831 | >=0.5.0, <=1.5.9; none | Chroma server SimpleRBAC lacks resource scope enforcement. SURA uses local Rust PersistentClient, not SimpleRBAC/multitenant server authorization. **Unresolved package advisory**. |
| [GHSA-2wm9-hf6c-p5cr](https://github.com/advisories/GHSA-2wm9-hf6c-p5cr) | High / CVE-2026-45830 | >=0.4.17, <=1.5.9; none | Cross-tenant Chroma HTTP collection access. Those endpoints are not SURA routes. **Unresolved**; no separate Chroma server may be exposed. |

Source inspection: SURA creates local `PersistentClient` instances; owned wrappers accept fixed store/name settings, no remote embedding repository/trust setting from HTTP callers. No Chroma HTTP server was started. This supports a **currently absent HTTP attack path**, not blanket package clearance: imported native/server dependencies, malicious local stores/model packages, third-party embeddings and future architecture changes still require review. Store and model provenance/ACLs must be verified on the real target. Do not downgrade or choose an unlisted patch simply to hide findings. No authorized risk acceptance exists.

## Supply-chain and operational limits

- `requirements.lock.txt` is a **version lock**, not a hash/artifact lock. Its verified Linux closure is not the installed non-model test environment and not a Windows closure. The model wheel and native/OS dependencies were not installed/scanned here.
- CycloneDX inventory has 506 distinct component entries spanning intended Python, actual test Python and frontend locks. Scope properties explicitly distinguish them. It is **not** a production dependency-edge/native/OS SBOM or artifact attestation. Refresh against the actual approved target, verify package/model artifact hashes and provenance, and retain the resolved graph before promotion.
- Gateway must authenticate/authorize individual users (e.g. organization OIDC), strip caller-supplied backend credentials, inject the backend token server-side over private transport, enforce TLS and request/connection limits, and protect static assets. A shared backend bearer is **not** end-user identity, tenant/document ACLs, or proof of gateway deployment.
- No private multitenant corpus support is certified. Stateless requests stop guessed-ID history access, but do not implement document-level authorization.
- Uvicorn access/error logging and proxy logs must redact Authorization/cookies/body data; production error traces/core dumps need restricted access and retention. Verify this on the target; source-safe application logging does not certify third-party logs.
- Native CPU inference/retrieval is synchronous. Client disconnect does not guarantee immediate interruption of native work. Admission stays occupied until actual completion; queue and Ollama network deadlines exist, but there is no verified absolute full-pipeline cancellation/deadline contract. Real timeout/cancel/drain recovery is a release blocker, not a mock-certified success.

**Security closure owner:** security/operations. Required: real authenticated ingress/isolation proof, actual production/native/Windows graph scan, approved artifact provenance, disposition/authorized acceptance of each unresolved material advisory, and real cancellation/privacy/rollback verification. No exposure was performed.
