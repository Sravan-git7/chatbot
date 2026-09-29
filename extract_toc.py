import json

with open("master_data.json", encoding="utf-8") as f:
    data = json.load(f)

toc = data["data"]["deliverable"]["fullToc"]

def walk(items, level=0):
    for item in items:
        print("  " * level + item.get("t", "") + " | " + item.get("u", ""))
        walk(item.get("c", []), level + 1)

walk(toc)