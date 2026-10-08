"""
Builds eval/golden/golden_v1.jsonl for SURA (SAP Utilities Assistant) Phase 1 baseline.
Strictly verifies that every key_fact is an exact verbatim substring in the actual corpus.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Load ingested document texts
with open(ROOT / "scratch" / "ingested_doc_texts.json", "r", encoding="utf-8") as f:
    doc_texts = json.load(f)

def vfact(doc: str, text: str):
    """Asserts that text is literally present in the document's full text."""
    assert doc in doc_texts, f"Doc {doc} not found in ingested docs"
    doc_full = doc_texts[doc]["full_text"]
    assert text in doc_full, f"Verbatim assertion failed for doc {doc}: '{text}' not in full_text!"
    return {"text": text, "doc": doc}

cases = []

# ==============================================================================
# 1. 40 Answerable Questions across the 25 ingested documents
# ==============================================================================

# M2C-02
cases.append({
    "id": "ans-01",
    "type": "answerable",
    "category": "move_in_out",
    "question": "How is the Print Workbench component used in move-in?",
    "expected_route": "answered",
    "gold_docs": ["M2C-02"],
    "key_facts": [
        vfact("M2C-02", "Letters to the customer, such as welcome letters and move-out confirmations are created using the Print Workbench component."),
    ],
    "notes": "Move-In/Out letter creation using Print Workbench"
})
cases.append({
    "id": "ans-02",
    "type": "answerable",
    "category": "move_in_out",
    "question": "What happens when a new customer moves into an installation during a move-out?",
    "expected_route": "answered",
    "gold_docs": ["M2C-02"],
    "key_facts": [
        vfact("M2C-02", "In a move-out, you terminate the customer's contract. If a new customer moves into the installation, the installation is allocated to this customer's contract."),
    ],
    "notes": "Move-out contract termination and reallocation"
})

# M2C-03
cases.append({
    "id": "ans-03",
    "type": "answerable",
    "category": "move_in_out",
    "question": "What activities are carried out using the move-in function?",
    "expected_route": "answered",
    "gold_docs": ["M2C-03"],
    "key_facts": [
        vfact("M2C-03", "You use the move-in function to carry out most of the activities required to begin providing a business partner with a utility service."),
        vfact("M2C-03", "Most importantly, you allocate a contract to an installation."),
    ],
    "notes": "Move-in function activities"
})
cases.append({
    "id": "ans-04",
    "type": "answerable",
    "category": "move_in_out",
    "question": "What installations are required to create a move-in?",
    "expected_route": "answered",
    "gold_docs": ["M2C-03"],
    "key_facts": [
        vfact("M2C-03", "To create a move-in, you require one or more installations that are vacant on the desired move-in date."),
    ],
    "notes": "Move-in prerequisite vacant installation"
})

# M2C-04
cases.append({
    "id": "ans-05",
    "type": "answerable",
    "category": "move_in_out",
    "question": "What happens to the allocation of a contract on the move-out date?",
    "expected_route": "answered",
    "gold_docs": ["M2C-04"],
    "key_facts": [
        vfact("M2C-04", "You specifically end the allocation of a contract to an installation on the move-out date."),
    ],
    "notes": "Ending allocation of contract on move-out date"
})
cases.append({
    "id": "ans-06",
    "type": "answerable",
    "category": "move_in_out",
    "question": "What happens to budget billing plans when a move-out is processed?",
    "expected_route": "answered",
    "gold_docs": ["M2C-04"],
    "key_facts": [
        vfact("M2C-04", "Move-out processing stops the active payment plans."),
        vfact("M2C-04", "Budget billing amounts that have already been paid are cleared when the final billing is invoiced."),
    ],
    "notes": "Move-out effect on budget billing plans"
})

# M2C-05
cases.append({
    "id": "ans-07",
    "type": "answerable",
    "category": "device_management",
    "question": "What does the Device Management component manage?",
    "expected_route": "answered",
    "gold_docs": ["M2C-05"],
    "key_facts": [
        vfact("M2C-05", "This component manages technical data, installations, meter readings, and the inspection of devices."),
    ],
    "notes": "Device management component overview"
})
cases.append({
    "id": "ans-08",
    "type": "answerable",
    "category": "device_management",
    "question": "What standard component corresponds to a device in the Utilities Industry component?",
    "expected_route": "answered",
    "gold_docs": ["M2C-05"],
    "key_facts": [
        vfact("M2C-05", "Name in IS-U: Device; From Component: Plant Maintenance (PM); Name in Standard System: Equipment"),
    ],
    "notes": "Device mapping to PM Equipment"
})

# M2C-06
cases.append({
    "id": "ans-09",
    "type": "answerable",
    "category": "meter_reading",
    "question": "How are meter reading orders and results selected using BAPIs?",
    "expected_route": "answered",
    "gold_docs": ["M2C-06"],
    "key_facts": [
        vfact("M2C-06", "The following Business Application Programming Interfaces (BAPI) are available in the Business Object Repository (BOR) for selecting meter reading orders and results:"),
        vfact("M2C-06", "- MeterReadingDocument.GetList (select meter reading orders and results)"),
    ],
    "notes": "BAPI for meter reading selection"
})
cases.append({
    "id": "ans-10",
    "type": "answerable",
    "category": "meter_reading",
    "question": "When are devices read aperiodically?",
    "expected_route": "answered",
    "gold_docs": ["M2C-06"],
    "key_facts": [
        vfact("M2C-06", "Devices are either read periodically for periodic billing or aperiodically, such as for control meter readings and readings at the time of device replacement, removal, or disconnection."),
    ],
    "notes": "Aperiodic meter readings"
})

# M2C-07
cases.append({
    "id": "ans-11",
    "type": "answerable",
    "category": "meter_reading",
    "question": "Where can you find the transactions to monitor meter reading results in the menu?",
    "expected_route": "answered",
    "gold_docs": ["M2C-07"],
    "key_facts": [
        vfact("M2C-07", "To monitor meter reading results, you can use the following transactions in the Utilities Industry menu under Device Management > Meter Reading > Monitoring ."),
    ],
    "notes": "Monitoring meter reading menu path"
})

# M2C-08
cases.append({
    "id": "ans-12",
    "type": "answerable",
    "category": "meter_reading",
    "question": "When does the Meter Reading Estimation component estimate meter reading results automatically?",
    "expected_route": "answered",
    "gold_docs": ["M2C-08"],
    "key_facts": [
        vfact("M2C-08", "This component allows you to estimate meter reading results automatically in the case of missing meter readings or implausible consumption."),
    ],
    "notes": "Meter reading automatic estimation conditions"
})

# M2C-09
cases.append({
    "id": "ans-13",
    "type": "answerable",
    "category": "meter_reading",
    "question": "What is the difference between extrapolation and interpolation in meter reading estimation?",
    "expected_route": "answered",
    "gold_docs": ["M2C-09"],
    "key_facts": [
        vfact("M2C-09", "The estimation procedures used are extrapolation and interpolation ."),
        vfact("M2C-09", "During extrapolation, a value is determined beyond the base period. During interpolation, a value is estimated between other existing values."),
    ],
    "notes": "Extrapolation vs interpolation definition"
})
cases.append({
    "id": "ans-14",
    "type": "answerable",
    "category": "meter_reading",
    "question": "What is the base period in meter reading estimation?",
    "expected_route": "answered",
    "gold_docs": ["M2C-09"],
    "key_facts": [
        vfact("M2C-09", "The base period is the period that contains all meter readings used as the basis for estimation."),
    ],
    "notes": "Base period definition"
})

# M2C-10
cases.append({
    "id": "ans-15",
    "type": "answerable",
    "category": "meter_reading",
    "question": "What happens if you adopt the meter reading result proposed during a move-in?",
    "expected_route": "answered",
    "gold_docs": ["M2C-10"],
    "key_facts": [
        vfact("M2C-10", "When you create a move-in, the system proposes an existing meter reading result for all the billing-relevant registers allocated to the devices for billing purposes."),
        vfact("M2C-10", "- If you adopt the meter reading result, the system adds the meter reading reason Move-in to the result."),
    ],
    "notes": "Adopting move-in meter reading result"
})

# M2C-11
cases.append({
    "id": "ans-16",
    "type": "answerable",
    "category": "billing",
    "question": "What determines the evaluation basis for schema execution in billing?",
    "expected_route": "answered",
    "gold_docs": ["M2C-11"],
    "key_facts": [
        vfact("M2C-11", "Billing uses meter reading results or load profiles to determine the evaluation basis for schema execution."),
        vfact("M2C-11", "All calculations required for rate creation are made during schema execution."),
    ],
    "notes": "Schema execution evaluation basis"
})
cases.append({
    "id": "ans-17",
    "type": "answerable",
    "category": "billing",
    "question": "What happens in billing when a price change occurs during a billing period?",
    "expected_route": "answered",
    "gold_docs": ["M2C-11"],
    "key_facts": [
        vfact("M2C-11", "For example, a price change causes the system to divide the total period into subperiods, each with the price valid for that subperiod."),
    ],
    "notes": "Price change subperiod division"
})

# M2C-12
cases.append({
    "id": "ans-18",
    "type": "answerable",
    "category": "billing",
    "question": "What contracts are selected during automatic billing?",
    "expected_route": "answered",
    "gold_docs": ["M2C-12"],
    "key_facts": [
        vfact("M2C-12", "Automatic billing enables you to bill a single contract or any selection of contracts. Contracts not allocated to an installation are not selected."),
    ],
    "notes": "Automatic billing contract selection"
})
cases.append({
    "id": "ans-19",
    "type": "answerable",
    "category": "billing",
    "question": "How does scheduling determine billing runs in automatic billing?",
    "expected_route": "answered",
    "gold_docs": ["M2C-12"],
    "key_facts": [
        vfact("M2C-12", "Scheduling determines how often billing runs occur."),
    ],
    "notes": "Scheduling determines billing run frequency"
})

# M2C-14
cases.append({
    "id": "ans-20",
    "type": "answerable",
    "category": "invoicing",
    "question": "What documents are produced by invoicing with bill creation?",
    "expected_route": "answered",
    "gold_docs": ["M2C-14"],
    "key_facts": [
        vfact("M2C-14", "2. Invoicing with Bill Creation results in a print document and a contract accounting document."),
    ],
    "notes": "Invoicing documents produced"
})
cases.append({
    "id": "ans-21",
    "type": "answerable",
    "category": "invoicing",
    "question": "How does invoicing relate to contract accounting and bill creation?",
    "expected_route": "answered",
    "gold_docs": ["M2C-14"],
    "key_facts": [
        vfact("M2C-14", "Invoicing creates the link to contract accounting and provides the basis for bill creation."),
    ],
    "notes": "Invoicing link to contract accounting"
})

# M2C-15
cases.append({
    "id": "ans-22",
    "type": "answerable",
    "category": "invoicing",
    "question": "When are new budget billing plans created automatically during invoicing?",
    "expected_route": "answered",
    "gold_docs": ["M2C-15"],
    "key_facts": [
        vfact("M2C-15", "When periodic billing documents are invoiced, a new budget billing plan is created automatically for contracts that were billed periodically."),
    ],
    "notes": "Budget billing plan creation during invoicing"
})
cases.append({
    "id": "ans-23",
    "type": "answerable",
    "category": "invoicing",
    "question": "What does deactivation of a budget billing plan in invoicing mean?",
    "expected_route": "answered",
    "gold_docs": ["M2C-15"],
    "key_facts": [
        vfact("M2C-15", "- Deactivate budget billing plan The invoicing document number appears automatically in the budget billing plan header in the Deactivate field. This means that:"),
        vfact("M2C-15", "- You cannot further process the budget billing plan."),
    ],
    "notes": "Deactivating budget billing plan"
})

# M2C-17
cases.append({
    "id": "ans-24",
    "type": "answerable",
    "category": "contract_accounts",
    "question": "Can a single contract account be assigned to multiple business partners in Utilities?",
    "expected_route": "answered",
    "gold_docs": ["M2C-17"],
    "key_facts": [
        vfact("M2C-17", "In this component, a contract account can be assigned to one business partner only."),
        vfact("M2C-17", "In Contract Accounts Receivable and Payable, each business partner posting is assigned to one business partner and to one contract account."),
    ],
    "notes": "Single business partner assignment in Utilities"
})
cases.append({
    "id": "ans-25",
    "type": "answerable",
    "category": "contract_accounts",
    "question": "What does a contract account contain in SAP Utilities?",
    "expected_route": "answered",
    "gold_docs": ["M2C-17"],
    "key_facts": [
        vfact("M2C-17", "In Utilities,one contract account contains all those contracts belonging to one business partner for which the same payment and dunning terms apply."),
    ],
    "notes": "Contract account contents in Utilities"
})

# M2C-19
cases.append({
    "id": "ans-26",
    "type": "answerable",
    "category": "payments",
    "question": "What is the purpose of the Analyze Incoming Payments F5588 app?",
    "expected_route": "answered",
    "gold_docs": ["M2C-19"],
    "key_facts": [
        vfact("M2C-19", "With the Analyze Incoming Payments (F5588) app, you can monitor and analyze incoming payments to optimize clarification processes and team workload."),
    ],
    "notes": "Analyze Incoming Payments F5588 app"
})
cases.append({
    "id": "ans-27",
    "type": "answerable",
    "category": "payments",
    "question": "What does the Analyze Incoming Payments app monitor?",
    "expected_route": "answered",
    "gold_docs": ["M2C-19"],
    "key_facts": [
        vfact("M2C-19", "- Analyze how many payments have been clarified manually within a given period."),
        vfact("M2C-19", "- Analyze the effectiveness of the automated clarification process provided by the standard."),
    ],
    "notes": "Tasks performed in Analyze Incoming Payments app"
})

# M2C-20
cases.append({
    "id": "ans-28",
    "type": "answerable",
    "category": "payments",
    "question": "In which event does the system attempt to assign incoming payment amounts to open items?",
    "expected_route": "answered",
    "gold_docs": ["M2C-20"],
    "key_facts": [
        vfact("M2C-20", "During the processing of externally initiated payments, the system attempts in event 0110 to assign the payment amount to the open items."),
    ],
    "notes": "Event 0110 in clearing control"
})
cases.append({
    "id": "ans-29",
    "type": "answerable",
    "category": "payments",
    "question": "What fields does clearing control take into account during incoming payment processing?",
    "expected_route": "answered",
    "gold_docs": ["M2C-20"],
    "key_facts": [
        vfact("M2C-20", "Clearing control takes account of entries in the same fields, as in account maintenance ."),
    ],
    "notes": "Clearing control account maintenance fields"
})

# M2C-21
cases.append({
    "id": "ans-30",
    "type": "answerable",
    "category": "payments",
    "question": "Where are clearing types defined in Customizing?",
    "expected_route": "answered",
    "gold_docs": ["M2C-21"],
    "key_facts": [
        vfact("M2C-21", "In Customizing for Contract Accounts Receivable and Payable, under Open Item Management > Clearing Control > Define Clearing Types , define the clearing rules, depending on the clearing type."),
    ],
    "notes": "Customizing path for clearing types"
})
cases.append({
    "id": "ans-31",
    "type": "answerable",
    "category": "payments",
    "question": "What does a clearing type represent in Contract Accounts Receivable and Payable?",
    "expected_route": "answered",
    "gold_docs": ["M2C-21"],
    "key_facts": [
        vfact("M2C-21", "The clearing type represents the business transaction, such as payment lot (05), cash desk (19), or manual account maintenance (03)."),
    ],
    "notes": "Clearing type representation"
})

# M2C-22
cases.append({
    "id": "ans-32",
    "type": "answerable",
    "category": "payments",
    "question": "Where can detailed information about payments from external cash desks be displayed?",
    "expected_route": "answered",
    "gold_docs": ["M2C-22"],
    "key_facts": [
        vfact("M2C-22", "In the document display for a payment, the External Cash Desk tab page contains detailed information about the payment."),
    ],
    "notes": "External Cash Desk tab page"
})

# M2C-23
cases.append({
    "id": "ans-33",
    "type": "answerable",
    "category": "installment_plans",
    "question": "What is an installment plan in Contract Accounts Receivable and Payable?",
    "expected_route": "answered",
    "gold_docs": ["M2C-23"],
    "key_facts": [
        vfact("M2C-23", "With an installment plan you divide source items to several installment receivables that have a due date in the future."),
        vfact("M2C-23", "An installment plan consists of a statistical document with several installment receivables."),
    ],
    "notes": "Installment plan definition"
})

# M2C-24
cases.append({
    "id": "ans-34",
    "type": "answerable",
    "category": "installment_plans",
    "question": "When can you create an installment plan for a business partner?",
    "expected_route": "answered",
    "gold_docs": ["M2C-24"],
    "key_facts": [
        vfact("M2C-24", "You create an installment plan when both of the following apply:"),
        vfact("M2C-24", "- There are one or more open items on the contract account of a business partner."),
        vfact("M2C-24", "- The business partner is unable to meet his/her payment obligations in accordance with the usual payment rules."),
    ],
    "notes": "Installment plan creation preconditions"
})
cases.append({
    "id": "ans-35",
    "type": "answerable",
    "category": "installment_plans",
    "question": "What transaction code is used to create an installment plan?",
    "expected_route": "answered",
    "gold_docs": ["M2C-24"],
    "key_facts": [
        vfact("M2C-24", "In the SAP Easy Access screen, choose Account > Installment Plan > Create (transaction FPR1 )."),
    ],
    "notes": "FPR1 create installment plan"
})

# M2C-25
cases.append({
    "id": "ans-36",
    "type": "answerable",
    "category": "installment_plans",
    "question": "Which transaction is used to display an installment plan?",
    "expected_route": "answered",
    "gold_docs": ["M2C-25"],
    "key_facts": [
        vfact("M2C-25", "1. In the SAP Easy Access screen, choose Account > Installment Plan > Display (transaction FPR3 )."),
    ],
    "notes": "FPR3 display installment plan"
})

# M2C-26
cases.append({
    "id": "ans-37",
    "type": "answerable",
    "category": "dunning",
    "question": "Why do you create payment reminders or dunning letters in FI-CA?",
    "expected_route": "answered",
    "gold_docs": ["M2C-26"],
    "key_facts": [
        vfact("M2C-26", "You can create payment reminders or dunning letters and send them to your business partners, to alert them of overdue payables and to request payment."),
    ],
    "notes": "FI-CA dunning purpose"
})

# M2C-27
cases.append({
    "id": "ans-38",
    "type": "answerable",
    "category": "collection_agency",
    "question": "What functions are available to submit receivables to a collection agency?",
    "expected_route": "answered",
    "gold_docs": ["M2C-27"],
    "key_facts": [
        vfact("M2C-27", "- Releasing Receivables for Collection"),
        vfact("M2C-27", "- Submission of Receivables to Collection Agency"),
    ],
    "notes": "Collection agency submission functions"
})

# M2C-28
cases.append({
    "id": "ans-39",
    "type": "answerable",
    "category": "collection_agency",
    "question": "How can you communicate with collection agencies in FI-CA?",
    "expected_route": "answered",
    "gold_docs": ["M2C-28"],
    "key_facts": [
        vfact("M2C-28", "You can communicate with your collection agencies by using files (creation of submission and information files, import of collection agency files) or by using Enterprise Services or APIs."),
    ],
    "notes": "Collection agency communication methods"
})

# M2C-29
cases.append({
    "id": "ans-40",
    "type": "answerable",
    "category": "disconnection",
    "question": "Why is a utility installation disconnected?",
    "expected_route": "answered",
    "gold_docs": ["M2C-29"],
    "key_facts": [
        vfact("M2C-29", "- Introduction of a collection procedure for outstanding payment"),
        vfact("M2C-29", "- Technical disconnection due to request of utilities company or customer"),
    ],
    "notes": "Disconnection reasons and usage"
})

# ==============================================================================
# 2. 15 Paraphrase Groups x 3 phrasings = 45 queries
# ==============================================================================

PARAPHRASE_DEFS = [
    (
        "para-01", "M2C-24", "installment_plans",
        "How do I create an installment plan?",
        "How can I create an installment plan for open items?",
        "How are installment plans created for a customer?",
        vfact("M2C-24", "In the SAP Easy Access screen, choose Account > Installment Plan > Create (transaction FPR1 ).")
    ),
    (
        "para-02", "M2C-25", "installment_plans",
        "How can I display an existing installment plan?",
        "Where do I view saved installment plans in transaction FPR3?",
        "What is the transaction to display an installment plan?",
        vfact("M2C-25", "1. In the SAP Easy Access screen, choose Account > Installment Plan > Display (transaction FPR3 ).")
    ),
    (
        "para-03", "M2C-03", "move_in_out",
        "What happens during a move-in?",
        "How does move-in processing work in SAP Utilities?",
        "What is the process to execute a customer move-in?",
        vfact("M2C-03", "You use the move-in function to carry out most of the activities required to begin providing a business partner with a utility service.")
    ),
    (
        "para-04", "M2C-04", "move_in_out",
        "How does a move-out work?",
        "What happens when a customer moves out in SAP Utilities?",
        "How is a move-out processed?",
        vfact("M2C-04", "During the move-out transaction, you execute most of the activities required to cancel the customer's supply of utilities services.")
    ),
    (
        "para-05", "M2C-08", "meter_reading",
        "How does meter reading estimation work?",
        "When does the system estimate meter readings?",
        "How are meter reading results estimated automatically?",
        vfact("M2C-08", "This component allows you to estimate meter reading results automatically in the case of missing meter readings or implausible consumption.")
    ),
    (
        "para-06", "M2C-09", "meter_reading",
        "What estimation procedures are used in meter reading?",
        "How are extrapolation and interpolation applied in meter estimation?",
        "Which methods does SAP Utilities use to estimate meter values?",
        vfact("M2C-09", "The estimation procedures used are extrapolation and interpolation .")
    ),
    (
        "para-07", "M2C-05", "device_management",
        "How are devices managed in SAP Utilities?",
        "What does the device management component do?",
        "What technical data is managed under device management?",
        vfact("M2C-05", "This component manages technical data, installations, meter readings, and the inspection of devices.")
    ),
    (
        "para-08", "M2C-06", "meter_reading",
        "How are meter readings organized?",
        "What is the process for reading meters in SAP Utilities?",
        "How are periodic and aperiodic meter readings carried out?",
        vfact("M2C-06", "You can use this component to organize meter readings and meter reading results.")
    ),
    (
        "para-09", "M2C-07", "meter_reading",
        "How do you monitor meter reading results?",
        "What does monitoring of meter reading results do?",
        "Where can I monitor meter reading orders and results?",
        vfact("M2C-07", "To monitor meter reading results, you can use the following transactions in the Utilities Industry menu under Device Management > Meter Reading > Monitoring .")
    ),
    (
        "para-10", "M2C-11", "billing",
        "How does billing work in SAP Utilities?",
        "What is the billing procedure in SAP Utilities?",
        "How are rate calculations and schema execution handled in billing?",
        vfact("M2C-11", "Billing uses meter reading results or load profiles to determine the evaluation basis for schema execution.")
    ),
    (
        "para-11", "M2C-12", "billing",
        "How does automatic billing work?",
        "What is the automatic billing procedure in SAP Utilities?",
        "How are contracts billed automatically?",
        vfact("M2C-12", "Automatic billing enables you to bill a single contract or any selection of contracts.")
    ),
    (
        "para-12", "M2C-14", "invoicing",
        "What is the invoicing process in SAP Utilities?",
        "How does invoicing create the link to contract accounting?",
        "What steps are involved in invoicing and bill creation?",
        vfact("M2C-14", "Invoicing creates the link to contract accounting and provides the basis for bill creation.")
    ),
    (
        "para-13", "M2C-17", "contract_accounts",
        "What is a contract account?",
        "How is a contract account defined in SAP Utilities?",
        "What does a contract account contain in Utilities?",
        vfact("M2C-17", "In Contract Accounts Receivable and Payable, each business partner posting is assigned to one business partner and to one contract account.")
    ),
    (
        "para-14", "M2C-20", "payments",
        "What is clearing control in incoming payments?",
        "How does clearing control assign payments to open items?",
        "What happens during clearing control for incoming payments?",
        vfact("M2C-20", "During the processing of externally initiated payments, the system attempts in event 0110 to assign the payment amount to the open items.")
    ),
    (
        "para-15", "M2C-26", "dunning",
        "How does dunning work in FI-CA?",
        "How are dunning notices created in SAP Utilities?",
        "What is the FI-CA dunning procedure for overdue payments?",
        vfact("M2C-26", "You can create payment reminders or dunning letters and send them to your business partners, to alert them of overdue payables and to request payment.")
    ),
]

for gid, doc, cat, q1, q2, q3, fact in PARAPHRASE_DEFS:
    for sub_idx, q in enumerate([q1, q2, q3], 1):
        cases.append({
            "id": f"{gid}-{chr(96 + sub_idx)}",
            "type": "paraphrase",
            "group": gid,
            "category": cat,
            "question": q,
            "expected_route": "answered",
            "gold_docs": [doc],
            "key_facts": [fact],
            "notes": f"Paraphrase variant {sub_idx} for group {gid} targeting {doc}"
        })

# ==============================================================================
# 3. 15 Out-of-Scope (OOS) Questions
# ==============================================================================

OOS_QUESTIONS = [
    ("oos-01", "What is the capital of Australia?", "General geography"),
    ("oos-02", "Give me a Python script to sort an array using quicksort.", "General programming"),
    ("oos-03", "Which football team won the 2018 World Cup?", "General sports"),
    ("oos-04", "How do I bake chocolate chip cookies at home?", "Culinary / cooking"),
    ("oos-05", "What is the weather in Hyderabad today?", "Current weather"),
    ("oos-06", "Explain how photosynthesis works in green plants.", "Biology / science"),
    ("oos-07", "What is the capital of France?", "General geography"),
    ("oos-08", "What is the boiling point of liquid nitrogen?", "Physics / chemistry"),
    ("oos-09", "Who is the CEO of Microsoft in 2024?", "General corporate"),
    ("oos-10", "How do I reset network settings on an Apple iPhone?", "Mobile consumer electronics"),
    ("oos-11", "Write a haiku about the rainy season.", "Creative writing"),
    ("oos-12", "What are the health benefits of green tea?", "Nutrition / health"),
    ("oos-13", "Who wrote the play Romeo and Juliet?", "Literature / arts"),
    ("oos-14", "What is the distance between the Earth and the Moon?", "Astronomy"),
    ("oos-15", "Can you recommend a good hotel in Tokyo for tourists?", "Travel / tourism"),
]

for cid, q, note in OOS_QUESTIONS:
    cases.append({
        "id": cid,
        "type": "out_of_scope",
        "category": "out_of_scope",
        "question": q,
        "expected_route": "out_of_scope",
        "gold_docs": [],
        "key_facts": [],
        "notes": note
    })

# ==============================================================================
# 4. 10 Near-Miss (Unable-to-Verify) Questions
# ==============================================================================

NEAR_MISS_QUESTIONS = [
    ("near-01", "M2C-07", "Which authorization object is needed to run the monitoring transaction?", "Authorization object absent from M2C-07 page"),
    ("near-02", "M2C-06", "What is the exact database table for meter reading orders in IS-U?", "DB table name absent from M2C-06 page"),
    ("near-03", "M2C-24", "What is the maximum number of installments allowed per installment plan?", "Max installment limit absent from M2C-24 page"),
    ("near-04", "M2C-11", "Which ABAP user exit is called during billing schema execution?", "ABAP user exit name absent from M2C-11 page"),
    ("near-05", "M2C-03", "What is the exact transaction code for mass move-in simulation?", "Mass move-in simulation tcode absent from M2C-03 page"),
    ("near-06", "M2C-14", "Which background job program executes mass invoicing for multiple contract accounts?", "Mass invoicing program name absent from M2C-14 page"),
    ("near-07", "M2C-20", "What is the specific event function module name for clearing rule priority 99?", "Clearing FM name absent from M2C-20 page"),
    ("near-08", "M2C-26", "Which spool recipient receives the dunning print log spool list?", "Spool recipient config absent from M2C-26 page"),
    ("near-09", "M2C-05", "What is the technical field length of the IS-U equipment serial number?", "Technical field length absent from M2C-05 page"),
    ("near-10", "M2C-29", "What is the legal notice waiting period in business days before service disconnection?", "Legal notice days absent from M2C-29 page"),
]

for cid, doc, q, note in NEAR_MISS_QUESTIONS:
    cases.append({
        "id": cid,
        "type": "near_miss",
        "category": "near_miss",
        "question": q,
        "expected_route": "unable_to_verify",
        "gold_docs": [doc],
        "key_facts": [],
        "notes": note
    })

# ==============================================================================
# 5. Landing Page Suggestions (from Welcome.tsx EXAMPLE_PROMPTS)
# ==============================================================================

LANDING_SUGGESTIONS = [
    ("land-01", "M2C-11", "How does billing work?"),
    ("land-02", "M2C-17", "What is a contract account?"),
    ("land-03", "M2C-14", "What is the invoicing process?"),
    ("land-04", "M2C-17", "How does a contract account relate to a business partner?"),
    ("land-05", "M2C-24", "How do I create an installment plan?"),
    ("land-06", "M2C-05", "How are devices managed?"),
]

# Load verified candidate facts
with open(ROOT / "scratch" / "candidate_facts.json", "r", encoding="utf-8") as f:
    vfacts = json.load(f)

for cid, doc, q in LANDING_SUGGESTIONS:
    cases.append({
        "id": cid,
        "type": "landing_suggestion",
        "category": "landing_prompt",
        "question": q,
        "expected_route": "answered",
        "gold_docs": [doc],
        "key_facts": [vfact(doc, vfacts[doc][0])],
        "notes": f"Landing page prompt from Welcome.tsx ({q})"
    })

# ==============================================================================
# 6. Explore Topic Chips (all 29 topic cards: 25 searchable, 4 un-ingested)
# ==============================================================================

# Load topic cards metadata
with open(ROOT / "data" / "m2c_page_identity.json", "r", encoding="utf-8") as f:
    m2c_ident = json.load(f)

for card in m2c_ident["cards"]:
    sid = card["source_id"]
    title = card["card_title"]
    is_ingested = card.get("local_page_available", False) or (sid in doc_texts)

    # Question formulation for the topic chip
    q = f"Tell me about {title}."
    if is_ingested:
        expected = "answered"
        gdocs = [sid]
        kfacts = [vfact(sid, vfacts[sid][0])]
    else:
        # Un-ingested cards produce documentation_unavailable / unable_to_verify
        expected = "documentation_unavailable"
        gdocs = [sid]
        kfacts = []

    cases.append({
        "id": f"chip-{sid.lower()}",
        "type": "explore_chip",
        "category": "explore_topic",
        "question": q,
        "expected_route": expected,
        "gold_docs": gdocs,
        "key_facts": kfacts,
        "notes": f"Explore topic chip for {sid}: {title} (Ingested={is_ingested})"
    })

# ==============================================================================
# 7. Related-Question Outputs (from util.ts follow-up pools)
# ==============================================================================

RELATED_QUESTIONS = [
    ("rel-01", "M2C-19", "How are incoming payments analyzed and cleared?"),
    ("rel-02", "M2C-14", "How does invoicing create the link to contract accounting?"),
    ("rel-03", "M2C-03", "How does move-in processing work?"),
    ("rel-04", "M2C-04", "How does move-out processing work?"),
    ("rel-05", "M2C-07", "What does monitoring of meter reading results do?"),
    ("rel-06", "M2C-12", "How does automatic billing work?"),
]

for cid, doc, q in RELATED_QUESTIONS:
    cases.append({
        "id": cid,
        "type": "related_question",
        "category": "related_output",
        "question": q,
        "expected_route": "answered",
        "gold_docs": [doc],
        "key_facts": [vfact(doc, vfacts[doc][0])],
        "notes": f"Related question from frontend follow-up pool: {q}"
    })

# ==============================================================================
# 8. Multi-Turn Topic Switches (A -> B -> A sequences)
# ==============================================================================

SWITCH_SEQUENCES = [
    # Sequence 1: Installment Plan (M2C-24) -> Meter Estimation (M2C-08) -> Installment Plan (M2C-24)
    ("sw-01-a", "M2C-24", "How do I create an installment plan?", "switch_seq_1", 1),
    ("sw-01-b", "M2C-08", "How does meter reading estimation work?", "switch_seq_1", 2),
    ("sw-01-c", "M2C-24", "What transaction code creates an installment plan?", "switch_seq_1", 3),
    # Sequence 2: Move-In (M2C-03) -> Invoicing (M2C-14) -> Move-In (M2C-03)
    ("sw-02-a", "M2C-03", "What happens during a move-in?", "switch_seq_2", 1),
    ("sw-02-b", "M2C-14", "What is the invoicing procedure in SAP Utilities?", "switch_seq_2", 2),
    ("sw-02-c", "M2C-03", "What activities are carried out using the move-in function?", "switch_seq_2", 3),
]

for cid, doc, q, group, turn in SWITCH_SEQUENCES:
    cases.append({
        "id": cid,
        "type": "topic_switch",
        "category": "topic_switch",
        "group": group,
        "turn": turn,
        "question": q,
        "expected_route": "answered",
        "gold_docs": [doc],
        "key_facts": [vfact(doc, vfacts[doc][0])],
        "notes": f"Topic switch turn {turn} in {group}: {q}"
    })

# ==============================================================================
# Write to eval/golden/golden_v1.jsonl
# ==============================================================================

out_dir = ROOT / "eval" / "golden"
out_dir.mkdir(parents=True, exist_ok=True)
out_file = out_dir / "golden_v1.jsonl"

with open(out_file, "w", encoding="utf-8") as f:
    for c in cases:
        f.write(json.dumps(c, ensure_ascii=False) + "\n")

print(f"Successfully generated {out_file} with {len(cases)} cases.")

# Count by category
counts = {}
for c in cases:
    t = c["type"]
    counts[t] = counts.get(t, 0) + 1
for t, cnt in sorted(counts.items()):
    print(f"  - {t}: {cnt}")
