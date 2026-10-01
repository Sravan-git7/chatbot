#!/usr/bin/env python3
"""Phase 4 / stage 6: write the deterministic card-level retrieval evaluation set `data/evaluation/card_retrieval_questions.json`.

The questions were written by hand BEFORE any retrieval was run, using only the text of the 29 reference cards
(title, category, What it covers, Meter-to-Cash relevance). No LLM was used. Every expected source is backed by an
`evidence` quote, and this script refuses to write the file unless each quote occurs verbatim in that card's `full_text`
(`data/retrieval_units.json`), so the set cannot drift away from the cards.

Fields: question_id, question, question_type, expected_source_ids (the card(s) whose text answers the question; a hit
is ANY of them), also_relevant_source_ids (other cards that are plausibly relevant; NOT counted in the metrics, shown for
interpretation only), ambiguous (true if another card plausibly competes or several cards are expected), evidence, notes.
Questions needing SAP page content that is not on the cards are deliberately absent.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m2c_common import ROOT, UNITS_PATH  # noqa: E402

OUT = ROOT / "data" / "evaluation" / "card_retrieval_questions.json"

# (id, type, question, expected, also_relevant, ambiguous, [(source, quote)], notes)
Q: List[Any] = [
    # --- exact service/topic names (the title as the user would type it)
    ("Q01", "exact_title", "Move-In Process", ["M2C-03"], ["M2C-02", "M2C-10"], False, [("M2C-03", "Move-In Process")], "Title of card 03; cards 02 and 10 also concern move-in."),
    ("Q02", "exact_title", "Move-Out Process", ["M2C-04"], ["M2C-02"], False, [("M2C-04", "Move-Out Process")], "Title of card 04."),
    ("Q03", "exact_title", "Automatic Billing", ["M2C-12"], ["M2C-11"], False, [("M2C-12", "Automatic Billing")], "Title of card 12."),
    ("Q04", "exact_title", "Budget Billing Plan", ["M2C-13"], ["M2C-15"], True, [("M2C-13", "Budget Billing Plan")], "Title of card 13; card 15 'Processing Budget Billing Plans' is a near-title competitor."),
    ("Q05", "exact_title", "Clearing Types", ["M2C-21"], ["M2C-20"], False, [("M2C-21", "Clearing Types")], "Title of card 21."),
    ("Q06", "exact_title", "FI-CA Dunning", ["M2C-26"], [], False, [("M2C-26", "FI-CA Dunning")], "Title of card 26."),
    ("Q07", "exact_title", "Installment Plan Overview", ["M2C-23"], ["M2C-24", "M2C-25"], False, [("M2C-23", "Installment Plan Overview")], "Title of card 23."),
    ("Q08", "exact_title", "Collection Agency APIs and Enterprise Services", ["M2C-28"], ["M2C-27"], False, [("M2C-28", "Collection Agency APIs and Enterprise Services")], "Title of card 28."),
    ("Q09", "exact_title", "Reading Meters", ["M2C-06"], ["M2C-07", "M2C-05"], False, [("M2C-06", "Reading Meters")], "Title of card 06."),
    ("Q10", "exact_title", "Contract Accounts Overview", ["M2C-17"], ["M2C-18"], True, [("M2C-17", "Contract Accounts Overview")], "Title of card 17; card 18 'Contract Account Business Object' is a near-title competitor."),
    ("Q11", "exact_title", "Disconnection/Reconnection of a Utility Installation", ["M2C-29"], [], False, [("M2C-29", "Disconnection/Reconnection of a Utility Installation")], "Title of card 29."),
    # --- semantic descriptions (paraphrase of 'What it covers')
    ("Q12", "semantic", "Which reference explains how billing results become invoices, print documents and postings in FI-CA?", ["M2C-14"], ["M2C-11"], False, [("M2C-14", "how billing results become invoices, print documents and FI-CA postings")], "Card 14 covers exactly this."),
    ("Q13", "semantic", "What explains estimating a reading when the meter reading is missing or unavailable?", ["M2C-08"], ["M2C-09"], True, [("M2C-08", "estimation when readings are missing, unavailable or unsuitable for direct use")], "Card 08; card 09 (estimation procedure details) is a close competitor."),
    ("Q14", "semantic", "How are incoming payment amounts assigned to open items?", ["M2C-20"], ["M2C-21", "M2C-19"], False, [("M2C-20", "incoming-payment amounts are assigned to open items using FI-CA clearing control")], "Card 20."),
    ("Q15", "semantic", "Which topic covers releasing, submitting, processing and recalling receivables handled by collection agencies?", ["M2C-27"], ["M2C-28"], False, [("M2C-27", "releasing, submitting, processing and recalling receivables handled by collection agencies")], "Card 27."),
    ("Q16", "semantic", "How are source receivables redistributed into scheduled installment receivables?", ["M2C-23"], ["M2C-24"], False, [("M2C-23", "source receivables are redistributed into scheduled installment receivables")], "Card 23."),
    ("Q17", "semantic", "Temporary interruption and restoration of utility supply for collection or technical reasons", ["M2C-29"], [], False, [("M2C-29", "temporary interruption and restoration of utility supply for collection or technical reasons")], "Card 29."),
    ("Q18", "semantic", "How are notifications of incoming payments from external cash desks integrated into FI-CA?", ["M2C-22"], ["M2C-19"], False, [("M2C-22", "integration of incoming-payment notifications from external cash desks into FI-CA")], "Card 22."),
    ("Q19", "semantic", "Which source lists Business Partner, Contract Account, Contract, Point of Delivery, Connection Object, Premise, Device Location, Installation and Device?", ["M2C-01"], ["M2C-17", "M2C-18"], False, [("M2C-01", "Business Partner, Contract Account, Contract, Point of Delivery, Connection Object, Premise, Device Location, Installation and Device")], "Card 01 names these objects."),
    ("Q20", "semantic", "What covers the creation of the customer-service relationship for a utility installation?", ["M2C-03"], ["M2C-02"], True, [("M2C-03", "creation of the customer-service relationship for a utility installation")], "Card 03; card 04 mentions the opposite (termination) of the same relationship."),
    ("Q21", "semantic", "What covers the termination of the customer-service relationship and related final processing?", ["M2C-04"], [], False, [("M2C-04", "termination of the customer-service relationship and related final processing")], "Card 04."),
    # --- Meter-to-Cash relevance wording
    ("Q22", "m2c_relevance", "Which source is important for estimated-bill and catch-up-bill reasoning?", ["M2C-08"], ["M2C-09"], False, [("M2C-08", "estimated-bill and catch-up-bill reasoning")], "Relevance line of card 08."),
    ("Q23", "m2c_relevance", "Which reference is critical for distinguishing billing document, invoicing result, customer bill and FI-CA document?", ["M2C-14"], [], False, [("M2C-14", "distinguishing billing document, invoicing result, customer bill and FI-CA document")], "Relevance line of card 14."),
    ("Q24", "m2c_relevance", "Which source teaches that payment receipt and open-item clearing are distinct steps?", ["M2C-20"], [], False, [("M2C-20", "payment receipt and open-item clearing are distinct steps")], "Relevance line of card 20."),
    ("Q25", "m2c_relevance", "Which source is the core reference for collections escalation logic within Meter-to-Cash?", ["M2C-26"], ["M2C-27"], False, [("M2C-26", "collections escalation logic")], "Relevance line of card 26."),
    ("Q26", "m2c_relevance", "Why can interim or budget amounts affect the customer balance independently of final consumption billing?", ["M2C-13"], ["M2C-15"], True, [("M2C-13", "interim/budget amounts can affect the customer balance independently of final consumption billing")], "Relevance line of card 13; card 15 is budget billing in invoicing."),
    ("Q27", "m2c_relevance", "Which card preserves the distinction between delinquency and disconnect eligibility?", ["M2C-29"], ["M2C-26"], False, [("M2C-29", "distinction between delinquency and disconnect eligibility")], "Relevance line of card 29."),
    ("Q28", "m2c_relevance", "Which source covers modern API and service integration beyond file-based exchanges?", ["M2C-28"], [], False, [("M2C-28", "modern API/service integration knowledge beyond file-based exchanges")], "Relevance line of card 28."),
    ("Q29", "m2c_relevance", "Which source is useful for differentiating payment-lot, cash-desk, account-maintenance and payment-run clearing contexts?", ["M2C-21"], ["M2C-20"], False, [("M2C-21", "payment-lot, cash-desk, account-maintenance and payment-run clearing contexts")], "Relevance line of card 21."),
    ("Q30", "m2c_relevance", "Which source is useful for operational monitoring, KPIs and exception-management of periodic billing and invoicing?", ["M2C-16"], ["M2C-07"], True, [("M2C-16", "operational monitoring, KPIs and exception-management use cases")], "Relevance line of card 16; card 07 is exception monitoring for meter-reading results."),
    ("Q31", "m2c_relevance", "Which source helps with exception monitoring and support or troubleshooting scenarios for meter-reading results?", ["M2C-07"], ["M2C-16"], True, [("M2C-07", "exception monitoring and support/troubleshooting scenarios")], "Relevance line of card 07; card 16 also mentions exception management."),
    # --- category wording (a card is expected; several cards share each category)
    ("Q32", "category", "Which card is in the Disconnection & Reconnection category?", ["M2C-29"], [], False, [("M2C-29", "Category: Disconnection & Reconnection")], "The only card in this category."),
    ("Q33", "category", "Which cards belong to the Dunning & Collections category?", ["M2C-26", "M2C-27", "M2C-28"], [], True, [("M2C-26", "Category: Dunning & Collections"), ("M2C-27", "Category: Dunning & Collections"), ("M2C-28", "Category: Dunning & Collections")], "Three cards share the category; any of them is a hit, and coverage of all three is also reported."),
    ("Q34", "category", "Which cards belong to Payment Arrangements / Installment Plans?", ["M2C-23", "M2C-24", "M2C-25"], [], True, [("M2C-23", "Category: Payment Arrangements / Installment Plans"), ("M2C-24", "Category: Payment Arrangements / Installment Plans"), ("M2C-25", "Category: Payment Arrangements / Installment Plans")], "Three cards share the category."),
    ("Q35", "category", "Which cards are in the Payments & Clearing category?", ["M2C-19", "M2C-20", "M2C-21", "M2C-22"], [], True, [("M2C-19", "Category: Payments & Clearing"), ("M2C-20", "Category: Payments & Clearing"), ("M2C-21", "Category: Payments & Clearing"), ("M2C-22", "Category: Payments & Clearing")], "Four cards share the category."),
    # --- distinctive terminology
    ("Q36", "distinctive_term", "extrapolation and interpolation", ["M2C-09"], ["M2C-08"], False, [("M2C-09", "extrapolation/interpolation")], "Term appears only on card 09."),
    ("Q37", "distinctive_term", "installation, rate type, schema, operand and price", ["M2C-12"], ["M2C-11"], False, [("M2C-12", "installation, rate type, schema, operand, price and billing relationships")], "Term list on card 12 (card 11 mentions rate/schema)."),
    ("Q38", "distinctive_term", "dunning notices and dunning activities for overdue items", ["M2C-26"], [], False, [("M2C-26", "overdue items, dunning notices and dunning activities")], "Card 26."),
    ("Q39", "distinctive_term", "payment clarification", ["M2C-19"], ["M2C-20"], False, [("M2C-19", "payment clarification")], "Term appears only on card 19."),
    ("Q40", "distinctive_term", "monitoring meter-reading results across business objects and organizational criteria", ["M2C-07"], ["M2C-06"], False, [("M2C-07", "across business objects and organizational criteria")], "Card 07."),
    ("Q41", "distinctive_term", "parent topic for devices and technical installations", ["M2C-05"], ["M2C-01"], False, [("M2C-05", "Parent topic for devices, technical installations")], "Card 05."),
    ("Q42", "distinctive_term", "subledger processing", ["M2C-17"], ["M2C-18"], False, [("M2C-17", "subledger processing")], "Term appears only on card 17."),
    ("Q43", "distinctive_term", "control role of the contract account for postings, payments and dunning", ["M2C-18"], ["M2C-17"], True, [("M2C-18", "control role for postings, payments and dunning")], "Card 18; card 17 also ties contract accounts to payments and dunning."),
    # --- cross-card ambiguity
    ("Q44", "ambiguous", "How does meter reading data take part in the move-in process?", ["M2C-10"], ["M2C-03", "M2C-06"], True, [("M2C-10", "how meter-reading data participates in the move-in process")], "Card 10; cards 03 (move-in) and 06 (meter reading) each match half of the question."),
    ("Q45", "ambiguous", "How are budget billing plans treated in invoicing?", ["M2C-15"], ["M2C-13", "M2C-14"], True, [("M2C-15", "treatment of budget billing plans in the invoicing process")], "Card 15; cards 13 and 14 match half of the question."),
    ("Q46", "ambiguous", "Explain the estimation procedure for meter readings", ["M2C-08", "M2C-09"], [], True, [("M2C-08", "Explains estimation"), ("M2C-09", "Deeper reference for estimation procedures")], "Both estimation cards are acceptable; any is a hit."),
    ("Q47", "ambiguous", "Overview of starting and ending utility service", ["M2C-02"], ["M2C-03", "M2C-04"], True, [("M2C-02", "customer service lifecycle around starting and ending utility service")], "Card 02; cards 03 and 04 are the detailed halves."),
    ("Q48", "ambiguous", "How are installment plans created?", ["M2C-24"], ["M2C-23", "M2C-25"], True, [("M2C-24", "creation of installment plans")], "Card 24; cards 23 and 25 are in the same family."),
    ("Q49", "ambiguous", "What is needed for final billing when a customer moves out?", ["M2C-04"], ["M2C-02"], True, [("M2C-04", "final meter reading, final billing and downstream account effects")], "Card 04; card 02 also mentions final billing."),
    ("Q50", "ambiguous", "How does a collection agency get involved when receivables stay unpaid?", ["M2C-27", "M2C-28"], ["M2C-26"], True, [("M2C-27", "receivables handled by collection agencies"), ("M2C-28", "external collection agencies")], "Cards 27 and 28 concern collection agencies; any is a hit."),
]


def build(units: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    by_id = {u["source_id"]: u for u in units}
    out = []
    for qid, typ, question, expected, also, ambiguous, evidence, notes in Q:
        for sid in list(expected) + list(also):
            if sid not in by_id:
                raise ValueError(f"{qid}: unknown source {sid}")
        for sid, quote in evidence:
            if quote not in by_id[sid]["full_text"]:
                raise ValueError(f"{qid}: evidence quote {quote!r} not found in {sid}")
        if {s for s, _ in evidence} != set(expected):
            raise ValueError(f"{qid}: evidence must cover exactly the expected sources")
        out.append({"question_id": qid, "question": question, "question_type": typ, "expected_source_ids": list(expected),
                    "also_relevant_source_ids": list(also), "ambiguous": ambiguous,
                    "evidence": [{"source_id": s, "quote": q} for s, q in evidence], "notes": notes})
    ids = [q["question_id"] for q in out]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate question ids")
    return {"schema_version": 1,
            "description": "Card-level retrieval questions derived ONLY from the text of the 29 reference cards; written before any retrieval was run; no LLM involved.",
            "source_units": "data/retrieval_units.json", "question_count": len(out), "questions": out}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--units", default=str(UNITS_PATH))
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    units = json.loads(Path(a.units).read_text(encoding="utf-8"))["units"]
    payload = build(units)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {a.out}: {payload['question_count']} questions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
