import json
import glob
import os

INPUT_DIR = "sap_pages"
OUTPUT_FILE = "processed_pages.json"

pages = []

for file in glob.glob(f"{INPUT_DIR}/*.json"):
    with open(file, encoding="utf-8") as f:
        data = json.load(f)

    text = data["text"].strip()

    if not text:
        continue

    pages.append({
        "title": data.get("title", ""),
        "url": data.get("url", ""),
        "text": text
    })

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(pages, f, ensure_ascii=False, indent=2)

print(f"Processed pages: {len(pages)}")
print(f"Saved to: {OUTPUT_FILE}")