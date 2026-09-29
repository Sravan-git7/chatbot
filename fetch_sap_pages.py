import json
import time
import requests
from bs4 import BeautifulSoup
from pathlib import Path

DELIVERABLE_ID = "40374631"
BUILD_NO = "1779"

with open("master_data.json", encoding="utf-8") as f:
    data = json.load(f)

toc = data["data"]["deliverable"]["fullToc"]

pages = []

def walk(items, parent=""):
    for item in items:
        title = item.get("t", "")
        file_path = item.get("u", "")

        if file_path:
            pages.append({
                "title": title,
                "file_path": file_path,
                "parent": parent
            })

        walk(item.get("c", []), title)

walk(toc)

out = Path("sap_pages")
out.mkdir(exist_ok=True)

session = requests.Session()

for i, page in enumerate(pages, 1):
    print(f"[{i}/{len(pages)}] {page['title']}")

    url = (
        "https://help.sap.com/http.svc/pagecontent"
        f"?deliverableInfo=1"
        f"&deliverable_id={DELIVERABLE_ID}"
        f"&buildNo={BUILD_NO}"
        f"&file_path={page['file_path']}"
    )

    try:
        r = session.get(url, timeout=30)
        r.raise_for_status()

        data = r.json()
        body = data["data"]["body"]

        soup = BeautifulSoup(body, "html.parser")
        text = soup.get_text("\n", strip=True)

        result = {
            "title": page["title"],
            "parent": page["parent"],
            "file_path": page["file_path"],
            "source_url": (
                "https://help.sap.com/docs/"
                f"SAP_S4HANA_ON-PREMISE/"
                f"{DELIVERABLE_ID}/"
                f"{page['file_path']}"
            ),
            "current_page": data["data"].get("currentPage"),
            "text": text
        }

        with open(
            out / f"{i:03d}.json",
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    except Exception as e:
        print(f"  ERROR: {e}")

    time.sleep(2)

print(f"\nFinished. Saved {len(pages)} pages to {out}")