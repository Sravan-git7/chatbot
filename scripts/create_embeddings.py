"""Embed chunks.json and (re)build the ChromaDB collection.

Run from anywhere: python scripts/create_embeddings.py

Note: the collection is created with ChromaDB's default distance (squared L2).
Embeddings are normalized, so distance = 2 - 2 * cosine_similarity.  Retrieval
thresholds in rag_core.py are tuned to that; do not switch the space without
re-checking MAX_DISTANCE.
"""

import json

import chromadb
from sentence_transformers import SentenceTransformer

from rag_core import COLLECTION_NAME, DB_DIR, EMBEDDING_MODEL_NAME, REPO_ROOT

INPUT_FILE = REPO_ROOT / "chunks.json"

if not INPUT_FILE.exists():
    raise SystemExit(
        f"{INPUT_FILE} not found. Run scripts/clean_sap_pages.py and "
        "scripts/chunk_pages.py first."
    )

with open(INPUT_FILE, encoding="utf-8") as f:
    chunks = json.load(f)

print(f"Loaded {len(chunks)} chunks.")

print("Loading embedding model...")
model = SentenceTransformer(EMBEDDING_MODEL_NAME)

client = chromadb.PersistentClient(path=str(DB_DIR))

# Always recreate the collection so stale embeddings cannot remain.
try:
    client.delete_collection(COLLECTION_NAME)
    print(f"Deleted existing collection: {COLLECTION_NAME}")
except Exception:
    print("No existing collection found.")

collection = client.create_collection(
    name=COLLECTION_NAME,
    metadata={
        "description": "SAP S/4HANA Utilities documentation",
        "embedding_model": EMBEDDING_MODEL_NAME
    }
)

texts = [x["text"] for x in chunks]

ids = [f"chunk_{i}" for i in range(len(chunks))]

metadatas = [
    {
        "title": x.get("title", ""),
        "url": x.get("url", "")
    }
    for x in chunks
]

print(f"Creating embeddings for {len(texts)} chunks...")

embeddings = model.encode(
    texts,
    show_progress_bar=True,
    normalize_embeddings=True
).tolist()

collection.add(
    ids=ids,
    documents=texts,
    embeddings=embeddings,
    metadatas=metadatas
)

print()
print("Done.")
print("Stored:", collection.count())
print("Expected:", len(chunks))