import json
import glob

files = glob.glob("sap_pages/*.json")

lengths = []
empty = []

for f in files:
    with open(f, encoding="utf-8") as file:
        d = json.load(file)

    text = d.get("text", "")

    if text.strip():
        lengths.append(len(text))
    else:
        empty.append(f)

print("Pages:", len(files))
print("Min chars:", min(lengths))
print("Max chars:", max(lengths))
print("Avg chars:", sum(lengths) // len(lengths))
print("Empty:", len(empty))

if empty:
    print("\nEmpty files:")
    for f in empty:
        print(f)