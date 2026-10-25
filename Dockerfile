# SURA SAP Utilities RAG — Multi-stage Docker build
# Stage 1: build frontend (pinned Node, reproducible npm ci)
# Stage 2: runtime API (pinned Python 3.11 + locked dependencies)

# --- Frontend builder ---
FROM node:20.19.3-alpine AS web-builder
WORKDIR /app/web
# Only dependency manifests first for layer caching
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts
COPY web/ ./
RUN npm run build

# --- Runtime ---
FROM python:3.11.9-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    ANONYMIZED_TELEMETRY=False

WORKDIR /app

# System deps for chromadb/sentence-transformers (sqlite, libgomp)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 sqlite3 curl \
 && rm -rf /var/lib/apt/lists/*

# Locked Python dependencies — pin exact versions; rollback by image tag
COPY requirements.lock.txt ./
RUN pip install --upgrade pip && \
    pip install -r requirements.lock.txt

# Application code and approved corpus (no vector stores, no secrets)
COPY scripts/ ./scripts/
COPY data/page_corpus/ ./data/page_corpus/
COPY data/source_corpus.json data/source_manifest.json data/topic_manifest.json data/m2c_page_identity.json data/card_collection_manifest.json data/page_collection_manifest.json ./data/
COPY data/page_corpus/ ./data/page_corpus/
COPY data/source_manifest.json ./data/source_manifest.json
COPY data/source_corpus.json ./data/source_corpus.json
# Minimal TOC/manifests needed for identity checks (not full sap_help pages)
COPY data/toc/ ./data/toc/
COPY data/guide_registrations.json ./data/guide_registrations.json
# Frontend build artifact from previous stage
COPY --from=web-builder /app/web/dist ./web/dist

# Non-root user
RUN useradd -m -u 10001 sura && chown -R sura:sura /app
USER sura

# Vector stores are NOT baked into the image — mounted at runtime
# Expected mounts: /app/data/vector_store and /app/data/vector_store/page_collection (read-only)
VOLUME ["/app/data/vector_store"]

ENV SURA_PROFILE=production \
    RAG_GENERATOR=extractive \
    HOST=0.0.0.0 \
    PORT=8000 \
    RAG_STATIC_DIR=/app/web/dist
# SURA_CARD_VECTOR_DIR and SURA_PAGE_VECTOR_DIR must be set at runtime to the mounted paths.
# Startup fails closed (503) if the mounted stores are missing — no silent fallback.
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["python", "-m", "uvicorn", "scripts.rag_api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
