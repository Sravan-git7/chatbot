#!/usr/bin/env python3
"""Phase 11.1 - FRESH holdout question set (AI-authored, written and frozen BEFORE any Phase 11.1 candidate code or evaluation existed).

Same record schema as the Phase 10 sets (so ``phase10_lib`` scoring applies). Gold evidence quotes are verbatim page text and are validated to lie inside ONE chunk;
absent-detail terms are validated NOT to occur in the page text; overlap with every earlier question set is checked. The script refuses to run twice: a frozen set is not rewritten.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

OUT = ROOT / "data/evaluation/phase11_1_holdout_questions.json"
FREEZE = ROOT / "data/evaluation/phase11_1_holdout_freeze.json"
AUTHORSHIP = ("AI coding assistant (not blind; not a domain expert; had read the 7-page corpus text and the Phase 11 E2E failure analysis; "
              "written 2026-10-01 before any Phase 11.1 candidate code existed; NOT human-labelled)")

PAGES = {  # card -> (doc_id, ingested page title)
    "M2C-07": "2ac7fe29a0c94cdd88fb80c2cb9f7758/4d76765c1e012b8ae10000000a42189b",
    "M2C-05": "2ac7fe29a0c94cdd88fb80c2cb9f7758/8990d0533f8e4308e10000000a174cb4",
    "M2C-24": "9442486404b54071b4ebeab6a16628e7/790dc5536a51204be10000000a174cb4",
    "M2C-14": "a003b275c98148ee8a4c3fafe9588fe3/cc7bce53118d4308e10000000a174cb4",
    "M2C-17": "e52c8ee6197147ec97dfc2eb8c46a3ad/0bfcc5536a51204be10000000a174cb4",
    "M2C-11": "ed84b70c199d4470ae2e5ccb93b2e45b/147bce53118d4308e10000000a174cb4",
    "M2C-02": "f4a255a5de524e3992155767996fb1fd/8082ce53118d4308e10000000a174cb4",
}

# (card, facet, question, evidence quote)
ANSWERABLE = [
    ("M2C-07", "natural", "Which transaction gives an overview of the devices of a meter reading unit?", "get an overview of the devices of a meter reading unit"),
    ("M2C-07", "natural", "What does transaction EL32 do?", "monitor meter reading data and trigger automatic follow-on processing for selected meter reading orders"),
    ("M2C-07", "paraphrase", "Where can I see which meter reading documents were posted or failed after an IDoc upload?", "display the successfully and unsuccessfully posted meter reading documents after uploading discrete meter reading data"),
    ("M2C-07", "detail", "Which business function has to be active before I can request on-demand meter readings?", "you have activated the business function Advanced Metering Infrastructure ( ISU_AMI_1 )"),
    ("M2C-07", "detail", "What is the prerequisite for carrying out quantity determination from the meter reading result list?", "you have activated the business function Utilities, Quantity Determination ( ISU_QD_1 )"),
    ("M2C-07", "natural", "What can I do from the meter reading orders list when devices have orders?", "navigate to the AMI monitor for one or more orders"),
    ("M2C-07", "keyword", "meter reading monitoring selection criteria objects", "The objects that you can monitor using these selection criteria are marked with x in each row"),
    ("M2C-07", "detail", "Where in Customizing is the automatic monitoring of meter reading data set up?", "Customizing for SAP Utilities > Device Management > Meter Reading > Basic Settings > Automatic Monitoring of Meter Reading Data"),
    ("M2C-05", "detail", "Which standard component does a device in IS-U correspond to?", "Name in IS-U: Device; From Component: Plant Maintenance (PM); Name in Standard System: Equipment"),
    ("M2C-05", "natural", "How is a device number created?", "The device number is created in MM with the Goods Receipt function and transferred to the device"),
    ("M2C-05", "paraphrase", "How do you tell one device from another with the same serial number?", "The device is identified by a unique material and serial number combination"),
    ("M2C-05", "natural", "When are equipment records created in device management?", "Equipment records are created automatically during goods receipt"),
    ("M2C-05", "detail", "Which component covers purchase requisitions and purchase orders in the device flow?", "Function: Procurement; Component: Purchase Requisition and Purchase Order from Purchasing (MM-PUR)"),
    ("M2C-05", "keyword", "device category logistics basic data material", "Name in IS-U: Device Category; From Component: Logistics Basic Data (LO-MD); Name in Standard System: Material"),
    ("M2C-24", "natural", "What is the Clrg Priority indicator for?", "To be able to prioritize the clearing of original items when payments are received, you set the Clrg Priority indicator"),
    ("M2C-24", "natural", "What happens when I calculate interest on an installment plan?", "When you calculate interest, the system creates an interest document automatically"),
    ("M2C-24", "detail", "Which fields does the system copy from the original item into a new installment plan?", "the system copies the company code, contract, business area, and business place from the original item"),
    ("M2C-24", "detail", "How can I change the values that are copied into the installment plan, for example the business place?", "you can do this by defining event 3000 accordingly"),
    ("M2C-24", "natural", "How is the number of installments determined?", "The installment amount and the total sum of the source items determine the number of installments"),
    ("M2C-24", "paraphrase", "What does the start date mean in an installment plan?", "The start date defines the due date of the first installment"),
    ("M2C-24", "natural", "What changes can I make in the installment plan proposal?", "An Installment Plan Proposal appears, in which you can make the following changes"),
    ("M2C-24", "natural", "What does the Distribute indicator do?", "If you set the Distribute indicator, the interest and charges are distributed over all of the due dates"),
    ("M2C-24", "paraphrase", "Where can the remaining amount of an installment plan end up?", "specify whether this remaining amount is to be included in the first or last installment, or in a new installment"),
    ("M2C-24", "detail", "What is the relationship between installment amount, number of installments, remaining amount and the original receivable?", "installment amount * number of installments + remaining amount = total of original receivable"),
    ("M2C-24", "keyword", "FPR1 installment plan", "Create (transaction FPR1 )"),
    ("M2C-14", "natural", "What does invoicing with bill creation result in?", "Invoicing with Bill Creation results in a print document and a contract accounting document"),
    ("M2C-14", "yes_no", "Is it possible to print a bill again?", "It is possible to reprint bills"),
    ("M2C-14", "natural", "Which function do I use to process incorrect bills that were already updated in FI-CA?", "you must process them using the Bill Reversal function"),
    ("M2C-14", "paraphrase", "How are the contracts of one contract account treated in invoicing?", "The contracts of a contract account are grouped together in invoicing for the joint bill"),
    ("M2C-14", "natural", "When do postings take place for a consumption bill that was outsorted?", "Postings do not take place until the bill is released using the Outsorting function"),
    ("M2C-14", "natural", "Where are budget billing amounts managed?", "you manage these in the Budget Billing Plan component"),
    ("M2C-17", "yes_no", "Can a single contract account be assigned to more than one business partner?", "a single contract account can be assigned to more than one business partner"),
    ("M2C-17", "natural", "Where does contract account master data normally come from?", "Contract account master data is usually created and changed from the operational system using an interface"),
    ("M2C-17", "natural", "In Utilities, what does one contract account contain?", "one contract account contains all those contracts belonging to one business partner for which the same payment and dunning terms apply"),
    ("M2C-11", "natural", "What happens in billing when a price changes during a billing period?", "a price change causes the system to divide the total period into subperiods"),
    ("M2C-11", "natural", "What is calculated during schema execution?", "All calculations required for rate creation are made during schema execution"),
    ("M2C-02", "natural", "Which activities can the system trigger automatically during a move-out?", "create a final bill for the move-out customer"),
    ("M2C-02", "detail", "Which component is used to create welcome letters and move-out confirmations?", "Letters to the customer, such as welcome letters and move-out confirmations are created using the Print Workbench component"),
    ("M2C-02", "paraphrase", "What happens to the installation when a new customer moves in?", "the installation is allocated to this customer"),
    ("M2C-02", "detail", "Which component lets me monitor and configure the workflow processes for move-in and move-out?", "The SAP Business Workflow component (BC-BMT-WFM) enables you to monitor and configure the workflow processes"),
]
# (card, facet, question, absent terms that must not occur in the page text)
ABSENT = [
    ("M2C-24", "numeric", "What is the maximum number of installments allowed in an installment plan?", ["maximum"]),
    ("M2C-24", "numeric", "What interest rate does the system apply to an installment plan?", ["interest rate"]),
    ("M2C-24", "detail", "What fee is charged for setting up an installment plan?", ["fee"]),
    ("M2C-24", "detail", "In which currency are installment plans calculated?", ["currency"]),
    ("M2C-07", "detail", "Which authorization do I need to run the automatic monitoring transaction EL32?", ["authorization"]),
    ("M2C-07", "numeric", "How many meter reading results can the monitoring list display at most?", ["at most", "maximum"]),
    ("M2C-05", "detail", "What is the typical lifetime of a device?", ["lifetime"]),
    ("M2C-02", "numeric", "How many days does a move-out take to complete?", ["days"]),
    ("M2C-02", "numeric", "What is the minimum contract duration before a move-out is allowed?", ["minimum", "duration"]),
    ("M2C-17", "numeric", "What is the largest number of characters a contract account number can have?", ["characters"]),
    ("M2C-17", "detail", "What is the transaction code to create a contract account?", ["transaction code"]),
    ("M2C-17", "numeric", "For how many years are changes to the master data logged?", ["years"]),
    ("M2C-11", "detail", "What tax rate does billing apply?", ["tax"]),
    ("M2C-14", "detail", "Which transaction code is used to reverse a bill?", ["transaction"]),
    ("M2C-14", "numeric", "How many days does a customer have to pay a bill after invoicing?", ["days"]),
]
NOT_INGESTED = [
    ("M2C-20", "How does clearing control work for incoming payments?"), ("M2C-21", "Which clearing types exist?"), ("M2C-29", "How do I disconnect a utility installation?"),
    ("M2C-22", "How are payments from an external cash desk processed?"), ("M2C-12", "How does automatic billing work?"), ("M2C-08", "How is a missing meter reading estimated?"),
    ("M2C-25", "How do I display or change an existing installment plan?"),
]
UNRESOLVED = [("M2C-16", "How do I analyse periodic billing and invoicing?"), ("M2C-13", "How do I create a budget billing plan?"), ("M2C-18", "What does the contract account business object contain?")]
OUT_OF_DOMAIN = ["What is the capital of France?", "How do I reset my email password?", "Write a Python function that sorts a list.", "What time is it in Tokyo right now?",
                 "Recommend a good restaurant in Hyderabad.", "Who won the last cricket world cup?", "How do I configure SAP Fiori launchpad tiles?"]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def toks(s: str) -> set:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def main() -> int:
    if OUT.exists() or FREEZE.exists():
        print("STOP: the Phase 11.1 holdout is frozen; refusing to rewrite it", file=sys.stderr)
        return 2
    import page_retriever as PR  # noqa: F401  (chunk text comes from the page store through the retriever)
    import build_page_collection as BP
    embed, _ = BP.load_embedder()
    retriever = PR.PageRetriever.from_store(embed=embed)
    queries, n = [], 0

    def add(card, typ, facet, q, **kw):
        nonlocal n
        n += 1
        rec = {"id": f"P111H-{n:03d}", "authorship": AUTHORSHIP, "authored_phase": "11.1", "authored_on": "2026-10-01", "query": q, "type": typ, "facet": facet, "gold_source_id": card,
               "gold_doc_id": PAGES.get(card), "acceptable_source_ids": [], "evidence": [], "expected_status": None, "notes": ""}
        rec.update(kw)
        queries.append(rec)

    problems = []
    page_text = {}
    for card, doc in PAGES.items():
        g, p = doc.split("/")
        chunks = retriever.page_chunks(g, p)
        page_text[card] = (chunks, norm(" ".join(c.text for c in chunks)))
    for card, facet, q, ev in ANSWERABLE:
        chunks, _ = page_text[card]
        if not any(norm(ev) in norm(c.text) for c in chunks):
            problems.append(f"evidence not inside one chunk of {card}: {ev!r}")
        add(card, "answerable", facet, q, answerability="answerable_from_local_page", evidence=[ev], expected_status="answered")
    for card, facet, q, absent in ABSENT:
        text = page_text[card][1]
        for a in absent:
            if norm(a) in text:
                problems.append(f"absent term {a!r} occurs in the {card} page: {q}")
        add(card, "absent_detail", facet, q, answerability="not_answerable_detail_absent_from_page", absent_terms=absent, expected_status="insufficient_context", notes="topic is on the page, the asked detail is not")
    for card, q in NOT_INGESTED:
        add(card, "not_ingested", "natural", q, answerability="not_answerable_page_not_in_local_corpus", gold_doc_id=None, expected_status="page_not_ingested")
    for card, q in UNRESOLVED:
        add(card, "unresolved_identity", "natural", q, answerability="not_answerable_identity_unresolved", gold_doc_id=None, expected_status="unresolved_identity")
    for q in OUT_OF_DOMAIN:
        add(None, "out_of_domain", "natural", q, answerability="out_of_domain", gold_doc_id=None, expected_status="out_of_domain")

    # overlap with every earlier question set (exact normalised match or token Jaccard >= 0.8)
    prior = []
    for f in ("phase8_queries", "phase9_queries", "phase10_dev_queries", "phase10_test_queries"):
        prior += [x["query"] for x in json.loads((ROOT / f"data/evaluation/{f}.json").read_text(encoding="utf-8"))["queries"]]
    prior += [x["question"] for x in json.loads((ROOT / "data/evaluation/phase11_e2e_questions.json").read_text(encoding="utf-8"))["questions"]]
    for x in queries:
        for p in prior:
            a, b = toks(x["query"]), toks(p)
            if norm(x["query"]) == norm(p) or len(a & b) / max(1, len(a | b)) >= 0.8:
                problems.append(f"overlaps an earlier question: {x['query']!r} ~ {p!r}")
    seen = [norm(x["query"]) for x in queries]
    if len(set(seen)) != len(seen):
        problems.append("duplicate questions inside the set")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    counts = {}
    for x in queries:
        counts[x["type"]] = counts.get(x["type"], 0) + 1
    payload = {"schema_version": 1, "description": "Phase 11.1 fresh holdout (frozen before candidate code/evaluation)", "authorship": AUTHORSHIP, "counts": counts, "total": len(queries),
               "corpus_sha256": json.loads((ROOT / "data/page_corpus/manifest.json").read_text(encoding="utf-8"))["corpus_sha256"], "queries": queries}
    text = json.dumps(payload, indent=1, ensure_ascii=False) + "\n"
    OUT.write_text(text, encoding="utf-8")
    FREEZE.write_text(json.dumps({"file": OUT.name, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "total": len(queries), "counts": counts,
                                  "frozen_before": "any Phase 11.1 candidate code or evaluation"}, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(counts), len(queries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
