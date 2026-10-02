import json
import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = str(REPO_ROOT / "sap_pages")
OUTPUT_FILE = str(REPO_ROOT / "cleaned_pages.json")


def normalize_text(text):
    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Fix common extraction artifacts where inline elements were
    # separated by newlines.
    text = re.sub(r"(?<=\w)\n(?=\()", " ", text)
    text = re.sub(r"(?<=\))\n(?=\w)", " ", text)

    # Join obvious sentence/phrase continuations.
    # Do NOT blindly join every line because SAP lists/headings matter.
    lines = text.split("\n")
    output = []

    for raw in lines:
        line = raw.strip()

        if not line:
            if output and output[-1] != "":
                output.append("")
            continue

        # Remove repeated whitespace inside a line
        line = re.sub(r"[ \t]+", " ", line)

        # If the previous line clearly ends with a word and the current
        # line begins with a continuation rather than a new heading/list,
        # join them.
        if output and output[-1] != "":
            previous = output[-1]

            # Current line looks like a continuation.
            continuation = (
                not re.match(
                    r"^(Purpose|Use|Features|Activities|Integration|"
                    r"Structure|Example|Examples|Note|Notes|"
                    r"Prerequisites|Procedure|Result|Results|"
                    r"Business master data includes:|"
                    r"Technical master data includes:)$",
                    line,
                    re.IGNORECASE,
                )
                and not line.endswith(":")
                and not re.match(r"^[-•*]\s+", line)
            )

            # Previous line appears incomplete.
            previous_incomplete = (
                not previous.endswith((".", "!", "?", ":", ";"))
                and not previous.endswith(")")
            )

            # Avoid joining obvious short list items.
            previous_is_short = len(previous) < 80

            if continuation and previous_incomplete and previous_is_short:
                output[-1] = previous + " " + line
                continue

        output.append(line)

    text = "\n".join(output)

    # Remove accidental duplicate consecutive lines.
    lines = text.splitlines()
    cleaned = []

    for line in lines:
        line = line.strip()

        if not line:
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            continue

        if cleaned and line == cleaned[-1]:
            continue

        cleaned.append(line)

    # Collapse excessive blank lines.
    text = "\n".join(cleaned)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


pages = []

for filename in sorted(os.listdir(INPUT_DIR)):
    if not filename.endswith(".json"):
        continue

    path = os.path.join(INPUT_DIR, filename)

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    raw_text = data.get("text", "")
    cleaned_text = normalize_text(raw_text)

    if not cleaned_text:
        continue

    pages.append(
        {
            "title": data.get("title", ""),
            "url": data.get("source_url", ""),
            "text": cleaned_text,
        }
    )


with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(pages, f, ensure_ascii=False, indent=2)


sizes = [len(page["text"]) for page in pages]

print(f"Cleaned pages: {len(pages)}")

if sizes:
    print(f"Min chars: {min(sizes)}")
    print(f"Max chars: {max(sizes)}")
    print(f"Avg chars: {sum(sizes) // len(sizes)}")

print(f"Saved to: {OUTPUT_FILE}")
