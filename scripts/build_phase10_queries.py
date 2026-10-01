#!/usr/bin/env python3
"""Phase 10 - authors and FREEZES two fresh query sets: DEV (design/selection of candidates) and TEST (sealed, evaluated once).

AUTHORSHIP DISCLOSURE: written by the AI coding assistant after reading the 7 ingested pages; not blind, not a domain expert, no runtime LLM.
Both sets were written BEFORE any Phase 10 retrieval or generation experiment and before the candidates were run. The author knew the Phase 9 failure
analysis (design-aware). Queries are checked against every earlier set (Phase 4/5/7F/8/9) and against each other (DEV vs TEST): no exact or near
duplicate (Jaccard >= 0.8), and no query shares more than 3 contiguous words with any card text (Phase 5 rule). Evidence quotes are verbatim page text and
absent terms are verified absent. Do NOT re-run after any experiment: it rewrites the frozen files.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_phase9_queries as B9  # noqa: E402
import page_corpus as PC  # noqa: E402

ROOT = PC.ROOT
EVAL = ROOT / "data" / "evaluation"
FREEZE = EVAL / "phase10_queries_freeze.json"
AUTHORED_ON = "2026-10-01"
PRIOR = B9.PRIOR_SETS + ["data/evaluation/phase9_queries.json"]

# (card, query, facet, [evidence verbatim], [acceptable sibling ids])
DEV_ANS = [
    ("M2C-07", "What happens in the lists when I double click a field?", "natural", ["you can navigate to the detailed display of an object by choosing Edit > Select or by double clicking on the field in question"], []),
    ("M2C-07", "Which transaction shows an overview of the devices in a reading unit?", "paraphrase", ["get an overview of the devices of a meter reading unit"], []),
    ("M2C-07", "EL32 customizing path", "keyword", ["Customizing for SAP Utilities > Device Management > Meter Reading > Basic Settings > Automatic Monitoring of Meter Reading Data"], []),
    ("M2C-07", "What must be active to see readings when I start from portions?", "multi_concept", ["If the business function Utilities, Quantity Determination ( ISU_QD_1 ) is active, you can also display meter reading results."], []),
    ("M2C-07", "Starting from a device, which objects can I list?", "section_specific", ["If you start by entering devices, you can display meter reading orders or meter reading results."], []),
    ("M2C-07", "ISU_MR_UPLOAD", "rare_term", ["IDocs from category ISU_MR_UPLOAD"], []),
    ("M2C-05", "Which SAP component does the device number come from?", "natural", ["Name in IS-U: Device Number; From Component: Logistics Basic Data (LO-MD); Name in Standard System: Serial Number"], []),
    ("M2C-05", "How is one physical meter told apart from other material with the same serial number?", "paraphrase", ["The device is identified by a unique material and serial number combination"], []),
    ("M2C-05", "stock transfer component", "keyword", ["Function: Stock Transfer; Component: Goods Issue and Return Delivery from MM-IM"], []),
    ("M2C-05", "Which component carries out billing for devices?", "natural", ["Billing is then carried out with the Sales and Distribution (SD) component."], []),
    ("M2C-05", "MM-PUR", "rare_term", ["Purchase Requisition and Purchase Order from Purchasing (MM-PUR)"], []),
    ("M2C-05", "Why can I use maintenance plans for meters?", "terminology_mismatch", ["Therefore, functions from the PM application component are used, including standard ordering functions and creation of maintenance plans or task lists."], []),
    ("M2C-24", "What does the Clrg Priority indicator do?", "entity", ["To be able to prioritize the clearing of original items when payments are received, you set the Clrg Priority indicator."], []),
    ("M2C-24", "Which fields does the plan copy from the original item?", "natural", ["the system copies the company code, contract, business area, and business place from the original item"], []),
    ("M2C-24", "Where can the leftover from uneven installments be placed?", "terminology_mismatch", ["specify whether this remaining amount is to be included in the first or last installment, or in a new installment"], []),
    ("M2C-24", "What is the Prio column for?", "entity", ["You can assign numerical key figures in the Prio column."], []),
    ("M2C-24", "What can I change in the proposal before saving?", "section_specific", ["Calculate or delete interest"], []),
    ("M2C-24", "interest document", "keyword", ["When you calculate interest, the system creates an interest document automatically."], []),
    ("M2C-24", "What decides the due date of the first installment?", "natural", ["The start date defines the due date of the first installment."], []),
    ("M2C-14", "Which function lets me reprint a bill?", "natural", ["It is possible to reprint bills."], []),
    ("M2C-14", "What does invoicing produce?", "natural", ["Invoicing with Bill Creation results in a print document and a contract accounting document."], []),
    ("M2C-14", "Which function reverses an invoiced billing document completely?", "paraphrase", ["To reverse billing documents that have been invoiced, you can use the Full Reversal function."], []),
    ("M2C-14", "outsorting release", "keyword", ["Postings do not take place until the bill is released using the Outsorting function."], []),
    ("M2C-14", "How do customers learn the budget billing due dates?", "terminology_mismatch", ["you use either the Partial Bill Creation function or the Budget Billing Request function"], []),
    ("M2C-14", "Where are open bill amounts followed up once the customer has the bill?", "multi_concept", ["The bill requests can be followed up in contract accounts receivable and payable."], []),
    ("M2C-17", "Can a single contract account belong to several business partners?", "natural", ["a single contract account can be assigned to more than one business partner"], []),
    ("M2C-17", "Which rule applies to telecommunications contract accounts?", "entity", ["In this component, a contract account can be assigned to one business partner only."], []),
    ("M2C-17", "Which property do all contracts in one utilities account share?", "paraphrase", ["one contract account contains all those contracts belonging to one business partner for which the same payment and dunning terms apply"], []),
    ("M2C-17", "How are public sector contract accounts organised?", "section_specific", ["You set up the contract accounts of a business partner for the relevant taxes"], []),
    ("M2C-17", "return processing lock", "keyword", ["a return can result in a processing lock being set"], []),
    ("M2C-17", "How is contract account master data usually created?", "natural", ["Contract account master data is usually created and changed from the operational system using an interface."], []),
    ("M2C-11", "Which input data does billing evaluate to get its basis?", "natural", ["Billing uses meter reading results or load profiles to determine the evaluation basis for schema execution."], []),
    ("M2C-11", "How does a price change within a period get handled?", "terminology_mismatch", ["a price change causes the system to divide the total period into subperiods"], []),
    ("M2C-11", "schema execution", "keyword", ["All calculations required for rate creation are made during schema execution."], []),
    ("M2C-02", "Which tool produces the move-out confirmation letters?", "natural", ["Letters to the customer, such as welcome letters and move-out confirmations are created using the Print Workbench component."], []),
    ("M2C-02", "Who gets the installation allocated after the previous customer leaves?", "paraphrase", ["If a new customer moves into the installation, the installation is allocated to this customer's contract."], []),
    ("M2C-02", "Can I customise the move-in screen layout?", "natural", ["You can also configure the screen layout to suit your requirements."], []),
    ("M2C-02", "workflow monitoring move-in", "keyword", ["The SAP Business Workflow component (BC-BMT-WFM) enables you to monitor and configure the workflow processes."], []),
    ("M2C-11", "How does the system handle billing periods?", "sibling_ambiguous", ["Different billing periods are included in the various billing procedures."], ["M2C-12", "M2C-14"]),
    ("M2C-24", "installment plan processing", "sibling_ambiguous", ["The system creates an installment plan proposal based on the parameters set."], ["M2C-23", "M2C-25"]),
    ("M2C-02", "customer move process", "sibling_ambiguous", ["This component enables you to process a customer move-in or move-out."], ["M2C-03", "M2C-04"]),
]
DEV_ABSENT = [
    ("M2C-07", "What is the maximum number of selection criteria I can combine in EL31?", ["maximum number"]),
    ("M2C-07", "Which transaction code displays the AMI monitor directly?", ["EMON"]),
    ("M2C-07", "Who is allowed to start on-demand meter readings from the list?", ["allowed to"]),
    ("M2C-05", "How long does it take for equipment records to be created after goods receipt?", ["minutes"]),
    ("M2C-05", "Which vendors supply meters to utilities?", ["vendor"]),
    ("M2C-24", "What interest rate does the system apply to installment plans?", ["interest rate"]),
    ("M2C-24", "What is the minimum installment amount?", ["minimum"]),
    ("M2C-14", "Which transaction code starts bill reversal?", ["EA00"]),
    ("M2C-14", "Can bills be sent by e-mail instead of print?", ["e-mail"]),
    ("M2C-17", "How many contract accounts can one business partner have at most?", ["at most"]),
    ("M2C-11", "What is the default billing period length?", ["default"]),
    ("M2C-02", "How much does it cost to process a move-in?", ["cost"]),
]
DEV_NOT_INGESTED = [
    ("M2C-26", "Which dunning levels exist and what happens at each?", []),
    ("M2C-28", "What interfaces does a collection agency use to report back payments?", ["M2C-27"]),
    ("M2C-29", "What triggers the shut-off of electricity supply?", []),
    ("M2C-23", "When is a payment deferral appropriate for a debtor?", ["M2C-24"]),
    ("M2C-21", "What is the difference between clearing types?", ["M2C-20"]),
    ("M2C-19", "Where do I see incoming payments that were not yet assigned?", ["M2C-22", "M2C-20"]),
    ("M2C-06", "How do meter reading orders get created and printed?", ["M2C-07", "M2C-08"]),
    ("M2C-12", "How can billing be started for many contracts at once?", ["M2C-11"]),
]
DEV_UNRESOLVED = [
    ("M2C-18", "What properties does a contract account entity have in SAP?"),
    ("M2C-13", "How are budget billing amounts calculated per period?"),
    ("M2C-16", "Which reports compare billing and invoicing volumes?"),
    ("M2C-01", "Which master data must exist for a connection object?"),
]
DEV_OOD = ["What is the weather in Mumbai today?", "Summarise the plot of Hamlet.", "How do I configure sales order pricing in SAP S/4HANA?", "Explain what a Kubernetes pod is.",
           "How do I file income tax returns in India?", "What is the best way to learn the guitar?", "How do I set up a SAP Concur expense report?", "Convert 100 miles to kilometres."]

TEST_ANS = [
    ("M2C-07", "How do I find out which readings failed to post after an upload?", "terminology_mismatch", ["display the successfully and unsuccessfully posted meter reading documents after uploading discrete meter reading data"], []),
    ("M2C-07", "Does starting from premises show billing orders?", "entity", ["Contract, Installation, Business Partner, or Premise"], []),
    ("M2C-07", "ISU_AMI_1 prerequisite", "rare_term", ["Advanced Metering Infrastructure ( ISU_AMI_1 )"], []),
    ("M2C-07", "What is the purpose of EL32?", "paraphrase", ["monitor meter reading data and trigger automatic follow-on processing for selected meter reading orders"], []),
    ("M2C-07", "Which menu path leads to the reading monitoring transactions?", "section_specific", ["Utilities Industry menu under Device Management > Meter Reading > Monitoring"], []),
    ("M2C-07", "summarized list grouped by date", "keyword", ["At first the system displays a summarized list grouped by date (meter reading date, billing date)"], []),
    ("M2C-05", "What does the device category correspond to in the standard system?", "natural", ["Name in IS-U: Device Category; From Component: Logistics Basic Data (LO-MD); Name in Standard System: Material"], []),
    ("M2C-05", "Does the equipment number change between components?", "natural", ["The equipment number is the same throughout the system."], []),
    ("M2C-05", "How can scrapped or sold meters be handled in the flow of devices?", "terminology_mismatch", ["Function: Outward Movement (such as scrapping or sales); Component: Goods Issue and Return Delivery from MM-IM"], []),
    ("M2C-05", "What does the See Also list say about equipment?", "section_specific", ["PM: Equipment"], []),
    ("M2C-05", "advanced metering infrastructure information", "keyword", ["you can find more information under Advanced Metering Infrastructure"], []),
    ("M2C-05", "Which technical data does device management cover?", "paraphrase", ["This component manages technical data, installations, meter readings, and the inspection of devices."], []),
    ("M2C-24", "How is the installment amount worked out from the rounding amount and the number of installments?", "multi_concept", ["The installment amount is calculated from the total sum of the original receivables, the rounding amount, and the number of installments."], []),
    ("M2C-24", "What makes the system split interest across all due dates?", "terminology_mismatch", ["If you set the Distribute indicator, the interest and charges are distributed over all of the due dates."], []),
    ("M2C-24", "In which situation should I create an installment plan?", "natural", ["The business partner is unable to meet his/her payment obligations in accordance with the usual payment rules."], []),
    ("M2C-24", "What default values can I copy into the first screen?", "paraphrase", ["You can either copy default values to the initial screen using the Installment Plan Type or enter the installment plan parameters manually."], []),
    ("M2C-24", "event 3000", "entity", ["by defining event 3000 accordingly"], []),
    ("M2C-24", "Which balances are shown at the bottom right of the proposal?", "section_specific", ["a table appears with the most important account balances (such as open amount, due amount, installment plan, credit)"], []),
    ("M2C-24", "inflation surcharge", "rare_term", ["Create or delete an installment plan surcharge and/or an inflation surcharge"], []),
    ("M2C-14", "What must exist before billing documents can be invoiced?", "natural", ["Billing documents from the Contract Billing (IS-U-BI) component, or budget billing plans, which are managed in the Budget Billing Plan component must exist if billing is to take place."], []),
    ("M2C-14", "How are several contracts put on one bill?", "paraphrase", ["The contracts of a contract account are grouped together in invoicing for the joint bill."], []),
    ("M2C-14", "Which function lets me simulate a bill without posting?", "natural", ["simulate the bill using the Print Document Display function"], []),
    ("M2C-14", "What does bill reversal create in FI-CA?", "entity", ["you create a reverse document in FI-CA"], []),
    ("M2C-14", "output type print parameter", "keyword", ["you specify the output type as a print parameter"], []),
    ("M2C-14", "invoicing and contract accounting link", "multi_concept", ["Invoicing creates the link to contract accounting and provides the basis for bill creation."], []),
    ("M2C-17", "What can be defined for each business partner in the account record?", "natural", ["you can define, for each business partner, the procedures that apply when posting and processing the line items"], []),
    ("M2C-17", "Are changes to contract account master data recorded?", "paraphrase", ["The system logs changes to master data."], []),
    ("M2C-17", "How are insurance contracts allocated to contract accounts?", "section_specific", ["Each contract is only assigned to one contract account, however one contract account may have several contracts assigned to it."], []),
    ("M2C-17", "What are one-time accounts an exception to?", "entity", ["This does not apply to one-time accounts."], []),
    ("M2C-17", "open item basis", "keyword", ["Contract accounts tend to be managed on an open item basis."], []),
    ("M2C-17", "Which tax types can a public sector contract account cover?", "terminology_mismatch", ["(property tax, income tax, and so on)"], []),
    ("M2C-11", "Which master data may change during a billing period?", "natural", ["All master and billing master data can change during a billing period."], []),
    ("M2C-11", "How does billing split the consumption for subperiods?", "paraphrase", ["The system also divides the total consumption, which produces the corresponding partial amount."], []),
    ("M2C-11", "load profiles", "rare_term", ["Billing uses meter reading results or load profiles"], []),
    ("M2C-02", "Which activities can the system trigger automatically at move-out?", "natural", ["create a final bill for the move-out customer."], []),
    ("M2C-02", "Can I process a move-in completely in a single step?", "paraphrase", ["process the entire transaction immediately and in full."], []),
    ("M2C-02", "How are workflow processes for moves monitored?", "natural", ["enables you to monitor and configure the workflow processes"], []),
    ("M2C-02", "business partner and contract account for a new tenant", "multi_concept", ["you can create a business partner and contract account for the customer, or select existing ones."], []),
    ("M2C-11", "billing procedure basics", "sibling_ambiguous", ["Billing uses meter reading results or load profiles to determine the evaluation basis for schema execution."], ["M2C-12"]),
    ("M2C-14", "invoicing", "sibling_ambiguous", ["Invoicing creates the link to contract accounting and provides the basis for bill creation."], ["M2C-16", "M2C-11"]),
    ("M2C-17", "contract account overview", "sibling_ambiguous", ["This component enables you to create and manage contract account master data."], ["M2C-18"]),
]
TEST_ABSENT = [
    ("M2C-07", "What is the maximum date range for EL31 selections?", ["maximum"]),
    ("M2C-07", "Which transaction code lists meter reading orders by status?", ["EL28"]),
    ("M2C-07", "Can I export the monitoring list to a spreadsheet?", ["spreadsheet"]),
    ("M2C-05", "How many device categories does the standard system ship with?", ["ship"]),
    ("M2C-05", "Who is responsible for scrapping a defective meter?", ["responsible"]),
    ("M2C-24", "What is the default installment interval?", ["default interval"]),
    ("M2C-24", "Does an installment plan stop dunning?", ["dunning"]),
    ("M2C-14", "How long are print documents kept?", ["retention"]),
    ("M2C-14", "Which tax is shown on the bill?", ["tax"]),
    ("M2C-17", "What is the maximum length of a contract account number?", ["maximum length"]),
    ("M2C-11", "Which transaction starts a single billing run?", ["EA11"]),
    ("M2C-02", "Can a move-in be reversed after it was saved?", ["revers"]),
]
TEST_NOT_INGESTED = [
    ("M2C-26", "What is the sequence of dunning notices sent to a late payer?", []),
    ("M2C-27", "Which receivables can be submitted to an external collector?", ["M2C-28"]),
    ("M2C-29", "What steps restore supply after a disconnection?", []),
    ("M2C-25", "How can I shorten or extend an existing instalment arrangement?", ["M2C-24", "M2C-23"]),
    ("M2C-20", "How is the clearing control configured for incoming payments?", ["M2C-21"]),
    ("M2C-22", "How are lockbox or cash desk payments recorded?", ["M2C-19"]),
    ("M2C-09", "What is the difference between the estimation methods for missing readings?", ["M2C-08"]),
    ("M2C-03", "What do I need to do to set up a new customer in a house that was vacant?", ["M2C-02"]),
]
TEST_UNRESOLVED = [
    ("M2C-18", "What attributes describe a contract account as an object?"),
    ("M2C-13", "How is the monthly instalment for budget billing determined?"),
    ("M2C-16", "How can I analyse invoicing runs over time?"),
    ("M2C-01", "How are connection objects and premises structured?"),
]
TEST_OOD = ["What time does the sun set in Paris?", "Give me a recipe for vegetable curry.", "How do I apply conditional formatting in Excel?", "How does public key cryptography work?",
            "How do I configure SAP HANA database backups?", "Who painted the Mona Lisa?", "How should I prepare for a job interview?", "Translate good morning into Spanish."]

PREREG = {"declared_in": "data/phase10_contract.md", "declared_before_experiments": True, "no_tuning_on_test": True, "test_evaluated_with_the_configuration_selected_on_dev_only": True,
          "phase8_and_phase9_sets_are_regression_references_only": True}


def build(prefix, ans, absent, not_ing, unres, ood, recs, card_words, prior, others):
    qs, problems = [], []
    n = 0

    def add(**kw):
        nonlocal n
        n += 1
        qs.append({"id": f"{prefix}-{n:03d}", "authorship": "AI coding assistant (not blind; not a domain expert; design-aware of Phase 9 failures)", "authored_phase": 10, "authored_on": AUTHORED_ON, **kw})
    for sid, q, facet, ev, acc in ans:
        text = B9.norm(recs[sid]["text"])
        for e in ev:
            if B9.norm(e) not in text:
                problems.append((sid, q, "evidence not verbatim", e))
        add(query=q, type="answerable", facet=facet, answerability="answerable_from_local_page", gold_source_id=sid, gold_doc_id=recs[sid]["doc_id"], acceptable_source_ids=acc, evidence=ev,
            expected_status="answered", notes=("sibling ambiguity by design" if facet == "sibling_ambiguous" else ""))
    for sid, q, terms in absent:
        text = B9.norm(recs[sid]["text"]).lower()
        for t in terms:
            if t.lower() in text:
                problems.append((sid, q, "absent term present", t))
        add(query=q, type="absent_detail", facet="natural", answerability="not_answerable_detail_absent_from_page", gold_source_id=sid, gold_doc_id=recs[sid]["doc_id"], acceptable_source_ids=[],
            evidence=[], absent_terms=terms, expected_status="insufficient_context", notes="topic is on the page, the asked detail is not")
    for sid, q, acc in not_ing:
        add(query=q, type="not_ingested", facet="natural", answerability="not_answerable_page_not_in_local_corpus", gold_source_id=sid, gold_doc_id=None, acceptable_source_ids=acc, evidence=[],
            expected_status="page_not_ingested", notes="page exists on SAP Help but is not in the local corpus")
    for sid, q in unres:
        add(query=q, type="unresolved_identity", facet="natural", answerability="not_answerable_identity_unresolved", gold_source_id=sid, gold_doc_id=None, acceptable_source_ids=[], evidence=[],
            expected_status="unresolved_identity", notes="conflicting or identity-only card (7C)")
    for q in ood:
        add(query=q, type="out_of_domain", facet="natural", answerability="out_of_domain", gold_source_id=None, gold_doc_id=None, acceptable_source_ids=[], evidence=[],
            expected_status="out_of_domain", notes="")
    for q in qs:
        w = B9.words(q["query"])
        if " ".join(w) in prior or " ".join(w) in others:
            problems.append((q["id"], q["query"], "exact duplicate of an earlier/other set", ""))
        if any(B9.jaccard(w, p.split()) >= 0.8 for p in prior | others):
            problems.append((q["id"], q["query"], "near duplicate (Jaccard>=0.8)", ""))
        if q["type"] != "out_of_domain":
            worst = max((B9.longest_shared_run(w, cw), sid) for sid, cw in card_words.items())
            q["max_card_phrase_run_words"] = worst[0]
            if worst[0] > 3:
                problems.append((q["id"], q["query"], f"shares {worst[0]} contiguous words with card {worst[1]}", ""))
    if len({" ".join(B9.words(q["query"])) for q in qs}) != len(qs):
        problems.append(("-", "-", "duplicate inside the set", ""))
    return qs, problems


def main() -> int:
    recs = {r["source_ids"][0]: r for r in PC.load_records()}
    cards = json.loads((ROOT / "data" / "retrieval_units.json").read_text(encoding="utf-8"))["units"]
    card_words = {c["source_id"]: B9.words(c["embedding_text"]) for c in cards}
    B9.PRIOR_SETS = PRIOR
    prior = B9.prior_queries()
    dev_text = {" ".join(B9.words(x[1])) for x in DEV_ANS + DEV_ABSENT + DEV_NOT_INGESTED + DEV_UNRESOLVED} | {" ".join(B9.words(x)) for x in DEV_OOD}
    test_text = {" ".join(B9.words(x[1])) for x in TEST_ANS + TEST_ABSENT + TEST_NOT_INGESTED + TEST_UNRESOLVED} | {" ".join(B9.words(x)) for x in TEST_OOD}
    dev, p1 = build("P10D", DEV_ANS, DEV_ABSENT, DEV_NOT_INGESTED, DEV_UNRESOLVED, DEV_OOD, recs, card_words, prior, test_text)
    test, p2 = build("P10T", TEST_ANS, TEST_ABSENT, TEST_NOT_INGESTED, TEST_UNRESOLVED, TEST_OOD, recs, card_words, prior, dev_text)
    if p1 or p2:
        for p in p1 + p2:
            print("PROBLEM", p)
        return 1
    corpus_sha = json.loads((PC.CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))["corpus_sha256"]
    freeze = {"statement": "both files were written before any Phase 10 experiment; the TEST file is sealed and is evaluated once with the configuration selected on DEV", "files": {}}
    for name, qs, role in (("dev", dev, "design and selection of candidates"), ("test", test, "sealed; one evaluation with the DEV-selected configuration")):
        counts = {t: sum(1 for q in qs if q["type"] == t) for t in ("answerable", "absent_detail", "not_ingested", "unresolved_identity", "out_of_domain")}
        payload = {"schema_version": 1, "description": f"Phase 10 {name.upper()} queries - {role}",
                   "authorship": {"authored_by": "AI coding assistant, after reading the 7 ingested pages; not a human domain expert; no LLM generation at runtime",
                                  "caveat": "not blind; design-aware of Phase 9 failures; n is small so every rate has a wide interval", "written_before_experiments": True,
                                  "labels_changed_after_retrieval": False, "authored_on": AUTHORED_ON},
                   "preregistered": PREREG, "counts": counts, "facet_counts": {f: sum(1 for q in qs if q["facet"] == f) for f in sorted({q["facet"] for q in qs})},
                   "corpus_sha256": corpus_sha, "queries": qs}
        data = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        path = EVAL / f"phase10_{name}_queries.json"
        path.write_text(data, encoding="utf-8")
        freeze["files"][name] = {"file": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(data.encode("utf-8")).hexdigest(), "queries": len(qs), "counts": counts}
        print(f"wrote {path.relative_to(ROOT)}: {len(qs)} {counts}")
    FREEZE.write_text(json.dumps(freeze, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
