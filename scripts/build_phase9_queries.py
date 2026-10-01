#!/usr/bin/env python3
"""Phase 9B - authors and FREEZES ``data/evaluation/phase9_queries.json`` (fresh retrieval / end-to-end evaluation set).

AUTHORSHIP DISCLOSURE: written by the AI coding assistant (no human domain expert, no runtime LLM). It is a *fresh* set: no query is taken from
the Phase 4/5/7F/8 sets (checked: exact and near-duplicate), and no query shares more than 3 contiguous words with any M2C card text (the
Phase 5 rule, checked against all 29 cards). The answerable queries were written with the page text in view, so they are not blind.
No retrieval was run before this file was frozen (the freeze record stores the sha256 of the file; ``evaluate_phase9.py`` refuses a file whose
hash differs). ``labels_changed_after_retrieval`` is therefore False by construction.

Query types: answerable | absent_detail | not_ingested | unresolved_identity | out_of_domain.
Facets (answerable queries and a few others): keyword | natural | paraphrase | entity | rare_term | multi_concept | section_specific |
sibling_ambiguous | terminology_mismatch.
Only 7 of 29 pages exist locally, so 22 cards can only be answered with ``page_not_ingested`` / ``unresolved_identity`` by design.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import page_corpus as PC  # noqa: E402

ROOT = PC.ROOT
OUT = ROOT / "data" / "evaluation" / "phase9_queries.json"
FREEZE = ROOT / "data" / "evaluation" / "phase9_queries_freeze.json"
PRIOR_SETS = ["data/evaluation/card_retrieval_questions.json", "data/evaluation/independent_queries.json", "data/evaluation/phase7F_ood_queries.json",
              "data/evaluation_questions.json", "data/evaluation/phase8_queries.json"]
AUTHORED_ON = "2026-10-01"

# (query, facet, [evidence quotes verbatim from the page], optional acceptable sibling card ids)
ANSWERABLE = {
    "M2C-07": [
        ("EL31 monitoring selection criteria", "keyword", ["You can use this transaction to monitor meter reading results based on different selection criteria."], []),
        ("ELDM", "entity", ["display the successfully and unsuccessfully posted meter reading documents"], []),
        ("Which business function does the AMI monitoring pushbutton for meter readings require?", "entity", ["you have activated the business function Advanced Metering Infrastructure 2 ( ISU_AMI_2 )"], []),
        ("Can I ask a smart meter for a reading right now from the result list?", "natural", ["you can use the pushbutton to request on-demand meter readings"], []),
        ("Where in the menu are the monitoring transactions for readings located?", "paraphrase", ["Utilities Industry menu under Device Management > Meter Reading > Monitoring"], []),
        ("AMI monitor", "rare_term", ["navigate to the AMI monitor for one or more orders"], []),
        ("What can I display when I enter contracts, installations or business partners?", "multi_concept", ["you can display billing orders, meter reading orders, or meter reading results"], []),
        ("Where is the setting that drives automatic follow-up of readings maintained?", "section_specific", ["Automatic Monitoring of Meter Reading Data"], []),
        ("Which function shows how many IDocs from the discrete upload failed to post?", "terminology_mismatch", ["IDocs from category ISU_MR_UPLOAD"], []),
        ("quantity determination trigger", "keyword", ["For meter readings with a quantity determination trigger"], []),
        ("Which objects are shown when I enter portions?", "natural", ["you can display schedule records, billing orders, and meter reading orders"], []),
        ("monitor meter reading", "sibling_ambiguous", ["You can use this transaction to monitor meter reading results based on different selection criteria."], ["M2C-06", "M2C-08"]),
        ("What does the device overview transaction show?", "section_specific", ["get an overview of the devices of a meter reading unit"], []),
        ("How can I get the system to run follow-up actions automatically after readings come in?", "terminology_mismatch", ["trigger automatic follow-on processing for selected meter reading orders"], []),
    ],
    "M2C-05": [
        ("IS-U device equipment mapping", "keyword", ["Name in IS-U: Device; From Component: Plant Maintenance (PM); Name in Standard System: Equipment"], []),
        ("Which functions does Materials Management handle for device flow?", "natural", ["MM is also used for the following functions in device flow:"], []),
        ("LO-MD material master device category", "entity", ["Name in IS-U: Device Category; From Component: Logistics Basic Data (LO-MD); Name in Standard System: Material"], []),
        ("goods issue and return delivery", "rare_term", ["Goods Issue and Return Delivery from MM-IM"], []),
        ("How is a serial number for a meter generated if not from goods receipt?", "paraphrase", ["It can also be generated when you create a device in IS-U."], []),
        ("Which components must be linked before devices can be managed?", "multi_concept", ["The following table lists the standard application components that must be integrated into device management before you can manage devices."], []),
        ("When I receive meters into stock, what record does SAP create?", "terminology_mismatch", ["Equipment records are created automatically during goods receipt"], []),
        ("Which related documentation is listed for planning and posting goods receipts?", "section_specific", ["MM-IM: Planning Goods Receipts , Goods Receipts for Purchase Orders"], []),
        ("How are meters managed in SAP?", "sibling_ambiguous", ["This component manages technical data, installations, meter readings, and the inspection of devices."], ["M2C-06", "M2C-07"]),
        ("ISU_AMI_1 advanced metering", "entity", ["If you have activated the Advanced Metering Infrastructure business function (ISU_AMI_1)"], []),
    ],
    "M2C-24": [
        ("FPR1", "keyword", ["Installment Plan > Create (transaction FPR1 )"], []),
        ("What do I do when a customer cannot pay open items under normal terms?", "natural", ["The business partner is unable to meet his/her payment obligations in accordance with the usual payment rules."], []),
        ("sample function module FKK_SAMPLE_3000", "rare_term", ["sample function module FKK_SAMPLE_3000"], []),
        ("Can the opening installment be a fixed share of the whole plan amount?", "paraphrase", ["The system can calculate the first installment as a percentage of the total amount of the installment plan."], []),
        ("How are interest and charges documents handled when I create a plan?", "multi_concept", ["interest and charges documents are automatically transferred to the installment plan for the original receivables"], []),
        ("What choices are there for the leftover amount after instalments are computed?", "section_specific", ["specify whether this remaining amount is to be included in the first or last installment, or in a new installment"], []),
        ("Distribute indicator", "entity", ["If you set the Distribute indicator, the interest and charges are distributed over all of the due dates."], []),
        ("How do I set up a payment-by-instalments arrangement for a debtor?", "terminology_mismatch", ["You create an installment plan when both of the following apply"], []),
        ("rounding amount number of installments", "keyword", ["Rounding Amount and No. of Instmnts"], []),
        ("What changes can I make on the proposal screen?", "natural", ["An Installment Plan Proposal appears, in which you can make the following changes"], []),
        ("Where in Customizing do I switch on the priority-clearing enhancement?", "section_specific", ["Business Transactions > Deferral and Installment Plan > Activate Additional Installment Plan Enhancement"], []),
        ("How do I influence which original items are cleared first by incoming money?", "rare_term", ["You can assign numerical key figures in the Prio column."], []),
        ("set up an installment plan", "sibling_ambiguous", ["You create an installment plan when both of the following apply"], ["M2C-23"]),
        ("Which formula links the plan amount, the count of installments and the leftover?", "multi_concept", ["installment amount * number of installments + remaining amount = total of original receivable"], []),
    ],
    "M2C-14": [
        ("bill reversal", "keyword", ["you must process them using the Bill Reversal function"], []),
        ("What happens to the contracts of one contract account when invoicing runs?", "natural", ["The contracts of a contract account are grouped together in invoicing for the joint bill."], []),
        ("Can I reprint a bill after it has been issued?", "paraphrase", ["It is possible to reprint bills."], []),
        ("IS-U-BI contract billing prerequisite", "entity", ["Billing documents from the Contract Billing (IS-U-BI) component"], []),
        ("outsorting", "rare_term", ["Postings do not take place until the bill is released using the Outsorting function."], []),
        ("How are budget billing amounts communicated to customers?", "multi_concept", ["you use either the Partial Bill Creation function or the Budget Billing Request function"], []),
        ("What does the system generate when a customer invoice is produced?", "terminology_mismatch", ["Invoicing with Bill Creation results in a print document and a contract accounting document."], []),
        ("What happens after the bill has been sent to the recipient?", "section_specific", ["the bill amounts are paid, regulated by the utility company, or dunned"], []),
        ("How do I cancel a billing document that was already invoiced?", "natural", ["To reverse billing documents that have been invoiced, you can use the Full Reversal function."], []),
        ("What comes after billing in the end-to-end utilities revenue cycle?", "sibling_ambiguous", ["Once the contract is billed, you start bill creation."], ["M2C-11", "M2C-12"]),
    ],
    "M2C-17": [
        ("contract account master data", "keyword", ["This component enables you to create and manage contract account master data."], []),
        ("Can one business partner have several contract accounts?", "natural", ["You can assign more than one contract account to a given business partner."], []),
        ("IS-T contract account one business partner", "entity", ["In this component, a contract account can be assigned to one business partner only."], []),
        ("In utilities, what do the contracts inside one account have in common?", "paraphrase", ["one contract account contains all those contracts belonging to one business partner for which the same payment and dunning terms apply"], []),
        ("one-time accounts", "rare_term", ["This does not apply to one-time accounts."], []),
        ("Which processes can be defined per business partner in the account master record?", "multi_concept", ["the procedures that apply when posting and processing the line items of a given contract account"], []),
        ("How do public sector taxes relate to these accounts?", "section_specific", ["You set up the contract accounts of a business partner for the relevant taxes"], []),
        ("What triggers a block being set automatically on a customer's account after a return?", "terminology_mismatch", ["a return can result in a processing lock being set"], []),
        ("Does the system record changes to the master data?", "natural", ["The system logs changes to master data."], []),
        ("Explain the purpose of a contract account.", "sibling_ambiguous", ["each business partner posting is assigned to one business partner and to one contract account"], ["M2C-18"]),
    ],
    "M2C-11": [
        ("What does billing use to determine the basis for schema execution?", "natural", ["Billing uses meter reading results or load profiles to determine the evaluation basis for schema execution."], []),
        ("What happens to a tariff change in the middle of a period?", "terminology_mismatch", ["a price change causes the system to divide the total period into subperiods"], []),
        ("rate creation calculations", "keyword", ["All calculations required for rate creation are made during schema execution."], []),
        ("Can master data change while a billing period is running?", "paraphrase", ["All master and billing master data can change during a billing period."], []),
        ("How does billing work for utilities?", "sibling_ambiguous", ["You can process all known period categories using different billing procedures."], ["M2C-12", "M2C-14"]),
    ],
    "M2C-02": [
        ("What can I automate when a tenant leaves?", "terminology_mismatch", ["create a final bill for the move-out customer"], []),
        ("welcome letter move-in", "keyword", ["create a welcome letter for the move-in customer"], []),
        ("BC-BMT-WFM", "entity", ["The SAP Business Workflow component (BC-BMT-WFM) enables you to monitor and configure the workflow processes."], []),
        ("Which component produces confirmation letters for customers who move out?", "paraphrase", ["Letters to the customer, such as welcome letters and move-out confirmations are created using the Print Workbench component."], []),
        ("What happens to the installation when a new customer replaces the old one?", "section_specific", ["If a new customer moves into the installation, the installation is allocated to this customer's contract."], []),
        ("At move-in, can I reuse an existing business partner and contract account?", "multi_concept", ["you can create a business partner and contract account for the customer, or select existing ones."], []),
    ],
}

# (card, query, [terms that must NOT occur in the page text])
ABSENT = [
    ("M2C-07", "What is the maximum number of rows the EL31 result list can display?", ["maximum number"]),
    ("M2C-07", "Which authorization object is needed to run the monitoring transaction?", ["authorization"]),
    ("M2C-05", "What is the maximum length of a device serial number?", ["maximum length"]),
    ("M2C-05", "Which transaction creates a brand-new device in IS-U?", ["EG31"]),
    ("M2C-24", "What is the maximum number of installments allowed in one plan?", ["maximum number"]),
    ("M2C-24", "Which transaction displays an existing installment plan?", ["FPR3"]),
    ("M2C-14", "Which transaction runs invoicing for a large batch of contract accounts?", ["EA19"]),
    ("M2C-14", "How many hours does bill creation take for large volumes?", ["hours"]),
    ("M2C-17", "What is the maximum number of contracts one contract account can hold?", ["maximum number"]),
    ("M2C-17", "Which transaction code opens a new contract account record?", ["CAA1"]),
    ("M2C-11", "Which transaction runs a billing simulation?", ["EASIBI"]),
    ("M2C-11", "How many different billing period categories are there?", ["twelve"]),
    ("M2C-02", "Which transaction processes a move-in?", ["EC50"]),
    ("M2C-02", "Which fields are mandatory on the move-in screen?", ["mandatory"]),
]

# card -> (query, acceptable sibling ids) ; the card's page is not in the local corpus
NOT_INGESTED = [
    ("M2C-03", "What are the steps to register a new tenant in a utility installation?", []),
    ("M2C-04", "How do I terminate a customer's supply contract when they leave?", ["M2C-02"]),
    ("M2C-06", "How do I enter a meter reading result manually?", []),
    ("M2C-08", "How does the system estimate a reading when no actual value is available?", ["M2C-09"]),
    ("M2C-09", "What are the individual estimation procedures for meter readings and how do they differ?", ["M2C-08"]),
    ("M2C-10", "How do I record the starting meter reading when a customer moves in?", ["M2C-03"]),
    ("M2C-12", "How do I schedule billing to run automatically in the background?", ["M2C-11"]),
    ("M2C-15", "How are budget billing amounts collected and processed after plan creation?", []),
    ("M2C-19", "How can I check payments that arrived on the bank statement?", ["M2C-20"]),
    ("M2C-20", "How does the system decide which open items an incoming payment clears?", ["M2C-21"]),
    ("M2C-21", "What kinds of clearing exist for posted payments?", ["M2C-20"]),
    ("M2C-22", "How are payments collected at an external cash desk posted?", ["M2C-19"]),
    ("M2C-23", "What is an installment plan and why would a utility offer one?", ["M2C-24"]),
    ("M2C-25", "How do I look at an installment plan I created earlier and change its terms?", ["M2C-24"]),
    ("M2C-26", "How does the system send reminders for unpaid invoices?", []),
    ("M2C-27", "How do I hand over overdue accounts to an external collections agency?", []),
    ("M2C-28", "Which enterprise services are available for communicating with a collection agency?", ["M2C-27"]),
    ("M2C-29", "How do I reconnect a customer after payment is received?", []),
    ("M2C-04", "Which steps are needed to issue a final bill after a customer moves out?", ["M2C-02", "M2C-14"]),
    ("M2C-29", "How do I deactivate supply for a customer who has not paid?", []),
]

UNRESOLVED = [
    ("M2C-01", "How do premises, connection objects and device locations fit together in utilities master data?"),
    ("M2C-01", "What master data objects must exist before I can install a meter?"),
    ("M2C-13", "How do I give a customer fixed monthly payments for consumption?"),
    ("M2C-13", "What is a budget billing plan and how is it structured?"),
    ("M2C-16", "How do I analyse billing and invoicing results over a period?"),
    ("M2C-16", "What analysis tools exist for periodic billing?"),
    ("M2C-18", "What is the structure of a contract account as a business object?"),
    ("M2C-18", "Which object model classes represent a contract account in SAP?"),
]

OUT_OF_DOMAIN = [
    "Which city is Canada's capital?", "How do I bake sourdough bread at home?", "Explain how a transformer neural network works.",
    "How do I add a new app tile to the Fiori launchpad?", "How do I set up a SAP SuccessFactors performance review?", "Who won the football world cup in 2014?",
    "Write a Python function that reverses a string.", "What are the symptoms of vitamin D deficiency?", "How do I reset my Windows password?",
    "Which camera settings are best for night photography?", "How do I configure SAP Ariba sourcing events?", "What is the current price of gold?",
    "How do I train for a half marathon?", "How do I create a workflow in Salesforce?",
    "How do I read the dial of my home electricity meter?", "How can I reduce my household electricity bill?",
]

PREREGISTERED = {
    "declared_before_evaluation": True, "no_tuning_on_this_set": True,
    "router": "rank-1 of the card router, dense only, no similarity threshold (Phase 7F: min_cosine stays None)",
    "default_chunk_strategy": "B_heading_200 (unchanged from Phase 8)",
    "k_chunks": 5, "context_budget_tokens": 700, "max_context_chunks": 4,
    "ood_min_coverage": 0.25, "context_min_coverage": 0.5, "extractive_min_score": 0.34, "min_sentence_support": 0.6,
    "hit_definition": "a retrieved chunk whose text contains (whitespace-normalised) any evidence quote of the query",
    "answer_correct_definition": "status == answered AND at least one cited chunk contains an evidence quote AND the cited page is the gold page",
    "router_correct_definition": "gold card at rank 1; for sibling_ambiguous / not_ingested queries rank-1 inside acceptable_source_ids is reported separately (never merged into the headline)",
    "hybrid_or_rerank_decision_rule": "NOT tested unless the failure analysis names a concrete cause; if tested, adopt only if recall@1 on this set improves AND no facet drops by more than 5 points",
    "metrics_not_combined": ["routing", "identity", "retrieval", "generation", "citation"],
}


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", t.replace("\xa0", " ")).strip()


def words(t: str):
    return re.findall(r"[a-z0-9]+", t.lower())


def longest_shared_run(a, b) -> int:
    """Longest contiguous word run common to word lists a and b."""
    best = 0
    index = {}
    for j, w in enumerate(b):
        index.setdefault(w, []).append(j)
    for i, w in enumerate(a):
        for j in index.get(w, []):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            best = max(best, k)
    return best


def prior_queries():
    out = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("query", "question") and isinstance(v, str):
                    out.add(" ".join(words(v)))
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    for p in PRIOR_SETS:
        walk(json.loads((ROOT / p).read_text(encoding="utf-8")))
    return out


def jaccard(a, b) -> float:
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a | b else 0.0


def main() -> int:
    recs = {r["source_ids"][0]: r for r in PC.load_records()}
    cards = json.loads((ROOT / "data" / "retrieval_units.json").read_text(encoding="utf-8"))["units"]
    card_words = {c["source_id"]: words(c["embedding_text"]) for c in cards}
    queries, problems = [], []
    n = 0

    def add(**kw):
        nonlocal n
        n += 1
        queries.append({"id": f"P9-{n:03d}", "authorship": "AI coding assistant (not blind; not a domain expert)", "authored_phase": 9, "authored_on": AUTHORED_ON, **kw})

    for sid, items in ANSWERABLE.items():
        text = norm(recs[sid]["text"])
        for q, facet, ev, acc in items:
            for e in ev:
                if norm(e) not in text:
                    problems.append((sid, q, "evidence not verbatim", e))
            add(query=q, type="answerable", facet=facet, answerability="answerable_from_local_page", gold_source_id=sid, gold_doc_id=recs[sid]["doc_id"], acceptable_source_ids=acc,
                evidence=ev, expected_status="answered",
                notes=("sibling-topic ambiguity by design: other cards in acceptable_source_ids are legitimate routes" if facet == "sibling_ambiguous" else ""))
    for sid, q, absent in ABSENT:
        text = norm(recs[sid]["text"]).lower()
        for a in absent:
            if a.lower() in text:
                problems.append((sid, q, "absent term present", a))
        add(query=q, type="absent_detail", facet="natural", answerability="not_answerable_detail_absent_from_page", gold_source_id=sid, gold_doc_id=recs[sid]["doc_id"], acceptable_source_ids=[],
            evidence=[], absent_terms=absent, expected_status="insufficient_context", notes="topic is on the page, the asked detail is not (term search)")
    for sid, q, acc in NOT_INGESTED:
        add(query=q, type="not_ingested", facet="natural", answerability="not_answerable_page_not_in_local_corpus", gold_source_id=sid, gold_doc_id=None, acceptable_source_ids=acc,
            evidence=[], expected_status="page_not_ingested", notes="page exists on SAP Help but is not in the local corpus; status page_not_ingested is the correct outcome")
    for sid, q in UNRESOLVED:
        add(query=q, type="unresolved_identity", facet="natural", answerability="not_answerable_identity_unresolved", gold_source_id=sid, gold_doc_id=None, acceptable_source_ids=[],
            evidence=[], expected_status="unresolved_identity", notes="card has conflicting or identity-only status (7C)")
    for q in OUT_OF_DOMAIN:
        add(query=q, type="out_of_domain", facet="natural", answerability="out_of_domain", gold_source_id=None, gold_doc_id=None, acceptable_source_ids=[], evidence=[], expected_status="out_of_domain",
            notes="")

    # ---- freshness checks (no retrieval is run here)
    prior = prior_queries()
    for q in queries:
        w = words(q["query"])
        if " ".join(w) in prior:
            problems.append((q["id"], q["query"], "exact duplicate of an earlier set", ""))
        if any(jaccard(w, p.split()) >= 0.8 for p in prior):
            problems.append((q["id"], q["query"], "near duplicate (Jaccard>=0.8) of an earlier set", ""))
        if q["type"] != "out_of_domain":
            worst = max((longest_shared_run(w, cw), sid) for sid, cw in card_words.items())
            q["max_card_phrase_run_words"] = worst[0]
            if worst[0] > 3:
                problems.append((q["id"], q["query"], f"shares {worst[0]} contiguous words with card {worst[1]}", ""))
    if len({" ".join(words(q["query"])) for q in queries}) != len(queries):
        problems.append(("-", "-", "duplicate queries inside the set", ""))
    if problems:
        for p in problems:
            print("PROBLEM", p)
        return 1

    counts = {t: sum(1 for q in queries if q["type"] == t) for t in ("answerable", "absent_detail", "not_ingested", "unresolved_identity", "out_of_domain")}
    payload = {
        "schema_version": 1, "description": "Phase 9 fresh retrieval and end-to-end evaluation queries (frozen before any retrieval was run)",
        "authorship": {"authored_by": "AI coding assistant, after reading the 7 ingested pages; not a human domain expert; no LLM generation at runtime",
                       "caveat": "answerable queries were written with the page text in view (not blind); a human domain review has not been done; per-page n is 5-14, so every rate has a wide interval",
                       "fresh_check": "no exact/near duplicate (Jaccard<0.8) of any Phase 4/5/7F/8 query; no query shares more than 3 contiguous words with any card text",
                       "written_before_evaluation": True, "labels_changed_after_retrieval": False, "authored_on": AUTHORED_ON},
        "preregistered": PREREGISTERED, "counts": counts,
        "facet_counts": {f: sum(1 for q in queries if q["facet"] == f) for f in sorted({q["facet"] for q in queries})},
        "corpus_sha256": json.loads((PC.CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))["corpus_sha256"],
        "queries": queries}
    data = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    OUT.write_text(data, encoding="utf-8")
    FREEZE.write_text(json.dumps({"file": "data/evaluation/phase9_queries.json", "sha256": hashlib.sha256(data.encode("utf-8")).hexdigest(), "queries": len(queries),
                                  "frozen_on": AUTHORED_ON, "statement": "frozen before any retrieval result was computed; evaluate_phase9.py refuses a different hash"}, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(queries)} queries {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
