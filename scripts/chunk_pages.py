import json
import re

INPUT_FILE = "cleaned_pages.json"
OUTPUT_FILE = "chunks.json"

with open(INPUT_FILE, encoding="utf-8") as f:
    pages = json.load(f)

chunks = []

for page in pages:
    text = page["text"]

    # Split roughly by paragraphs/sentences
    parts = re.split(r"\n\s*\n|(?<=[.!?])\s+", text)

    current = ""

    for part in parts:
        part = part.strip()

        if not part:
            continue

        if len(current) + len(part) <= 1000:
            current += " " + part
        else:
            if current.strip():
                chunks.append({
                    "title": page["title"],
                    "url": page["url"],
                    "text": current.strip()
                })

            current = part

    if current.strip():
        chunks.append({
            "title": page["title"],
            "url": page["url"],
            "text": current.strip()
        })

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(chunks, f, ensure_ascii=False, indent=2)

print(f"Pages: {len(pages)}")
print(f"Chunks: {len(chunks)}")
print(f"Saved to: {OUTPUT_FILE}")