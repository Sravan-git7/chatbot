#!/usr/bin/env python3
"""Phase 5A: write the independent query set `data/evaluation/independent_queries.json`.

The queries were written by hand (by the AI coding agent working on this repository, in this file - NOT produced by an automated
LLM generation pipeline, and NOT written by a human domain expert) to sound like real users, NOT copied from the cards, and were
written BEFORE any Phase 5 retrieval was run. Labels come from the card text only (no retrieval in the loop, no SAP knowledge beyond
the cards). A human-written or real-user query set would be a stronger test; see the Phase 5 report limitations. Each query has an
expected card, a rationale and a verbatim `evidence` quote from the expected card's `full_text`; this script refuses to write
the file unless every quote is found and the independence rules hold:

  * no query equals a Phase-4 evaluation question (case-insensitive);
  * no query shares a run of more than MAX_VERBATIM_WORDS consecutive words with the text of its expected card(s);
  * `max_verbatim_overlap_words` is stored for each query so the independence is auditable.

Difficulty (assigned by hand, with these criteria, before any run):
  easy   - the query contains a term that identifies the topic (appears in only one or two cards) or the intent is unmistakable;
  medium - the intent is clear but the vocabulary differs from the card, or a sibling card is plausible;
  hard   - the vocabulary differs AND a sibling card is plausible, or the query is very short / generic / compound.
Length buckets are computed from the word count: very_short 1-4, short 5-7, long 8-20, very_long >20.
`expected_source_ids`: a hit is ANY of them. `also_relevant_source_ids` are plausible competitors, not counted in the metrics.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m2c_common import ROOT, UNITS_PATH  # noqa: E402

OUT = ROOT / "data" / "evaluation" / "independent_queries.json"
PHASE4_QUESTIONS = ROOT / "data" / "evaluation" / "card_retrieval_questions.json"
MAX_VERBATIM_WORDS = 3
TYPES = ("natural", "keyword", "paraphrase", "entity", "ambiguous")

# (id, type, difficulty, query, expected, also_relevant, ambiguous, rationale, [(source, evidence quote)])
Q: List[Any] = [
    ("P5-01", "natural", "medium", "Where do I start if I need to understand how customers, premises and meters fit together in the system?", ["M2C-01"], ["M2C-05", "M2C-17"], True,
     "Card 01 is the foundation card for the master-data objects (business partner, premise, installation, device) and their relationships.", [("M2C-01", "Foundation source for Business Partner, Contract Account, Contract, Point of Delivery")]),
    ("P5-02", "natural", "medium", "What happens in the system when a new tenant gets connected?", ["M2C-03"], ["M2C-02", "M2C-10"], True,
     "Starting service for a new customer is the move-in process (creation of the customer-service relationship).", [("M2C-03", "creation of the customer-service relationship for a utility installation")]),
    ("P5-03", "natural", "medium", "A customer is leaving the property. What needs to happen with their last bill and meter reading?", ["M2C-04"], ["M2C-02"], True,
     "Card 04 names service stop, final meter reading and final billing; card 02 also mentions final billing.", [("M2C-04", "service stop, final meter reading, final billing and downstream account effects")]),
    ("P5-04", "natural", "easy", "Why did a customer get a bill based on an estimate instead of an actual reading?", ["M2C-08"], ["M2C-09"], False,
     "Card 08 covers estimation when readings are missing or unusable and estimated-bill reasoning.", [("M2C-08", "estimation when readings are missing, unavailable or unsuitable for direct use")]),
    ("P5-05", "natural", "hard", "How do I follow up on customers who have not paid on time?", ["M2C-26"], ["M2C-27", "M2C-29"], True,
     "Overdue items and the escalation of collections are the subject of the dunning card; later-stage cards are siblings.", [("M2C-26", "overdue items, dunning notices and dunning activities")]),
    ("P5-06", "natural", "medium", "Can I spread a large overdue balance over several payments?", ["M2C-23"], ["M2C-24"], True,
     "Redistributing receivables into scheduled instalments is defined on the installment plan overview card.", [("M2C-23", "source receivables are redistributed into scheduled installment receivables")]),
    ("P5-07", "natural", "medium", "Where can I find out how a payment that just arrived gets matched to what the customer owes?", ["M2C-20"], ["M2C-21", "M2C-19"], True,
     "Assigning incoming amounts to open items is the clearing-control card.", [("M2C-20", "incoming-payment amounts are assigned to open items using FI-CA clearing control")]),
    ("P5-08", "natural", "easy", "How is electricity supply switched off and back on when a customer doesn't pay?", ["M2C-29"], ["M2C-26"], False,
     "Interruption and restoration of supply for collection reasons is the disconnection/reconnection card.", [("M2C-29", "temporary interruption and restoration of utility supply for collection or technical reasons")]),
    ("P5-09", "natural", "medium", "Which topic explains how an invoice gets created after the bill has been calculated?", ["M2C-14"], ["M2C-11"], True,
     "Turning billing results into invoices is the invoicing procedure card; card 11 ends at billing results.", [("M2C-14", "how billing results become invoices, print documents and FI-CA postings")]),
    ("P5-10", "natural", "hard", "How can I keep an eye on meter reads that came in wrong or are stuck?", ["M2C-07"], ["M2C-06"], True,
     "Monitoring results and exception/troubleshooting scenarios belong to card 07; card 06 covers validation and correction.", [("M2C-07", "exception monitoring and support/troubleshooting scenarios")]),
    ("P5-11", "natural", "medium", "Is there a way to hand unpaid accounts over to an external debt collector?", ["M2C-27"], ["M2C-28"], True,
     "Submitting receivables to collection agencies is card 27; card 28 covers the technical integration.", [("M2C-27", "releasing, submitting, processing and recalling receivables handled by collection agencies")]),
    ("P5-12", "natural", "medium", "How do system interfaces to outside collection companies work?", ["M2C-28"], ["M2C-27"], True,
     "Integration mechanisms between FI-CA and external agencies are card 28.", [("M2C-28", "integration mechanisms between FI-CA and external collection agencies")]),
    ("P5-13", "natural", "hard", "What does a customer's financial account in the billing system control?", ["M2C-18"], ["M2C-17"], True,
     "The contract account's control role is described on card 18; card 17 is the overview.", [("M2C-18", "control role for postings, payments and dunning")]),
    ("P5-14", "natural", "medium", "How do customers pay a steady monthly amount instead of variable bills?", ["M2C-13"], ["M2C-15"], True,
     "Budget billing plans and periodic payment concepts are card 13.", [("M2C-13", "utility budget billing plans and periodic payment concepts")]),
    ("P5-15", "keyword", "hard", "budget billing", ["M2C-13", "M2C-15"], [], True,
     "Both budget-billing cards are equally valid answers to a bare two-word query.", [("M2C-13", "budget billing plans"), ("M2C-15", "budget billing plans")]),
    ("P5-16", "keyword", "easy", "extrapolation", ["M2C-09"], ["M2C-08"], False,
     "Extrapolation is named only on the estimation-procedure details card.", [("M2C-09", "extrapolation/interpolation")]),
    ("P5-17", "keyword", "medium", "open items", ["M2C-20"], ["M2C-21"], False,
     "Assignment of incoming amounts to open items is card 20.", [("M2C-20", "assigned to open items")]),
    ("P5-18", "keyword", "medium", "cash desk", ["M2C-22"], ["M2C-21"], True,
     "External cash desks are the subject of card 22; card 21 mentions cash-desk clearing contexts.", [("M2C-22", "incoming-payment notifications from external cash desks")]),
    ("P5-19", "keyword", "hard", "dunning", ["M2C-26"], ["M2C-27", "M2C-29", "M2C-17", "M2C-18"], True,
     "Card 26 is the primary dunning reference; several cards mention dunning in passing.", [("M2C-26", "Primary reference for FI-CA dunning")]),
    ("P5-20", "keyword", "hard", "meter estimation", ["M2C-08", "M2C-09"], [], True,
     "Two cards cover estimation; either answers the query.", [("M2C-08", "Explains estimation"), ("M2C-09", "Deeper reference for estimation procedures")]),
    ("P5-21", "keyword", "hard", "billing schema", ["M2C-11", "M2C-12"], [], True,
     "Schema is named on the billing procedure card (rate/schema calculation) and on the automatic billing card.", [("M2C-11", "rate/schema calculation"), ("M2C-12", "rate type, schema, operand, price")]),
    ("P5-22", "keyword", "hard", "installment plan display", ["M2C-25"], ["M2C-23", "M2C-24"], True,
     "Display and change functions are on card 25; cards 23 and 24 are in the same family.", [("M2C-25", "display/change functions")]),
    ("P5-23", "keyword", "easy", "delinquency", ["M2C-29"], [], False,
     "Delinquency is named only on the disconnection card.", [("M2C-29", "distinction between delinquency and disconnect eligibility")]),
    ("P5-24", "keyword", "hard", "reversal", ["M2C-22"], [], False,
     "Reversal scenarios are named only on the external cash desk card.", [("M2C-22", "real-time external payment and reversal scenarios")]),
    ("P5-25", "keyword", "medium", "KPIs", ["M2C-16"], ["M2C-07"], False,
     "KPIs are named only on the periodic billing/invoicing analysis card.", [("M2C-16", "operational monitoring, KPIs and exception-management use cases")]),
    ("P5-26", "keyword", "hard", "FI-CA document", ["M2C-14"], ["M2C-26"], True,
     "Card 14 is the one that distinguishes the FI-CA document from the billing document; FI-CA appears on many cards.", [("M2C-14", "customer bill and FI-CA document")]),
    ("P5-27", "paraphrase", "hard", "Explain how a household is registered as using a service point for the first time", ["M2C-03"], ["M2C-02", "M2C-10"], True,
     "First-time use of a utility installation by a customer is the move-in process.", [("M2C-03", "Explains the move-in process")]),
    ("P5-28", "paraphrase", "medium", "Stopping service for a customer and finishing up the account", ["M2C-04"], ["M2C-02"], True,
     "Ending the relationship with final processing is the move-out process.", [("M2C-04", "termination of the customer-service relationship and related final processing")]),
    ("P5-29", "paraphrase", "hard", "Calculating what to charge from usage figures using price tables", ["M2C-11"], ["M2C-12"], True,
     "The billing procedure goes from consumption data through rate calculation to billing results; card 12 covers the configuration elements.", [("M2C-11", "from consumption/profile data through rate/schema calculation to billing results")]),
    ("P5-30", "paraphrase", "medium", "What do I do when a meter cannot be read and a figure has to be guessed?", ["M2C-08"], ["M2C-09"], True,
     "Missing or unavailable readings lead to estimation.", [("M2C-08", "estimation when readings are missing, unavailable or unsuitable for direct use")]),
    ("P5-31", "paraphrase", "hard", "Filling gaps in usage data between two known readings", ["M2C-09"], ["M2C-08"], True,
     "Interpolation between known values is named on card 09 (estimation procedure details).", [("M2C-09", "extrapolation/interpolation")]),
    ("P5-32", "paraphrase", "medium", "Checking the quality of submitted consumption figures and fixing wrong ones before charging", ["M2C-06"], ["M2C-07"], True,
     "Validation/correction of results and their transfer toward billing is card 06.", [("M2C-06", "validation/correction and transfer of results toward billing")]),
    ("P5-33", "paraphrase", "hard", "Looking into money received from customers that can't be assigned", ["M2C-19"], ["M2C-20"], True,
     "Analysis and clarification of incoming payments is card 19; card 20 covers the assignment mechanism.", [("M2C-19", "analysis of incoming payments and payment clarification")]),
    ("P5-34", "paraphrase", "hard", "Different situations in which open amounts get settled against payments", ["M2C-21"], ["M2C-20"], True,
     "Clearing types across FI-CA processes are card 21.", [("M2C-21", "Reference for clearing types used across FI-CA processes")]),
    ("P5-35", "paraphrase", "hard", "Shop-counter payments from outside partners being posted immediately", ["M2C-22"], ["M2C-19"], True,
     "Real-time external payment notifications are card 22.", [("M2C-22", "real-time external payment and reversal scenarios")]),
    ("P5-36", "paraphrase", "medium", "Changing a payment agreement after it has been set up for a customer", ["M2C-25"], ["M2C-24"], True,
     "Maintenance of an arrangement after creation, including change functions, is card 25.", [("M2C-25", "maintenance and exception scenarios after an arrangement is created")]),
    ("P5-37", "paraphrase", "medium", "Setting up a new payment arrangement and checking whether the customer qualifies", ["M2C-24"], ["M2C-23"], True,
     "Creation, eligibility and setup are card 24.", [("M2C-24", "eligibility, setup and downstream clearing/dunning reasoning")]),
    ("P5-38", "paraphrase", "hard", "Dashboards for how well the bill runs are doing", ["M2C-16"], ["M2C-07"], True,
     "An analytical view of execution and status of periodic billing/invoicing is card 16.", [("M2C-16", "Modern analytical view of periodic billing/invoicing execution and status")]),
    ("P5-39", "entity", "easy", "Point of Delivery and Connection Object", ["M2C-01"], [], False,
     "Both objects are listed on the master-data foundation card.", [("M2C-01", "Point of Delivery, Connection Object, Premise")]),
    ("P5-40", "entity", "medium", "operand and rate type", ["M2C-12"], ["M2C-11"], True,
     "Rate type and operand are named on the automatic billing card.", [("M2C-12", "rate type, schema, operand, price")]),
    ("P5-41", "entity", "medium", "print documents", ["M2C-14"], [], False,
     "Print documents are named on the invoicing procedure card.", [("M2C-14", "invoices, print documents and FI-CA postings")]),
    ("P5-42", "entity", "hard", "technical installations and devices", ["M2C-05"], ["M2C-01"], True,
     "Card 05 is the parent topic for devices and technical installations; card 01 lists installation and device among master data.", [("M2C-05", "Parent topic for devices, technical installations")]),
    ("P5-43", "entity", "medium", "catch-up bill", ["M2C-08"], [], False,
     "Catch-up-bill reasoning is named on the estimation card.", [("M2C-08", "estimated-bill and catch-up-bill reasoning")]),
    ("P5-44", "entity", "easy", "SAP enterprise services for collection agencies", ["M2C-28"], ["M2C-27"], True,
     "Enterprise services for agency integration are card 28.", [("M2C-28", "Collection Agency APIs and Enterprise Services")]),
    ("P5-45", "entity", "medium", "recall of receivables", ["M2C-27"], ["M2C-28"], False,
     "Recalling receivables is part of the collection agency submission process.", [("M2C-27", "releasing, submitting, processing and recalling receivables")]),
    ("P5-46", "entity", "medium", "debt arrangement", ["M2C-23"], ["M2C-24", "M2C-25"], True,
     "Debt-arrangement concepts are named on the installment plan overview card.", [("M2C-23", "Core source for debt-arrangement concepts and future due dates")]),
    ("P5-47", "entity", "hard", "meter hardware and technical setup", ["M2C-05"], ["M2C-01"], True,
     "Physical metering assets and technical installations are the subject of the device management overview.", [("M2C-05", "how physical metering assets connect to the Meter-to-Cash chain")]),
    ("P5-48", "ambiguous", "hard", "What do I need to know about move-in?", ["M2C-03"], ["M2C-02", "M2C-10"], True,
     "Three cards concern move-in; card 03 is the process card.", [("M2C-03", "Explains the move-in process")]),
    ("P5-49", "ambiguous", "medium", "Explain budget billing in the invoicing context", ["M2C-15"], ["M2C-13", "M2C-14"], True,
     "Card 15 treats budget billing within invoicing; cards 13 and 14 each match half of the query.", [("M2C-15", "treatment of budget billing plans in the invoicing process")]),
    ("P5-50", "ambiguous", "medium", "How do installment plans work?", ["M2C-23"], ["M2C-24", "M2C-25"], True,
     "Card 23 defines installment plans; cards 24 and 25 cover creating and maintaining them.", [("M2C-23", "Defines installment plans")]),
    ("P5-51", "ambiguous", "hard", "How is meter reading handled?", ["M2C-06"], ["M2C-05", "M2C-07", "M2C-08", "M2C-10"], True,
     "Card 06 is the core meter-read lifecycle card; four sibling cards concern meter reading from other angles.", [("M2C-06", "Core source for teaching meter-read lifecycle")]),
    ("P5-52", "ambiguous", "hard", "Payments that come in from customers", ["M2C-19", "M2C-20", "M2C-22"], ["M2C-21"], True,
     "Three cards handle incoming payments from different angles; any is acceptable.", [("M2C-19", "analysis of incoming payments"), ("M2C-20", "incoming-payment amounts are assigned"), ("M2C-22", "incoming-payment notifications")]),
    ("P5-53", "ambiguous", "hard", "Contract account", ["M2C-17", "M2C-18"], [], True,
     "Two cards are about the contract account (overview and business object); either is acceptable.", [("M2C-17", "Foundation reference for contract accounts"), ("M2C-18", "definition of the contract account")]),
    ("P5-54", "ambiguous", "medium", "Billing process overview", ["M2C-11"], ["M2C-12", "M2C-14", "M2C-16"], True,
     "Card 11 is described as the primary business-process source for billing.", [("M2C-11", "Primary business-process source for SAP Utilities billing")]),
]


def words(s: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


def longest_common_run(a: Sequence[str], b: Sequence[str]) -> int:
    best = 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0] * (len(b) + 1)
        for j, y in enumerate(b, 1):
            if x == y:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


def length_bucket(n: int) -> str:
    return "very_short" if n <= 4 else "short" if n <= 7 else "long" if n <= 20 else "very_long"


def build(units: Sequence[Dict[str, Any]], phase4_questions: Sequence[str]) -> Dict[str, Any]:
    by_id = {u["source_id"]: u for u in units}
    p4 = {q.strip().lower() for q in phase4_questions}
    out, seen = [], set()
    for qid, typ, diff, query, expected, also, amb, rationale, evidence in Q:
        if typ not in TYPES or diff not in ("easy", "medium", "hard"):
            raise ValueError(f"{qid}: bad type/difficulty")
        for sid in list(expected) + list(also):
            if sid not in by_id:
                raise ValueError(f"{qid}: unknown source {sid}")
        if {s for s, _ in evidence} != set(expected):
            raise ValueError(f"{qid}: evidence must cover exactly the expected sources")
        for sid, quote in evidence:
            if quote not in by_id[sid]["full_text"]:
                raise ValueError(f"{qid}: evidence quote {quote!r} not found in {sid}")
        if query.strip().lower() in p4:
            raise ValueError(f"{qid}: identical to a Phase-4 question")
        if query.lower() in seen or qid in seen:
            raise ValueError(f"{qid}: duplicate")
        seen |= {query.lower(), qid}
        qw = words(query)
        overlap = max(longest_common_run(qw, words(by_id[s]["full_text"])) for s in expected)
        if overlap > MAX_VERBATIM_WORDS:
            raise ValueError(f"{qid}: {overlap} consecutive words copied from the card (max {MAX_VERBATIM_WORDS})")
        if len(expected) > 1 and not amb:
            raise ValueError(f"{qid}: several expected cards require ambiguous=true")
        out.append({"query_id": qid, "query": query, "query_type": typ, "difficulty": diff, "expected_source_ids": list(expected),
                    "also_relevant_source_ids": list(also), "ambiguous": amb, "rationale": rationale,
                    "evidence": [{"source_id": s, "quote": q} for s, q in evidence],
                    "word_count": len(qw), "length_bucket": length_bucket(len(qw)), "max_verbatim_overlap_words": overlap})
    return {"schema_version": 1,
            "description": "Independent retrieval queries written like real users; labels from the card text only; written by hand by the AI coding agent (no automated LLM generation pipeline, no human domain expert) before any Phase 5 retrieval.",
            "independence_rules": {"max_verbatim_overlap_words": MAX_VERBATIM_WORDS, "not_equal_to_phase4_questions": True},
            "difficulty_criteria": {"easy": "term appears in only one or two cards, or intent unmistakable",
                                    "medium": "intent clear but vocabulary differs from the card, or a sibling card is plausible",
                                    "hard": "vocabulary differs AND a sibling card is plausible, or very short/generic/compound"},
            "length_buckets": {"very_short": "1-4 words", "short": "5-7", "long": "8-20", "very_long": ">20"},
            "query_count": len(out), "queries": out}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--units", default=str(UNITS_PATH))
    ap.add_argument("--phase4-questions", default=str(PHASE4_QUESTIONS))
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    units = json.loads(Path(a.units).read_text(encoding="utf-8"))["units"]
    p4 = [q["question"] for q in json.loads(Path(a.phase4_questions).read_text(encoding="utf-8"))["questions"]]
    payload = build(units, p4)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {a.out}: {payload['query_count']} queries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
