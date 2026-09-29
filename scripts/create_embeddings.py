import json
import chromadb
from sentence_transformers import SentenceTransformer

INPUT_FILE = "chunks.json"
DB_DIR = "chroma_db"
COLLECTION_NAME = "sap_docs"

with open(INPUT_FILE, encoding="utf-8") as f:
    chunks = json.load(f)

print(f"Loaded {len(chunks)} chunks.")

print("Loading embedding model...")
model = SentenceTransformer("all-MiniLM-L6-v2")

client = chromadb.PersistentClient(path=DB_DIR)

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
        "embedding_model": "all-MiniLM-L6-v2"
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