#!/usr/bin/env python3
"""Phase 12 - FRESH end-to-end evaluation set (AI-authored; written and frozen BEFORE any Phase 12 retrieval/evaluation ran). Contract: ``data/phase12_contract.md`` section D.

Eleven categories (field ``category``), record ``type`` in the earlier schema (answerable, absent_detail, not_ingested, unresolved_identity, out_of_domain) plus ``ambiguous``.
Validation (any problem -> nothing is written): gold evidence lies inside ONE chunk of the gold page; absent-detail terms do not occur in the page text; no exact / token-Jaccard >= 0.8
overlap with the Phase 8/9/10/11.1 sets, the 16 E2E questions or inside this set. The script refuses to run twice: a frozen set is never rewritten.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

OUT = ROOT / "data/evaluation/phase12_queries.json"
FREEZE = ROOT / "data/evaluation/phase12_freeze.json"
AUTHORSHIP = ("AI coding assistant (not blind; not a domain expert; had read all 7 page texts and the Phase 11.1 results and failure analysis; written 2026-10-01 "
              "before any Phase 12 evaluation; NOT human-labelled)")

PAGES = {
    "M2C-07": "2ac7fe29a0c94cdd88fb80c2cb9f7758/4d76765c1e012b8ae10000000a42189b",
    "M2C-05": "2ac7fe29a0c94cdd88fb80c2cb9f7758/8990d0533f8e4308e10000000a174cb4",
    "M2C-24": "9442486404b54071b4ebeab6a16628e7/790dc5536a51204be10000000a174cb4",
    "M2C-14": "a003b275c98148ee8a4c3fafe9588fe3/cc7bce53118d4308e10000000a174cb4",
    "M2C-17": "e52c8ee6197147ec97dfc2eb8c46a3ad/0bfcc5536a51204be10000000a174cb4",
    "M2C-11": "ed84b70c199d4470ae2e5ccb93b2e45b/147bce53118d4308e10000000a174cb4",
    "M2C-02": "f4a255a5de524e3992155767996fb1fd/8082ce53118d4308e10000000a174cb4",
}

# (category, card, question, evidence quote)  -> type answerable
ANSWERABLE = [
    # 1 direct factual
    ("direct_factual", "M2C-07", "What is the purpose of transaction EL43?", "get an overview of the devices of a meter reading unit"),
    ("direct_factual", "M2C-07", "What does transaction ELDM display?", "display the successfully and unsuccessfully posted meter reading documents"),
    ("direct_factual", "M2C-07", "How do I navigate to the detailed display of an object in the monitoring lists?", "choosing Edit > Select or by double clicking on the field in question"),
    ("direct_factual", "M2C-05", "How is a device number created in Device Management?", "The device number is created in MM with the Goods Receipt function"),
    ("direct_factual", "M2C-05", "What do device, device category and device number correspond to in the standard system?", "correspond to equipment, material, and the serial number in the standard system"),
    ("direct_factual", "M2C-05", "When are equipment records created?", "Equipment records are created automatically during goods receipt"),
    ("direct_factual", "M2C-24", "Which indicator sets the clearing priority of original items?", "you set the Clrg Priority indicator"),
    ("direct_factual", "M2C-24", "What happens to interest and charges when the Distribute indicator is set?", "the interest and charges are distributed over all of the due dates"),
    ("direct_factual", "M2C-14", "What is generated when invoicing with bill creation is run?", "Invoicing with Bill Creation results in a print document and a contract accounting document"),
    ("direct_factual", "M2C-14", "What happens to a bill after it has been created?", "After the bill has been created, it is sent to the bill recipient"),
    ("direct_factual", "M2C-17", "What does the Contract Accounts component let me create?", "create and manage contract account master data"),
    ("direct_factual", "M2C-11", "What do the various billing procedures include?", "Different billing periods are included in the various billing procedures"),
    ("direct_factual", "M2C-02", "Through which component are letters such as move-out confirmations generated?", "created using the Print Workbench component"),
    ("direct_factual", "M2C-02", "What can the system trigger automatically for a move-out customer?", "create a final bill for the move-out customer"),
    # 2 paraphrased (avoid the page's own wording)
    ("paraphrased", "M2C-07", "How can I see which meters belong to a reading unit?", "get an overview of the devices of a meter reading unit"),
    ("paraphrased", "M2C-07", "Where in the menu do I find the tools for checking meter readings?", "in the Utilities Industry menu under Device Management > Meter Reading > Monitoring"),
    ("paraphrased", "M2C-24", "Under what circumstances is a payment arrangement for a customer set up?", "You create an installment plan when both of the following apply"),
    ("paraphrased", "M2C-24", "How do I store my finished payment arrangement?", "Save the installment plan"),
    ("paraphrased", "M2C-14", "Can a printed bill be printed again?", "It is possible to reprint bills"),
    ("paraphrased", "M2C-14", "Which function creates an offsetting document when a bill turns out to be wrong?", "you must process them using the Bill Reversal function"),
    ("paraphrased", "M2C-17", "Which contracts does a utilities contract account bundle together?", "one contract account contains all those contracts belonging to one business partner for which the same payment and dunning terms apply"),
    ("paraphrased", "M2C-17", "What kind of change can happen to account master data without a user editing it?", "Master data can be changed automatically by certain business transactions"),
    ("paraphrased", "M2C-11", "Why is the billing period cut into pieces when a rate changes?", "a price change causes the system to divide the total period into subperiods"),
    ("paraphrased", "M2C-02", "What takes place when a customer leaves and a new one arrives?", "If a new customer moves into the installation, the installation is allocated to this customer's contract"),
    ("paraphrased", "M2C-05", "Where does the equipment name of a device come from?", "Name in IS-U: Device; From Component: Plant Maintenance (PM); Name in Standard System: Equipment"),
    # 3 terminology-heavy
    ("terminology", "M2C-07", "What is ISU_QD_1 used for in the meter reading monitoring lists?", "you can use the pushbutton to carry out quantity determination"),
    ("terminology", "M2C-07", "What is the business function ISU_AMI_1 required for?", "request on-demand meter readings"),
    ("terminology", "M2C-05", "Which function uses Goods Receipt from Inventory Management (MM-IM)?", "Function: Delivery; Component: Goods Receipt from Inventory Management (MM-IM)"),
    ("terminology", "M2C-24", "What does the Remaining Amount field decide?", "specify whether this remaining amount is to be included in the first or last installment, or in a new installment"),
    ("terminology", "M2C-24", "What is event 3000 used for?", "by defining event 3000 accordingly"),
    ("terminology", "M2C-14", "What does outsorting mean for a consumption bill?", "Postings do not take place until the bill is released using the Outsorting function"),
    ("terminology", "M2C-17", "Which industry component limits a contract account to one business partner?", "In this component, a contract account can be assigned to one business partner only"),
    ("terminology", "M2C-11", "What is a subperiod in billing?", "divide the total period into subperiods, each with the price valid for that subperiod"),
    ("terminology", "M2C-02", "Which component monitors the workflow processes of move-in and move-out?", "The SAP Business Workflow component (BC-BMT-WFM) enables you to monitor and configure the workflow processes"),
    # 4 code / transaction
    ("code_transaction", "M2C-07", "Which transaction code shows all devices belonging to one meter reading unit?", "Device Overview Transaction EL43"),
    ("code_transaction", "M2C-07", "Which transaction handles the automatic monitoring of meter reading data?", "Automatic Monitoring of Meter Reading Data Transaction EL32"),
    ("code_transaction", "M2C-07", "Which business function enables on-demand meter reading?", "Advanced Metering Infrastructure ( ISU_AMI_1 )"),
    ("code_transaction", "M2C-07", "Which business function is required to carry out quantity determination from the results list?", "Utilities, Quantity Determination ( ISU_QD_1 )"),
    ("code_transaction", "M2C-07", "What is the IDoc category used when uploading discrete meter reading data?", "IDocs from category ISU_MR_UPLOAD"),
    ("code_transaction", "M2C-24", "What is the transaction code for creating an installment plan?", "(transaction FPR1 )"),
    ("code_transaction", "M2C-24", "Where in Customizing is the clearing priority indicator made available?", "Business Transactions > Deferral and Installment Plan > Activate Additional Installment Plan Enhancement"),
    ("code_transaction", "M2C-05", "Which component abbreviation covers purchase requisitions and purchase orders?", "Purchase Requisition and Purchase Order from Purchasing (MM-PUR)"),
    ("code_transaction", "M2C-02", "What is the component abbreviation of SAP Business Workflow in move-in and move-out?", "BC-BMT-WFM"),
    # 5 numeric / detail
    ("numeric_detail", "M2C-24", "Which event number allows other values for company code and contract in an installment plan?", "event 3000"),
    ("numeric_detail", "M2C-24", "In which step of the procedure do I save the installment plan?", "9. Save the installment plan"),
    ("numeric_detail", "M2C-24", "In which step do I choose Continue to get the installment plan proposal?", "8. Choose Continue ."),
    ("numeric_detail", "M2C-24", "In which step does a list of selected items appear?", "7. A list of selected items appears"),
    ("numeric_detail", "M2C-24", "In which step do I enter an amount in the Installment Amount field?", "5. Enter an amount in the Installment Amount field"),
    ("numeric_detail", "M2C-07", "What does the asterisk in the table of monitoring options mean?", "At first the system displays a summarized list grouped by date"),
    # 8 sibling topic (answerable part)
    ("sibling_topic", "M2C-24", "How do I copy default values into the first screen when entering installment plan parameters?", "copy default values to the initial screen using the Installment Plan Type"),
    ("sibling_topic", "M2C-24", "What can be changed in an installment plan proposal before it is saved?", "Add installments - Delete installments - Calculate or delete interest"),
    ("sibling_topic", "M2C-02", "What does the move-in/out component do for a customer who leaves?", "In a move-out, you terminate the customer's contract"),
    ("sibling_topic", "M2C-07", "Which lists exist for checking results after meters have been read?", "monitor meter reading results based on different selection criteria"),
    ("sibling_topic", "M2C-11", "How does the billing procedure cope with changes to master data during a period?", "All master and billing master data can change during a billing period"),
    ("sibling_topic", "M2C-14", "What does invoicing do with the contracts of one contract account?", "The contracts of a contract account are grouped together in invoicing for the joint bill"),
    ("sibling_topic", "M2C-17", "Is each contract tied to a single contract account in the insurance component?", "Each contract is only assigned to one contract account, however one contract account may have several contracts assigned to it"),
    # 10 corrected identity (M2C-05)
    ("corrected_identity", "M2C-05", "Which application component supplies the equipment records for devices?", "functions from the PM application component are used"),
    ("corrected_identity", "M2C-05", "What does Device Management say about advanced metering infrastructure?", "you can find more information under Advanced Metering Infrastructure"),
    ("corrected_identity", "M2C-05", "Which component handles stock transfers of devices?", "Function: Stock Transfer; Component: Goods Issue and Return Delivery from MM-IM"),
    ("corrected_identity", "M2C-05", "How is a device uniquely identified?", "The device is identified by a unique material and serial number combination"),
    ("corrected_identity", "M2C-05", "Which standard-system object stands for the device category in IS-U?", "Name in IS-U: Device Category; From Component: Logistics Basic Data (LO-MD); Name in Standard System: Material"),
    ("corrected_identity", "M2C-05", "Is the equipment number the same everywhere in the system?", "The equipment number is the same throughout the system"),
    ("corrected_identity", "M2C-05", "Which hardware-related tasks does the device component cover?", "manages technical data, installations, meter readings, and the inspection of devices"),
    # 11 review flag (M2C-14 is review-flagged but ingested)
    ("review_conflict", "M2C-14", "What does the Full Reversal function do?", "To reverse billing documents that have been invoiced, you can use the Full Reversal function"),
    ("review_conflict", "M2C-14", "Which function releases bills that were outsorted?", "Postings do not take place until the bill is released using the Outsorting function"),
]

# (category, card, question, absent terms that must not occur in the page text)  -> type absent_detail
ABSENT = [
    ("absent_detail", "M2C-07", "What is the maximum number of meter reading orders that transaction EL31 can display?", ["maximum"]),
    ("absent_detail", "M2C-07", "How often does transaction EL32 run automatically?", ["often"]),
    ("absent_detail", "M2C-07", "Which authorization object protects transaction EL43?", ["authorization"]),
    ("absent_detail", "M2C-05", "Up to how many digits may a serial number have?", ["digits"]),
    ("absent_detail", "M2C-05", "Which database table stores the devices?", ["database table"]),
    ("absent_detail", "M2C-24", "Which interval type is preselected for new installment plans?", ["preselected"]),
    ("absent_detail", "M2C-24", "How many installments can an installment plan have at most?", ["at most"]),
    ("absent_detail", "M2C-24", "Within how many days must the first installment be paid?", ["days"]),
    ("absent_detail", "M2C-14", "What is the retention period for print documents?", ["retention"]),
    ("absent_detail", "M2C-14", "Which output type is used by default when printing bills?", ["default"]),
    ("absent_detail", "M2C-17", "What is the upper limit of contract accounts per business partner?", ["upper limit"]),
    ("absent_detail", "M2C-17", "What is the maximum number of characters in a contract account number?", ["characters"]),
    ("absent_detail", "M2C-11", "What is the shortest billing period that is supported?", ["shortest"]),
    ("absent_detail", "M2C-11", "Which rounding rule does billing apply to partial amounts?", ["rounding"]),
    ("absent_detail", "M2C-02", "How many days before a move-out date must the notice be given?", ["days"]),
    ("absent_detail", "M2C-02", "Which fee applies to a move-in?", ["fee"]),
]

# (category, card, question) -> type not_ingested (the card is identified but there is no local page)
NOT_INGESTED = [
    ("sibling_topic", "M2C-25", "Where can I look at an installment plan that was already saved?"),
    ("sibling_topic", "M2C-04", "What steps does a move-out require?"),
    ("sibling_topic", "M2C-03", "How is a move-in carried out step by step?"),
    ("sibling_topic", "M2C-12", "How does automatic billing run?"),
    ("sibling_topic", "M2C-08", "How are missing meter readings estimated?"),
    ("sibling_topic", "M2C-09", "Which estimation procedures are available for meter readings?"),
    ("review_conflict", "M2C-23", "What does the installment plan overview describe?"),
    ("review_conflict", "M2C-23", "When are installment plans used instead of paying a bill at once?"),
    ("direct_factual", "M2C-26", "How does dunning work for overdue receivables?"),
    ("direct_factual", "M2C-29", "How is a utility installation disconnected and reconnected?"),
]

# (category, card, question) -> type unresolved_identity (conflicting / identity-only cards: never answerable)
UNRESOLVED = [
    ("review_conflict", "M2C-18", "What is the contract account business object?"),
    ("review_conflict", "M2C-18", "Which fields make up the contract account business object?"),
    ("review_conflict", "M2C-18", "What methods does the contract account object offer?"),
    ("review_conflict", "M2C-13", "What is a budget billing plan used for?"),
    ("review_conflict", "M2C-16", "What does the billing and invoicing analysis report?"),
    ("review_conflict", "M2C-01", "What is covered by utilities master data?"),
]

# (category, question, acceptable cards) -> type ambiguous
AMBIGUOUS = [
    ("ambiguous", "How do I create a plan?", ["M2C-24", "M2C-13", "M2C-15", "M2C-23"]),
    ("ambiguous", "What does the bill contain?", ["M2C-14", "M2C-11"]),
    ("ambiguous", "How is the account managed?", ["M2C-17", "M2C-18"]),
    ("ambiguous", "What happens during the move?", ["M2C-02", "M2C-03", "M2C-04", "M2C-10"]),
    ("ambiguous", "What does the monitoring show?", ["M2C-07"]),
    ("ambiguous", "What do I need to activate?", ["M2C-07", "M2C-05", "M2C-24"]),
    ("ambiguous", "How are devices handled?", ["M2C-05", "M2C-07"]),
    ("ambiguous", "Tell me about billing.", ["M2C-11", "M2C-12", "M2C-13", "M2C-14", "M2C-15", "M2C-16"]),
]

OUT_OF_DOMAIN = ["What is the capital of Australia?", "Give me a JavaScript snippet that sorts an array of numbers.", "Which football team won the 2018 World Cup?",
                 "How do I set up sourcing events in SAP Ariba?", "What is the boiling point of water?", "Explain how photosynthesis works.",
                 "How can I change the language of my Android phone?", "Which compression does the SAP HANA database use for columns?"]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def toks(s: str) -> set:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def main() -> int:
    if OUT.exists() or FREEZE.exists():
        print("STOP: the Phase 12 question set is frozen; refusing to rewrite it", file=sys.stderr)
        return 2
    import build_page_collection as BP
    import page_retriever as PR
    embed, _ = BP.load_embedder()
    retriever = PR.PageRetriever.from_store(embed=embed)
    page_text = {}
    for card, doc in PAGES.items():
        g, p = doc.split("/")
        chunks = retriever.page_chunks(g, p)
        page_text[card] = (chunks, norm(" ".join(c.text for c in chunks)))
    queries, problems = [], []

    def add(cat, card, typ, q, **kw):
        rec = {"id": f"P12-{len(queries) + 1:03d}", "authorship": AUTHORSHIP, "authored_phase": "12", "authored_on": "2026-10-01", "category": cat, "query": q, "type": typ,
               "facet": cat, "gold_source_id": card, "gold_doc_id": PAGES.get(card) if typ in ("answerable", "absent_detail") else None, "acceptable_source_ids": [], "evidence": [],
               "expected_status": None, "notes": ""}
        rec.update(kw)
        queries.append(rec)

    for cat, card, q, ev in ANSWERABLE:
        if not any(norm(ev) in norm(c.text) for c in page_text[card][0]):
            problems.append(f"evidence not inside one chunk of {card}: {ev!r}")
        add(cat, card, "answerable", q, answerability="answerable_from_local_page", evidence=[ev], expected_status="answered")
    for cat, card, q, absent in ABSENT:
        for a in absent:
            if norm(a) in page_text[card][1]:
                problems.append(f"absent term {a!r} occurs in the {card} page: {q}")
        add(cat, card, "absent_detail", q, answerability="not_answerable_detail_absent_from_page", absent_terms=absent, expected_status="insufficient_context",
            notes="the topic is on the page, the asked detail is not")
    for cat, card, q in NOT_INGESTED:
        add(cat, card, "not_ingested", q, answerability="not_answerable_page_not_in_local_corpus", expected_status="page_not_ingested")
    for cat, card, q in UNRESOLVED:
        add(cat, card, "unresolved_identity", q, answerability="not_answerable_identity_unresolved", expected_status="unresolved_identity")
    for cat, q, acc in AMBIGUOUS:
        add(cat, acc[0], "ambiguous", q, answerability="ambiguous_any_acceptable_page_or_abstain", acceptable_source_ids=acc, expected_status="answered_or_abstained")
    for q in OUT_OF_DOMAIN:
        add("out_of_domain", None, "out_of_domain", q, answerability="out_of_domain", expected_status="out_of_domain")

    prior = []
    for f in ("phase8_queries", "phase9_queries", "phase10_dev_queries", "phase10_test_queries", "phase11_1_holdout_questions", "phase11_1_holdout2_questions"):
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
    counts, cats = {}, {}
    for x in queries:
        counts[x["type"]] = counts.get(x["type"], 0) + 1
        cats[x["category"]] = cats.get(x["category"], 0) + 1
    payload = {"schema_version": 1, "description": "Phase 12 fresh end-to-end evaluation set (frozen before any Phase 12 evaluation)", "authorship": AUTHORSHIP, "counts": counts,
               "categories": cats, "total": len(queries),
               "corpus_sha256": json.loads((ROOT / "data/page_corpus/manifest.json").read_text(encoding="utf-8"))["corpus_sha256"], "queries": queries}
    text = json.dumps(payload, indent=1, ensure_ascii=False) + "\n"
    OUT.write_text(text, encoding="utf-8")
    FREEZE.write_text(json.dumps({"file": OUT.name, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "total": len(queries), "counts": counts, "categories": cats,
                                  "frozen_before": "any Phase 12 retrieval, router, generator or UI evaluation"}, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(counts), json.dumps(cats), len(queries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
