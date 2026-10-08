# SURA Production Rollback Guide

## 1. Rollback Overview

This document describes how to safely roll back the SURA service in the event of an operational anomaly, latency regression, or pipeline issue.

Because SURA maintains a strictly stateless HTTP API and a read-only document corpus (`data/page_corpus` and `data/card_collection`), rollback operations are fast and low risk.

---

## 2. Fast Rollback via Feature Flags (Zero-Downtime)

If an anomaly is related to experimental pipeline behavior:
1. Ensure all experimental feature flags in `.env` are set to `0`:
   ```bash
   SURA_INTENT_AWARE=0
   SURA_SECTION_SELECTION=0
   SURA_ADDITIONAL_EVIDENCE=0
   ```
2. Restart or reload the FastAPI process:
   ```bash
   systemctl reload-or-restart sura
   ```
3. Verify `/ready` returns `HTTP 200`:
   ```bash
   curl -i http://localhost:8000/ready
   ```

---

## 3. Full Version Rollback Procedure

### Step 1: Switch Traffic / Update Symlink
If utilizing standard blue/green or symlink directory deployments:
```bash
# Switch current pointer to previous release
ln -sfn /opt/sura-releases/release-phase11 /opt/sura/current
systemctl restart sura
```

### Step 2: Container Rollback
If deploying via Docker / Kubernetes:
```bash
docker stop sura-production
docker run -d --name sura-production -p 8000:8000 --env-file /opt/sura/.env.production sura:phase11
```
Or with Kubernetes:
```bash
kubectl rollout undo deployment/sura-service
```

### Step 3: Verify Integrity & Health
1. Verify liveness:
   ```bash
   curl -f http://localhost:8000/health || exit 1
   ```
2. Verify readiness:
   ```bash
   curl -f http://localhost:8000/ready || exit 1
   ```
3. Run post-rollback probe query:
   ```bash
   curl -X POST http://localhost:8000/api/chat \
     -H "Content-Type: application/json" \
     -d '{"message": "How do I create an installment plan in SAP Utilities?"}'
   ```
   Confirm HTTP 200 with citations and grounded content.
