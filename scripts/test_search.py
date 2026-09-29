import chromadb
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")

client = chromadb.PersistentClient(path="chroma_db")
collection = client.get_collection("sap_docs")

query = input("Ask: ")

embedding = model.encode([query]).tolist()

results = collection.query(
    query_embeddings=embedding,
    n_results=5
)

for i, doc in enumerate(results["documents"][0]):
    print(f"\n--- Result {i+1} ---")
    print(doc)