import chromadb
from sentence_transformers import SentenceTransformer


DB_DIR = "chroma_db"
COLLECTION_NAME = "sap_docs"

TOP_K = 5


print("Loading embedding model...")
model = SentenceTransformer("all-MiniLM-L6-v2")

print("Loading ChromaDB...")
client = chromadb.PersistentClient(path=DB_DIR)
collection = client.get_collection(COLLECTION_NAME)

print(f"Collection contains {collection.count()} chunks.")


def search(query, top_k=TOP_K):
    query_embedding = model.encode([query]).tolist()

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=top_k
    )

    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    print("\n" + "=" * 80)
    print(f"QUERY: {query}")
    print("=" * 80)

    for i, (doc, metadata, distance) in enumerate(
        zip(documents, metadatas, distances),
        start=1
    ):
        print(f"\n--- Result {i} ---")
        print(f"Title: {metadata.get('title', 'Unknown')}")
        print(f"Distance: {distance}")
        print(f"URL: {metadata.get('url', '')}")
        print("\n" + doc[:1500])


questions = [
    "What is master data?",
    "What are the two types of master data?",
    "What is a contract account?",
    "What is a business partner?",
    "What is a point of delivery?",
    "How are contract accounts assigned to business partners?",
    "How can a business partner be blocked?",
    "How is payment data changed?",
]


for question in questions:
    search(question)