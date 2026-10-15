# Chroma 1.5.9 advisory closure review

Date: 2026-10-15. **BLOCKED security acceptance; NOT READY.** No package upgrade/downgrade, exploit execution, Chroma HTTP server, remote model loading or production exposure was performed. This is source review and an inert local constructor-hook experiment, not a penetration test of a deployed target.

Fresh authoritative metadata: `gh api /advisories/<GHSA>` for each identifier below; exact responses are alongside this document. PyPI `https://pypi.org/pypi/chromadb/json` reports latest **1.5.9**. Every advisory lists `first_patched_version: null`. See `chroma-patch-availability.json`. No supported patched release is established by these sources; do not invent one, downgrade to evade a scanner, or upgrade without platform/lifecycle/quality compatibility testing.

| Identifier | Severity / affected versions | Vulnerable component and prerequisites | Reachability and safe mitigation / disposition |
|---|---|---|---|
| [GHSA-f4j7-r4q5-qw2c](https://github.com/advisories/GHSA-f4j7-r4q5-qw2c), CVE-2026-45829 | Critical; >=1.0.0, <=1.5.9 | Python FastAPI v2 collection creation: `process_create_collection` calls `load_create_collection_configuration_from_json` **before** `sync_auth_request`. Known embedding-function config invokes `build_from_config`; sentence-transformer provider forwards primitive kwargs including `trust_remote_code` to `SentenceTransformer`. A malicious repository/configuration can execute model code. | SURA exposes chat, not this collection-management route, and uses explicit vectors. **Chroma's own authentication alone is not an adequate mitigation for this pre-auth ordering.** Independently deny collection-management ingress, do not run/expose Chroma HTTP, constrain egress/FS privileges and accept only approved immutable models/configuration. Actual target topology/provenance remain unverified; OPEN. |
| [GHSA-36p7-vc44-83pf](https://github.com/advisories/GHSA-36p7-vc44-83pf), CVE-2026-45833 | Critical; >=0.4.17, <=1.5.9 | Python v2 collection update: authorized `UPDATE_COLLECTION` precedes deserialization of `new_configuration`; the same embedding-function constructor path can load attacker-selected model code. | A permitted collection updater is not a safe model-code trust boundary. Independently prohibit config update routes/privileges, deny unapproved model repositories and validate local store/config provenance. No SURA HTTP request forwards collection configuration. Local SDK/configuration loading is still relevant; OPEN. |
| [GHSA-xph7-9rjv-w5fr](https://github.com/advisories/GHSA-xph7-9rjv-w5fr), CVE-2026-45831 | High; >=0.5.0, <=1.5.9 | `SimpleRBACAuthorizationProvider.authorize_or_raise(user, action, resource)` tests only user/action; resource is ignored. Its source explicitly states per-resource authorization is unsupported. | SURA does not configure this provider. Do not rely on it for tenant/database/collection isolation. Use independent authorization and separately isolated stores/processes/network boundaries; test cross-principal/tenant access on the actual deployment. A shared SURA gateway token is not tenant IAM. OPEN. |
| [GHSA-2wm9-hf6c-p5cr](https://github.com/advisories/GHSA-2wm9-hf6c-p5cr), CVE-2026-45830 | High; >=0.4.17, <=1.5.9 | Advisory reports missing authorization validation permitting authenticated cross-tenant collection read/write/update/delete. The advisory supplies **no vulnerable function or precise root patch**, so this review does not claim to have independently reproduced that full exploit or equate it solely with SimpleRBAC. | No SURA collection CRUD proxy or tenant API was found. Do not expose a shared Chroma server; deny collection CRUD, enforce independent resource ACLs and process/store isolation. Obtain target configuration and test tenant A credentials against tenant B across read/write/update/delete. Actual deployment proof and acceptance absent; OPEN. |

## Installed-source data flow, not an architectural exemption

Reviewed installed 1.5.9 modules:

- `chromadb/server/fastapi/__init__.py`: create v2 at ~803 (configuration loading ~822, authentication ~828); update v2 at ~925 (auth ~937, config ~946). v1 management paths also exist; don't restrict only one URL version.
- `chromadb/api/collection_configuration.py`: create config loads a registered embedding provider with `build_from_config`; the collection-config property uses a similar loader.
- `chromadb/utils/embedding_functions/sentence_transformer_embedding_function.py`: `build_from_config` forwards kwargs through its constructor to `SentenceTransformer`; primitive `True` passes its type checks.
- `chromadb/auth/simple_rbac_authz/__init__.py`: per-resource policy ignored.
- `chromadb/api/client.py` and `api/models/CollectionCommon.py`: collection lookup, explicit-vector reads/queries and configuration-property loading have distinct paths.

**The Rust client is not a blanket exemption.** `chroma_inert_probe.py` creates only an owned temporary fixture and registers an inert provider that records constructor calls. `chroma_inert_probe.json` proves:

1. Create-config deserialization constructs the provider with a `trust_remote_code: true` field.
2. A Rust `PersistentClient` collection's `.configuration` property also constructs the provider from persisted config.
3. In this exact fixture/version, `get_collection`, `get(... embeddings ...)` and explicit-vector `query` did **not** construct the provider.

No malicious repository, remote code, network or actual model was used. This proves a loading surface, not an end-to-end RCE exploit. SURA's query path uses fixed local stores, explicit query vectors and metadata/count reads, not the configuration property; source search found no Chroma HTTP-client/server constructor or HTTP-to-config forwarding in its application path. Offline validation utilities and any future/third-party SDK use must be reviewed independently. Operator-controlled store/model configuration can still cross the Python constructor boundary.

## Required security closure

Security/operations must inventory the **actual** running processes, listening interfaces, ingress allowlists, SDK/server/provider settings, package/native/OS/model artifact hashes, store ACLs and model/config provenance. Verify upstream fixes when available and rerun Windows lifecycle, full backend, strict quality and performance compatibility before adoption. Until then, document each mitigation's enforcement and residual risk and obtain explicit authorized acceptance where policy permits. No acceptance exists here. Lack of an observed SURA HTTP route does not close a package advisory, prove all deployment paths unreachable, or authorize exposure.
