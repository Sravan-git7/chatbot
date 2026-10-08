# SURA Operational Troubleshooting Guide

This guide provides diagnosis and remediation procedures for common operational issues in SURA.

---

## 1. Readiness Probe Failing (`HTTP 503` on `/ready`)

### Symptoms
- Load balancer reports unhealthy instance.
- Requests to `/ready` return:
  ```json
  {"error": {"code": "service_not_ready", "message": "Corpus index is empty or unavailable.", "request_id": "..."}}
  ```

### Diagnosis
1. Check whether `data/page_corpus/manifest.json` and `data/card_collection/` exist.
2. Verify file permissions: the process user must have read access to `data/`.
3. If using `RAG_GENERATOR=ollama`, check whether Ollama is running (`curl http://localhost:11434/api/tags`) and model `llama3.2:3b` is pulled.

### Resolution
- Run corpus verification:
  ```bash
  python -m pytest tests/test_health_ready.py
  ```
- If files are missing, inspect data directory structure or restore from release artifacts.

---

## 2. HTTP 429 Too Many Requests

### Symptoms
- Client receives:
  ```json
  {"error": {"code": "rate_limited", "message": "Too many concurrent requests. Please retry shortly.", "request_id": "..."}}
  ```
  or
  ```json
  {"error": {"code": "rate_limited", "message": "Rate limit exceeded for this client IP. Please wait before retrying.", "request_id": "..."}}
  ```
- Header `Retry-After` is present (either `1` or `60`).

### Diagnosis
1. **Concurrency Saturated:** Max concurrency is set to 4 (`MAX_CONCURRENT_REQUESTS = 4`) to prevent CPU thread thrashing during SentenceTransformer embedding.
2. **Per-IP Rate Exceeded:** An individual IP address sent more requests than `SURA_RATE_LIMIT_PER_MINUTE` (default: 60/min).

### Resolution
- For high concurrency, add backend instances behind a round-robin load balancer.
- For legitimate heavy callers, increase `SURA_RATE_LIMIT_PER_MINUTE=120` in `.env`.

---

## 3. High Tail Latency (p95 > 100ms)

### Symptoms
- Responses take longer than expected; p95 latency spikes.

### Root Cause & Investigation
- On multi-core systems, PyTorch's default thread count for SentenceTransformer vector inference can introduce CPU context-switching overhead.
- Check structured log timings:
  ```json
  "latency_per_stage": {
    "embed_ms": 42.1,
    "chroma_ms": 7.4,
    "rerank_ms": 12.3,
    "context_ms": 6.1,
    "grounding_ms": 4.8
  }
  ```

### Resolution
- Ensure feature flags are kept OFF (`SURA_INTENT_AWARE=0`, `SURA_SECTION_SELECTION=0`, `SURA_ADDITIONAL_EVIDENCE=0`).
- Bound PyTorch thread allocation if necessary:
  ```bash
  export OMP_NUM_THREADS=4
  export MKL_NUM_THREADS=4
  ```

---

## 4. Grounding Violations / Abstentions

### Symptoms
- Status is `insufficient_evidence` or `unable_to_verify` instead of `answered`.

### Cause
- SURA strictly requires exact-citation support chains. If the query asks for concepts not explicitly described in the 25 ingested SAP Help pages, the engine intentionally abstains rather than synthesizing ungrounded claims.

### Resolution
- Confirm whether the question is covered by the 25 ingested pages. If the topic corresponds to an un-ingested topic (`M2C-01`, `M2C-13`, `M2C-16`, `M2C-18`), SURA honestly reports page unavailable and directs the user to the reference card.
