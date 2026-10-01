#!/usr/bin/env python3
"""Phase 11.1 (iteration 2) - SECOND fresh holdout question set (AI-authored, written and frozen BEFORE any Phase 11.1 candidate code or evaluation existed).

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

OUT = ROOT / "data/evaluation/phase11_1_holdout2_questions.json"
FREEZE = ROOT / "data/evaluation/phase11_1_holdout2_freeze.json"
AUTHORSHIP = ("AI coding assistant (not blind; not a domain expert; had read the 7-page corpus text and the Phase 11 E2E failure analysis; "
              "written 2026-10-01 AFTER the first holdout was evaluated and BEFORE the iteration-2 candidate (C3) existed; NOT human-labelled)")

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
    ("M2C-07", "detail", "Which business function is a prerequisite for AMI monitoring of meter readings?", "you have activated the business function Advanced Metering Infrastructure 2 ( ISU_AMI_2 )"),
    ("M2C-07", "natural", "If I enter a portion, which objects can I display?", "you can display schedule records, billing orders, and meter reading orders"),
    ("M2C-07", "paraphrase", "What can be shown when the starting point is a device?", "you can display meter reading orders or meter reading results"),
    ("M2C-07", "natural", "Under which menu path are the monitoring transactions found?", "in the Utilities Industry menu under Device Management > Meter Reading > Monitoring"),
    ("M2C-05", "detail", "Which component corresponds to the serial number in the standard system for a device number?", "Name in IS-U: Device Number; From Component: Logistics Basic Data (LO-MD); Name in Standard System: Serial Number"),
    ("M2C-05", "detail", "Which component handles goods issue and return delivery when devices are scrapped or sold?", "Function: Outward Movement (such as scrapping or sales); Component: Goods Issue and Return Delivery from MM-IM"),
    ("M2C-05", "natural", "Which component is used to bill devices?", "Billing is then carried out with the Sales and Distribution (SD) component"),
    ("M2C-05", "paraphrase", "What does Device Management take care of?", "This component manages technical data, installations, meter readings, and the inspection of devices"),
    ("M2C-24", "natural", "Where do I specify the percentage for the first installment?", "under: Business Transactions > Deferral and Installment Plan > Define Categories for Installment Plan , specify a percentage"),
    ("M2C-24", "natural", "What do I have to activate so that interest and surcharges are part of an installment plan?", "activate the enhancement under Business Transactions > Deferral and Installment Plan > Activate Installment Plan Enhancement for Surcharges/Interest"),
    ("M2C-24", "natural", "Which entries are mandatory when I enter the installment plan parameters manually?", "You must enter the installment interval and the interval type, as well as the installment plan category"),
    ("M2C-24", "natural", "How does the system check a rounding amount that I enter?", "the system automatically checks whether this amount complies with the rounding rules defined in Customizing"),
    ("M2C-24", "detail", "What is the prerequisite for creating an inflation surcharge in the installment plan proposal?", "The prerequisite in this case is that you activated the enhancement in Customizing under Business Transactions > Deferral and Installment Plans > Activate Installment Plan Enhancement for Charges/Interest"),
    ("M2C-24", "detail", "Which function module is documented as the sample for event 3000?", "see the documentation of the sample function module FKK_SAMPLE_3000"),
    ("M2C-14", "natural", "What can I do with the Print Document Display function?", "you can use to simulate the bill using the Print Document Display function"),
    ("M2C-14", "natural", "With which component is invoicing reversal integrated?", "Invoicing reversal, therefore, is integrated with the Contract Billing (IS-U-BI) component"),
    ("M2C-14", "detail", "Which function reverses billing documents that have already been invoiced?", "To reverse billing documents that have been invoiced, you can use the Full Reversal function"),
    ("M2C-14", "natural", "What must exist before billing can take place?", "must exist if billing is to take place"),
    ("M2C-14", "detail", "Which functions inform the customer about the number of budget billings and their due dates?", "you use either the Partial Bill Creation function or the Budget Billing Request function"),
    ("M2C-17", "yes_no", "Can one contract in Utilities belong to several contract accounts?", "each individual contract is assigned to one contract account only"),
    ("M2C-17", "natural", "What is defined in the contract account master record for each business partner?", "you can define, for each business partner, the procedures that apply when posting and processing the line items of a given contract account"),
    ("M2C-17", "natural", "What can cause a processing lock to be set automatically?", "a return can result in a processing lock being set"),
    ("M2C-17", "natural", "On what basis are contract accounts usually managed?", "Contract accounts tend to be managed on an open item basis"),
    ("M2C-11", "natural", "What does the billing module ensure about changes during a billing period?", "The billing module ensures that all billing-relevant changes that occur during a billing period are taken into consideration"),
    ("M2C-11", "paraphrase", "What happens to the total consumption when a price changes?", "The system also divides the total consumption, which produces the corresponding partial amount"),
    ("M2C-02", "natural", "What can I do for the business partner in a move-in?", "you can create a business partner and contract account for the customer, or select existing ones"),
    ("M2C-02", "yes_no", "Can the screen layout for move-in and move-out be configured?", "You can also configure the screen layout to suit your requirements"),
    ("M2C-02", "natural", "Can a move-in or move-out be processed completely in one step?", "process the entire transaction immediately and in full"),
]
# (card, facet, question, absent terms that must not occur in the page text)
ABSENT = [
    ("M2C-14", "numeric", "How many bills can be reversed at once?", ["at once"]),
    ("M2C-14", "numeric", "What is the maximum number of reprints allowed per bill?", ["maximum"]),
    ("M2C-24", "numeric", "What is the minimum interval between two installments?", ["minimum"]),
    ("M2C-24", "detail", "Which authorization object controls who may create installment plans?", ["authorization"]),
    ("M2C-07", "detail", "What is the default selection criterion in the monitoring transaction?", ["default"]),
    ("M2C-05", "numeric", "How many characters can a device number have?", ["characters"]),
    ("M2C-11", "numeric", "How long is a billing period in days?", ["days"]),
    ("M2C-17", "detail", "Which transaction code displays a contract account?", ["transaction code"]),
    ("M2C-02", "detail", "What is the notice period for terminating a customer's contract in a move-out?", ["notice period"]),
    ("M2C-02", "detail", "Which fee applies to the final bill of a move-out?", ["fee"]),
]
NOT_INGESTED = [("M2C-03", "How does the move-in process work?"), ("M2C-19", "How do I analyse incoming payments?"), ("M2C-28", "Which APIs exist for collection agencies?"),
                ("M2C-10", "How is meter reading data handled during a move-in?")]
UNRESOLVED = [("M2C-01", "What master data does Utilities Master Data cover?"), ("M2C-16", "What does periodic billing analysis show?")]
OUT_OF_DOMAIN = ["How tall is Mount Everest?", "Translate good morning into French.", "What is a good recipe for chicken curry?", "How do I install Python on Windows?"]


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
        rec = {"id": f"P111H2-{n:03d}", "authorship": AUTHORSHIP, "authored_phase": "11.1", "authored_on": "2026-10-01", "query": q, "type": typ, "facet": facet, "gold_source_id": card,
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
    for f in ("phase8_queries", "phase9_queries", "phase10_dev_queries", "phase10_test_queries", "phase11_1_holdout_questions"):
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
    payload = {"schema_version": 1, "description": "Phase 11.1 second fresh holdout (frozen before the iteration-2 candidate existed)", "authorship": AUTHORSHIP, "counts": counts, "total": len(queries),
               "corpus_sha256": json.loads((ROOT / "data/page_corpus/manifest.json").read_text(encoding="utf-8"))["corpus_sha256"], "queries": queries}
    text = json.dumps(payload, indent=1, ensure_ascii=False) + "\n"
    OUT.write_text(text, encoding="utf-8")
    FREEZE.write_text(json.dumps({"file": OUT.name, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "total": len(queries), "counts": counts,
                                  "frozen_before": "the iteration-2 candidate code (C3) and any evaluation of it"}, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(counts), len(queries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
