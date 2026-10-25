# SURA Staging Deployment Bundle — Fast-Track

## What this bundle is
Minimal reproducible Docker deployment for the SURA RAG API + frontend, with persistent vector-store mount and HTTPS reverse proxy. Uses the repository's existing supported configuration model (validated via `scripts/rag_api.validate_configuration()` and `SURA_CARD_VECTOR_DIR`/`SURA_PAGE_VECTOR_DIR` with fail-closed startup). No secrets are baked into images.

## Files
- `Dockerfile` — multi-stage: Node 20.19.3 frontend builder + Python 3.11.9 runtime with `requirements.lock.txt` (141 pins). No vector stores baked in; `VOLUME /app/data/vector_store`.
- `.dockerignore` — excludes `.env`, `data/vector_store/`, `chroma_db/`, `scratch/`, secrets, `node_modules`, generated benchmarks, OS files.
- `docker-compose.yml` — `api` (private, `expose: 8000`, internal network only) + `proxy` (nginx 1.27.3 TLS, `ports 443/80`, injects `Authorization: Bearer` server-side). Vector store is external `sura_vector_store` volume (read-only).
- `deploy/nginx.conf` — TLS, `client_max_body_size 16k`, security headers, `/health` + `/ready` liveness/readiness, `/api/` proxy with `X-Request-Id`.
- `secrets/README.md` — token generation (64-char example), external secret-manager guidance.

## Prerequisites (sole blocking gate)
The approved persistent store snapshot is **missing** in this sandbox (`data/vector_store/chroma.sqlite3` absent, protected, never accessed). Staging cannot be provisioned until the owner supplies a quiesced snapshot with byte hashes:

- Expected fingerprint: `corpus_sha256 46e7c63af630de1a99f924320092b3bce4e29751add1eb3177b357cabd136008`, 29 cards (28 ingested + M2C-18 `excluded_conflicting_identity`), 113 chunks (28 pages), model `all-MiniLM-L6-v2` `53aa5117…`, 384 dims, cosine.
- Provisioning: `docker volume create sura_vector_store && tar -xzf sura-vector-store-<sha>.tar.gz -C $(docker volume inspect sura_vector_store --format '{{.Mountpoint}}') && verify counts/fingerprint.`

Other hosts: no Docker/SSH/cloud/registry/DNS/secret-manager integration is available in this sandbox (`which docker` not found, `env` shows no cloud creds). Bundle is ready; deployment will run on any host with Docker 24+.

## Deploy (authorized host only)

```bash
# 1. Host setup
SURA_ALLOWED_HOSTS=sura-staging.example.com
RAG_CORS_ORIGINS=https://sura-staging.example.com   # or empty for same-origin only
export SURA_IMAGE_TAG=c02e908   # git SHA — rollback by re-tagging previous SHA
docker volume create sura_vector_store
# Restore approved snapshot (owner-supplied) into volume mountpoint, verify fingerprint
python3 -c "import secrets, string; print(''.join(secrets.choice(string.ascii_letters+string.digits+'-_.') for _ in range(64)))" > secrets/sura_api_token.txt
chmod 600 secrets/sura_api_token.txt
# TLS certs: place fullchain + key as deploy/certs/tls.crt + tls.key (or use LB-managed TLS)

# 2. Build (pinned)
docker compose build --no-cache
docker images sura-rag:c02e908 --digests  # record image digest + SBOM for rollback

# 3. Deploy
SURA_ALLOWED_HOSTS=$SURA_ALLOWED_HOSTS RAG_CORS_ORIGINS=$RAG_CORS_ORIGINS docker compose up -d
docker compose ps

# 4. Validate staging (private, via proxy host)
curl -fsS https://sura-staging.example.com/health     # 200 {status: ok, process: live}
curl -fsS https://sura-staging.example.com/ready      # 200 {ready: true, topics: 29, pages_available: 28} or 503 with reason — gate traffic on this
curl -fsS https://sura-staging.example.com/api/health # UI-facing

# 5. Smoke against remote service (authenticated via proxy IdP)
./scripts/staging_smoke.sh https://sura-staging.example.com   # 9 cases: EL43, ELDM, device-number, EL31 abstain, empty 422, cake OOD, comparison, followup, injection
docker compose logs api --tail 100 | grep -i "error\|missing store\|fallback"  # must show no fallback, no secret leak

# 6. Benchmark against staging index
python benchmarks/run_quality.py --source-commit c02e908 --card-vector-dir /app/data/vector_store --page-vector-dir /app/data/vector_store/page_collection
# Require: Recall@1 >=0.89, wrong_page 0, abstention preserved; compare to isolated 0.938 (61/65) baseline

# 7. Rollback
docker compose down
docker tag sura-rag:previous-stable sura-rag:rollback && docker compose up -d
# Previous image digest + volume snapshot retained
```

## Why /api points to deployed service, not localhost
Frontend `web/dist` is served by FastAPI (`RAG_STATIC_DIR=/app/web/dist`) and makes relative `/api/...` calls. No `VITE_BACKEND_URL` is baked; production CORS defaults to `[]` (no implicit localhost). Nginx proxies all paths to the private `api:8000`.

## Security
- API never exposed publicly; only proxy publishes 443/80.
- `SURA_PROFILE=production` requires non-wildcard `SURA_ALLOWED_HOSTS`, `RAG_CORS_ORIGINS` explicit, `RAG_CSP_FRAME_ANCESTORS='none'`, `RAG_ENABLE_DEBUG=0`, `SURA_LOG_QUERIES=0`, experimental flags 0 — validated at startup (fail-closed 503).
- Token via Docker secret `sura_api_token` (file or external), never in image, logs, or report.
- `TrustedHostMiddleware` enforced when `allowed_hosts` set; `CORSMiddleware` `allow_credentials False`.

## Rollback
Images tagged by git SHA + digest; compose `image: sura-rag:${SURA_IMAGE_TAG}`. Keep previous image + volume snapshot. Rollback is `docker compose down` + tag previous digest + `up -d` + re-run `/ready` + smoke. Never `git reset --hard` or overwrite live store.
