# Phase 13-A: Per-Question Comparison Diff

| ID | Type | Gold Card | Baseline Top-1 (Rank) | Reranked Top-1 (Rank) | Sel Changed | Base Status -> Rerank Status | Base Correct -> Rerank Correct | Query |
|---|---|---|---|---|:---:|---|:---:|---|
| P12-001 | answerable | M2C-07 | M2C-22 (#27) | M2C-22 (#27) | - | insufficient_context -> insufficient_context | False | What is the purpose of transaction EL43? |
| P12-002 | answerable | M2C-07 | M2C-25 (#21) | M2C-25 (#21) | - | answered -> answered | False | What does transaction ELDM display? |
| P12-003 | answerable | M2C-07 | M2C-07 (#1) | M2C-07 (#1) | - | answered -> answered | True | How do I navigate to the detailed display of an object in the monitoring lists? |
| P12-004 | answerable | M2C-05 | M2C-05 (#1) | M2C-05 (#1) | - | answered -> answered | True | How is a device number created in Device Management? |
| P12-005 | answerable | M2C-05 | M2C-05 (#1) | M2C-05 (#1) | - | answered -> answered | True | What do device, device category and device number correspond to in the standard system? |
| P12-006 | answerable | M2C-05 | M2C-27 (#3) | M2C-05 (#1) | YES | answered -> answered | False -> **True** | When are equipment records created? |
| P12-007 | answerable | M2C-24 | M2C-20 (#25) | M2C-20 (#25) | - | insufficient_context -> insufficient_context | False | Which indicator sets the clearing priority of original items? |
| P12-008 | answerable | M2C-24 | M2C-20 (#4) | M2C-24 (#1) | YES | out_of_domain -> answered | False -> **True** | What happens to interest and charges when the Distribute indicator is set? |
| P12-009 | answerable | M2C-14 | M2C-14 (#1) | M2C-14 (#1) | - | answered -> answered | True | What is generated when invoicing with bill creation is run? |
| P12-010 | answerable | M2C-14 | M2C-29 (#2) | M2C-14 (#1) | YES | insufficient_context -> answered | False -> **True** | What happens to a bill after it has been created? |
| P12-011 | answerable | M2C-17 | M2C-18 (#2) | M2C-17 (#1) | YES | unresolved_identity -> answered | False -> **True** | What does the Contract Accounts component let me create? |
| P12-012 | answerable | M2C-11 | M2C-11 (#1) | M2C-11 (#1) | - | answered -> answered | True | What do the various billing procedures include? |
| P12-013 | answerable | M2C-02 | M2C-04 (#12) | M2C-04 (#12) | - | insufficient_context -> insufficient_context | False | Through which component are letters such as move-out confirmations generated? |
| P12-014 | answerable | M2C-02 | M2C-03 (#3) | M2C-02 (#1) | YES | answered -> answered | False -> **True** | What can the system trigger automatically for a move-out customer? |
| P12-015 | answerable | M2C-07 | M2C-06 (#2) | M2C-06 (#2) | - | insufficient_context -> insufficient_context | False | How can I see which meters belong to a reading unit? |
| P12-016 | answerable | M2C-07 | M2C-07 (#1) | M2C-07 (#1) | - | answered -> answered | True | Where in the menu do I find the tools for checking meter readings? |
| P12-017 | answerable | M2C-24 | M2C-24 (#1) | M2C-24 (#1) | - | insufficient_context -> insufficient_context | False | Under what circumstances is a payment arrangement for a customer set up? |
| P12-018 | answerable | M2C-24 | M2C-24 (#1) | M2C-24 (#1) | - | insufficient_context -> insufficient_context | False | How do I store my finished payment arrangement? |
| P12-019 | answerable | M2C-14 | M2C-14 (#1) | M2C-14 (#1) | - | answered -> answered | True | Can a printed bill be printed again? |
| P12-020 | answerable | M2C-14 | M2C-14 (#1) | M2C-14 (#1) | - | answered -> answered | True | Which function creates an offsetting document when a bill turns out to be wrong? |
| P12-021 | answerable | M2C-17 | M2C-17 (#1) | M2C-17 (#1) | - | answered -> answered | True | Which contracts does a utilities contract account bundle together? |
| P12-022 | answerable | M2C-17 | M2C-01 (#9) | M2C-03 (#9) | YES | unresolved_identity -> insufficient_context | False | What kind of change can happen to account master data without a user editing it? |
| P12-023 | answerable | M2C-11 | M2C-13 (#3) | M2C-11 (#1) | YES | out_of_domain -> answered | False -> **True** | Why is the billing period cut into pieces when a rate changes? |
| P12-024 | answerable | M2C-02 | M2C-03 (#4) | M2C-02 (#1) | YES | insufficient_context -> insufficient_context | False | What takes place when a customer leaves and a new one arrives? |
| P12-025 | answerable | M2C-05 | M2C-05 (#1) | M2C-05 (#1) | - | answered -> answered | True | Where does the equipment name of a device come from? |
| P12-026 | answerable | M2C-07 | M2C-06 (#3) | M2C-07 (#1) | YES | insufficient_context -> answered | False -> **True** | What is ISU_QD_1 used for in the meter reading monitoring lists? |
| P12-027 | answerable | M2C-07 | M2C-03 (#25) | M2C-05 (#25) | YES | insufficient_context -> answered | False | What is the business function ISU_AMI_1 required for? |
| P12-028 | answerable | M2C-05 | M2C-05 (#1) | M2C-05 (#1) | - | answered -> answered | True | Which function uses Goods Receipt from Inventory Management (MM-IM)? |
| P12-029 | answerable | M2C-24 | M2C-24 (#1) | M2C-24 (#1) | - | answered -> answered | True | What does the Remaining Amount field decide? |
| P12-030 | answerable | M2C-24 | M2C-27 (#26) | M2C-05 (#26) | YES | out_of_domain -> out_of_domain | False | What is event 3000 used for? |
| P12-031 | answerable | M2C-14 | M2C-13 (#10) | M2C-15 (#10) | YES | unresolved_identity -> insufficient_context | False | What does outsorting mean for a consumption bill? |
| P12-032 | answerable | M2C-17 | M2C-18 (#2) | M2C-17 (#1) | YES | unresolved_identity -> answered | False -> **True** | Which industry component limits a contract account to one business partner? |
| P12-033 | answerable | M2C-11 | M2C-12 (#2) | M2C-11 (#1) | YES | insufficient_context -> answered | False -> **True** | What is a subperiod in billing? |
| P12-034 | answerable | M2C-02 | M2C-04 (#4) | M2C-03 (#2) | YES | insufficient_context -> insufficient_context | False | Which component monitors the workflow processes of move-in and move-out? |
| P12-035 | answerable | M2C-07 | M2C-06 (#3) | M2C-07 (#1) | YES | insufficient_context -> answered | False -> **True** | Which transaction code shows all devices belonging to one meter reading unit? |
| P12-036 | answerable | M2C-07 | M2C-10 (#2) | M2C-07 (#1) | YES | insufficient_context -> answered | False -> **True** | Which transaction handles the automatic monitoring of meter reading data? |
| P12-037 | answerable | M2C-07 | M2C-10 (#4) | M2C-07 (#1) | YES | insufficient_context -> answered | False -> **True** | Which business function enables on-demand meter reading? |
| P12-038 | answerable | M2C-07 | M2C-27 (#6) | M2C-09 (#6) | YES | insufficient_context -> insufficient_context | False | Which business function is required to carry out quantity determination from the results list? |
| P12-039 | answerable | M2C-07 | M2C-10 (#5) | M2C-07 (#1) | YES | insufficient_context -> answered | False -> **True** | What is the IDoc category used when uploading discrete meter reading data? |
| P12-040 | answerable | M2C-24 | M2C-24 (#1) | M2C-24 (#1) | - | answered -> answered | True | What is the transaction code for creating an installment plan? |
| P12-041 | answerable | M2C-24 | M2C-20 (#26) | M2C-21 (#26) | YES | out_of_domain -> insufficient_context | False | Where in Customizing is the clearing priority indicator made available? |
| P12-042 | answerable | M2C-05 | M2C-23 (#14) | M2C-17 (#14) | YES | out_of_domain -> insufficient_context | False | Which component abbreviation covers purchase requisitions and purchase orders? |
| P12-043 | answerable | M2C-02 | M2C-03 (#3) | M2C-02 (#1) | YES | insufficient_context -> answered | False -> **True** | What is the component abbreviation of SAP Business Workflow in move-in and move-out? |
| P12-044 | answerable | M2C-24 | M2C-24 (#1) | M2C-24 (#1) | - | answered -> answered | True | Which event number allows other values for company code and contract in an installment plan? |
| P12-045 | answerable | M2C-24 | M2C-24 (#1) | M2C-25 (#3) | YES | insufficient_context -> insufficient_context | False | In which step of the procedure do I save the installment plan? |
| P12-046 | answerable | M2C-24 | M2C-24 (#1) | M2C-24 (#1) | - | insufficient_context -> insufficient_context | False | In which step do I choose Continue to get the installment plan proposal? |
| P12-047 | answerable | M2C-24 | M2C-27 (#7) | M2C-27 (#7) | - | insufficient_context -> insufficient_context | False | In which step does a list of selected items appear? |
| P12-048 | answerable | M2C-24 | M2C-24 (#1) | M2C-24 (#1) | - | insufficient_context -> insufficient_context | False | In which step do I enter an amount in the Installment Amount field? |
| P12-049 | answerable | M2C-07 | M2C-07 (#1) | M2C-07 (#1) | - | insufficient_context -> insufficient_context | False | What does the asterisk in the table of monitoring options mean? |
| P12-050 | answerable | M2C-24 | M2C-25 (#3) | M2C-24 (#1) | YES | insufficient_context -> answered | False -> **True** | How do I copy default values into the first screen when entering installment plan parameters? |
| P12-051 | answerable | M2C-24 | M2C-25 (#2) | M2C-24 (#1) | YES | answered -> answered | False -> **True** | What can be changed in an installment plan proposal before it is saved? |
| P12-052 | answerable | M2C-02 | M2C-04 (#3) | M2C-02 (#1) | YES | answered -> answered | False -> **True** | What does the move-in/out component do for a customer who leaves? |
| P12-053 | answerable | M2C-07 | M2C-07 (#1) | M2C-07 (#1) | - | answered -> answered | False | Which lists exist for checking results after meters have been read? |
| P12-054 | answerable | M2C-11 | M2C-12 (#4) | M2C-11 (#1) | YES | insufficient_context -> answered | False -> **True** | How does the billing procedure cope with changes to master data during a period? |
| P12-055 | answerable | M2C-14 | M2C-14 (#1) | M2C-14 (#1) | - | answered -> answered | True | What does invoicing do with the contracts of one contract account? |
| P12-056 | answerable | M2C-17 | M2C-18 (#2) | M2C-17 (#1) | YES | unresolved_identity -> answered | False -> **True** | Is each contract tied to a single contract account in the insurance component? |
| P12-057 | answerable | M2C-05 | M2C-05 (#1) | M2C-05 (#1) | - | answered -> answered | False | Which application component supplies the equipment records for devices? |
| P12-058 | answerable | M2C-05 | M2C-05 (#1) | M2C-05 (#1) | - | answered -> answered | True | What does Device Management say about advanced metering infrastructure? |
| P12-059 | answerable | M2C-05 | M2C-05 (#1) | M2C-05 (#1) | - | answered -> answered | True | Which component handles stock transfers of devices? |
| P12-060 | answerable | M2C-05 | M2C-05 (#1) | M2C-05 (#1) | - | answered -> answered | True | How is a device uniquely identified? |
| P12-061 | answerable | M2C-05 | M2C-05 (#1) | M2C-05 (#1) | - | answered -> answered | True | Which standard-system object stands for the device category in IS-U? |
| P12-062 | answerable | M2C-05 | M2C-05 (#1) | M2C-05 (#1) | - | answered -> answered | True | Is the equipment number the same everywhere in the system? |
| P12-063 | answerable | M2C-05 | M2C-05 (#1) | M2C-05 (#1) | - | insufficient_context -> insufficient_context | False | Which hardware-related tasks does the device component cover? |
| P12-064 | answerable | M2C-14 | M2C-04 (#2) | M2C-14 (#1) | YES | out_of_domain -> answered | False -> **True** | What does the Full Reversal function do? |
| P12-065 | answerable | M2C-14 | M2C-14 (#1) | M2C-14 (#1) | - | answered -> answered | True | Which function releases bills that were outsorted? |
| P12-066 | absent_detail | M2C-07 | M2C-06 (#4) | M2C-07 (#1) | YES | insufficient_context -> insufficient_context | False | What is the maximum number of meter reading orders that transaction EL31 can display? |
| P12-067 | absent_detail | M2C-07 | M2C-22 (#22) | M2C-02 (#22) | YES | out_of_domain -> insufficient_context | False | How often does transaction EL32 run automatically? |
| P12-068 | absent_detail | M2C-07 | M2C-18 (#16) | M2C-17 (#16) | YES | out_of_domain -> insufficient_context | False | Which authorization object protects transaction EL43? |
| P12-069 | absent_detail | M2C-05 | M2C-09 (#5) | M2C-05 (#1) | YES | out_of_domain -> insufficient_context | False | Up to how many digits may a serial number have? |
| P12-070 | absent_detail | M2C-05 | M2C-05 (#1) | M2C-05 (#1) | - | insufficient_context -> insufficient_context | False | Which database table stores the devices? |
| P12-071 | absent_detail | M2C-24 | M2C-24 (#1) | M2C-24 (#1) | - | answered -> answered | False | Which interval type is preselected for new installment plans? |
| P12-072 | absent_detail | M2C-24 | M2C-23 (#2) | M2C-23 (#2) | - | insufficient_context -> insufficient_context | False | How many installments can an installment plan have at most? |
| P12-073 | absent_detail | M2C-24 | M2C-23 (#2) | M2C-24 (#1) | YES | out_of_domain -> insufficient_context | False | Within how many days must the first installment be paid? |
| P12-074 | absent_detail | M2C-14 | M2C-27 (#6) | M2C-25 (#6) | YES | out_of_domain -> insufficient_context | False | What is the retention period for print documents? |
| P12-075 | absent_detail | M2C-14 | M2C-14 (#1) | M2C-14 (#1) | - | insufficient_context -> insufficient_context | False | Which output type is used by default when printing bills? |
| P12-076 | absent_detail | M2C-17 | M2C-18 (#2) | M2C-17 (#1) | YES | unresolved_identity -> insufficient_context | False | What is the upper limit of contract accounts per business partner? |
| P12-077 | absent_detail | M2C-17 | M2C-18 (#2) | M2C-17 (#1) | YES | unresolved_identity -> insufficient_context | False | What is the maximum number of characters in a contract account number? |
| P12-078 | absent_detail | M2C-11 | M2C-16 (#4) | M2C-11 (#1) | YES | unresolved_identity -> insufficient_context | False | What is the shortest billing period that is supported? |
| P12-079 | absent_detail | M2C-11 | M2C-11 (#1) | M2C-11 (#1) | - | insufficient_context -> insufficient_context | False | Which rounding rule does billing apply to partial amounts? |
| P12-080 | absent_detail | M2C-02 | M2C-25 (#5) | M2C-04 (#3) | YES | out_of_domain -> insufficient_context | False | How many days before a move-out date must the notice be given? |
| P12-081 | absent_detail | M2C-02 | M2C-03 (#4) | M2C-03 (#3) | - | insufficient_context -> insufficient_context | False | Which fee applies to a move-in? |
| P12-082 | not_ingested | M2C-25 | M2C-23 (#2) | M2C-23 (#2) | - | answered -> answered | False | Where can I look at an installment plan that was already saved? |
| P12-083 | not_ingested | M2C-04 | M2C-04 (#1) | M2C-04 (#1) | - | insufficient_context -> insufficient_context | False | What steps does a move-out require? |
| P12-084 | not_ingested | M2C-03 | M2C-03 (#1) | M2C-03 (#1) | - | answered -> answered | False | How is a move-in carried out step by step? |
| P12-085 | not_ingested | M2C-12 | M2C-12 (#1) | M2C-12 (#1) | - | answered -> answered | False | How does automatic billing run? |
| P12-086 | not_ingested | M2C-08 | M2C-08 (#1) | M2C-08 (#1) | - | answered -> answered | False | How are missing meter readings estimated? |
| P12-087 | not_ingested | M2C-09 | M2C-09 (#1) | M2C-09 (#1) | - | answered -> answered | False | Which estimation procedures are available for meter readings? |
| P12-088 | not_ingested | M2C-23 | M2C-23 (#1) | M2C-23 (#1) | - | answered -> answered | False | What does the installment plan overview describe? |
| P12-089 | not_ingested | M2C-23 | M2C-24 (#2) | M2C-23 (#1) | YES | insufficient_context -> insufficient_context | False | When are installment plans used instead of paying a bill at once? |
| P12-090 | not_ingested | M2C-26 | M2C-27 (#2) | M2C-26 (#1) | YES | insufficient_context -> answered | False | How does dunning work for overdue receivables? |
| P12-091 | not_ingested | M2C-29 | M2C-29 (#1) | M2C-29 (#1) | - | answered -> answered | False | How is a utility installation disconnected and reconnected? |
| P12-092 | unresolved_identity | M2C-18 | M2C-18 (#1) | M2C-17 (#4) | YES | unresolved_identity -> answered | False | What is the contract account business object? |
| P12-093 | unresolved_identity | M2C-18 | M2C-18 (#1) | M2C-17 (#4) | YES | unresolved_identity -> insufficient_context | False | Which fields make up the contract account business object? |
| P12-094 | unresolved_identity | M2C-18 | M2C-18 (#1) | M2C-17 (#5) | YES | unresolved_identity -> insufficient_context | False | What methods does the contract account object offer? |
| P12-095 | unresolved_identity | M2C-13 | M2C-13 (#1) | M2C-15 (#5) | YES | unresolved_identity -> answered | False | What is a budget billing plan used for? |
| P12-096 | unresolved_identity | M2C-16 | M2C-14 (#2) | M2C-14 (#4) | - | answered -> answered | False | What does the billing and invoicing analysis report? |
| P12-097 | unresolved_identity | M2C-01 | M2C-01 (#1) | M2C-03 (#5) | YES | unresolved_identity -> insufficient_context | False | What is covered by utilities master data? |
| P12-098 | ambiguous | M2C-24 | M2C-24 (#1) | M2C-24 (#1) | - | answered -> answered | False | How do I create a plan? |
| P12-099 | ambiguous | M2C-14 | M2C-13 (#3) | M2C-14 (#1) | YES | unresolved_identity -> answered | False | What does the bill contain? |
| P12-100 | ambiguous | M2C-17 | M2C-17 (#1) | M2C-17 (#1) | - | answered -> answered | False | How is the account managed? |
| P12-101 | ambiguous | M2C-02 | M2C-03 (#1) | M2C-04 (#1) | YES | answered -> answered | False | What happens during the move? |
| P12-102 | ambiguous | M2C-07 | M2C-07 (#1) | M2C-07 (#1) | - | answered -> answered | False | What does the monitoring show? |
| P12-103 | ambiguous | M2C-07 | M2C-05 (#1) | M2C-05 (#1) | - | out_of_domain -> out_of_domain | False | What do I need to activate? |
| P12-104 | ambiguous | M2C-05 | M2C-05 (#1) | M2C-05 (#1) | - | answered -> answered | False | How are devices handled? |
| P12-105 | ambiguous | M2C-11 | M2C-11 (#1) | M2C-12 (#1) | YES | answered -> answered | False | Tell me about billing. |
| P12-106 | out_of_domain | None | M2C-17 (#N/A) | M2C-17 (#N/A) | - | out_of_domain -> out_of_domain | False | What is the capital of Australia? |
| P12-107 | out_of_domain | None | M2C-26 (#N/A) | M2C-06 (#N/A) | YES | out_of_domain -> out_of_domain | False | Give me a JavaScript snippet that sorts an array of numbers. |
| P12-108 | out_of_domain | None | M2C-27 (#N/A) | M2C-27 (#N/A) | - | out_of_domain -> out_of_domain | False | Which football team won the 2018 World Cup? |
| P12-109 | out_of_domain | None | M2C-22 (#N/A) | M2C-24 (#N/A) | YES | out_of_domain -> insufficient_context | False | How do I set up sourcing events in SAP Ariba? |
| P12-110 | out_of_domain | None | M2C-09 (#N/A) | M2C-09 (#N/A) | - | out_of_domain -> out_of_domain | False | What is the boiling point of water? |
| P12-111 | out_of_domain | None | M2C-04 (#N/A) | M2C-03 (#N/A) | YES | out_of_domain -> out_of_domain | False | Explain how photosynthesis works. |
| P12-112 | out_of_domain | None | M2C-25 (#N/A) | M2C-25 (#N/A) | - | insufficient_context -> insufficient_context | False | How can I change the language of my Android phone? |
| P12-113 | out_of_domain | None | M2C-11 (#N/A) | M2C-09 (#N/A) | YES | out_of_domain -> out_of_domain | False | Which compression does the SAP HANA database use for columns? |
