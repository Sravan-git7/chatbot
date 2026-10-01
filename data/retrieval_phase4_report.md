# Phase 4 report - card-level retrieval units, embeddings and retrieval evaluation

Decision applied: **Strategy A (one retrieval unit per card)**. Every card keeps two representations: `full_text` (complete normalised card, unchanged) and `embedding_text` (card text without the two boilerplate sections). Section-based and bounded-section strategies were not used. No SAP page content was added, no protected RAG script was modified, and the new collection is not connected to the existing application.

## 1. Tokenizer and model

* embedding model: **all-MiniLM-L6-v2** (the name configured in `scripts/rag_core.py`; unchanged)
* model files come from: pip package gt-all-minilm-l6-v2 (third-party re-packaging of sentence-transformers/all-MiniLM-L6-v2). huggingface.co is not reachable from the build sandbox, so the weights were taken from this PyPI package; it is a **third-party packaging, not an official release**. File hashes are recorded below.
* tokenizer: `BertTokenizer` (vocabulary 30522) loaded from the packaged model files; sentence-transformers `max_seq_length` = **256** tokens (position-embedding limit 512)
* counts include the special tokens `[CLS]` and `[SEP]` and were made **without truncation**

| Model file | sha256 |
|---|---|
| `model.safetensors` | `53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db` |
| `tokenizer.json` | `be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037` |
| `vocab.txt` | `07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3` |
| `config.json` | `953f9c0d463486b10a6871cc2fd59f223b2c70184f49815e7efbcab5d8908b41` |
| `sentence_bert_config.json` | `fc1993fde0a95c24ec6c022539d41cf6e2f7c9721e5415d6fb6897472a9cd4b7` |
| `modules.json` | `84e40c8e006c9b1d6c122e02cba9b02458120b5fb0c87b746c41e0207cf642cf` |

## 2. Token statistics

| Text | Min | Median | Mean | Max | Model limit |
|---|--:|--:|--:|--:|--:|
| full_text (not embedded) | 214 | 228.0 | 227.9 | 245 | 256 |
| embedding_text (embedded) | 129 | 143.0 | 142.9 | 160 | 256 |

Per-source token counts:

| Source | Title | full_text tokens | embedding_text tokens | Headroom under limit (embedding_text) |
|---|---|--:|--:|--:|
| M2C-01 | Utilities Master Data | 240 | 155 | 101 |
| M2C-02 | Move-In/Out Overview | 228 | 143 | 113 |
| M2C-03 | Move-In Process | 234 | 149 | 107 |
| M2C-04 | Move-Out Process | 228 | 143 | 113 |
| M2C-05 | Device Management Overview | 227 | 142 | 114 |
| M2C-06 | Reading Meters | 235 | 150 | 106 |
| M2C-07 | Monitoring Meter Reading Results | 225 | 140 | 116 |
| M2C-08 | Meter Reading Estimation | 224 | 139 | 117 |
| M2C-09 | Estimation Procedure Details | 234 | 149 | 107 |
| M2C-10 | Meter Reading Data During Move-In | 230 | 145 | 111 |
| M2C-11 | SAP Utilities Billing Procedure | 220 | 135 | 121 |
| M2C-12 | Automatic Billing | 222 | 137 | 119 |
| M2C-13 | Budget Billing Plan | 223 | 138 | 118 |
| M2C-14 | SAP Utilities Invoicing Procedure | 233 | 148 | 108 |
| M2C-15 | Processing Budget Billing Plans | 219 | 134 | 122 |
| M2C-16 | Periodic Billing and Invoicing Analysis | 226 | 141 | 115 |
| M2C-17 | Contract Accounts Overview | 225 | 140 | 116 |
| M2C-18 | Contract Account Business Object | 235 | 150 | 106 |
| M2C-19 | Analyze Incoming Payments | 219 | 134 | 122 |
| M2C-20 | Clearing Control in Incoming Payments | 230 | 145 | 111 |
| M2C-21 | Clearing Types | 229 | 144 | 112 |
| M2C-22 | Processing Incoming Payments from External Cash Desks | 223 | 138 | 118 |
| M2C-23 | Installment Plan Overview | 233 | 148 | 108 |
| M2C-24 | Creating Installment Plans | 214 | 129 | 127 |
| M2C-25 | Displaying and Changing Installment Plans | 219 | 134 | 122 |
| M2C-26 | FI-CA Dunning | 228 | 143 | 113 |
| M2C-27 | Submission of Receivables to Collection Agency | 232 | 147 | 109 |
| M2C-28 | Collection Agency APIs and Enterprise Services | 228 | 143 | 113 |
| M2C-29 | Disconnection/Reconnection of a Utility Installation | 245 | 160 | 96 |

## 3. Truncation findings

* verdict: **PASS: every embedding_text fits the model input length**
* embedding_text over the limit: none; full_text over the limit: none
* the largest full_text is 245 tokens, below 256, so even the complete card would not be truncated. The earlier chars/4 estimate (about 279) in the Phase 3 report was too high; the real tokenizer count replaces it.
* no text was truncated and the model was not changed. The embedding stage ran only after this check passed.

## 4. Retrieval-unit statistics

* units: **29** (one per source PDF; ids `M2C-01`..`M2C-29`) in `data/retrieval_units.json` (sha256 `f5e9b908c9b7374ffab5adbc6f8afb9b5597de91cb50ec3fea8b9b3db2d3ff21`)
* full_text characters: 29674 in total; embedding_text characters: 14710 in total (49.6% of full_text)
* per unit: full_text 974-1116 chars; embedding_text 458-600 chars
* review state carried on every unit: 26 verified, 3 needs_review (M2C-14, M2C-18, M2C-23); source correction metadata on M2C-05; none of it resolved

## 5. Boilerplate exclusion rule

> embedding_text = full_text minus the heading line and body of the sections `library_use` and `copyright_note`; all other sections are kept verbatim in their original order with their original separator whitespace; no text is rewritten, added or summarised; leading/trailing whitespace is stripped.

* excluded sections (fixed list): `library_use`, `copyright_note`. The builder refuses to run if these sections are not identical in all 29 cards.
* kept verbatim: reference line, title, category line, *What it covers*, *Meter-to-Cash relevance*, *Authoritative SAP Help source* and its URL.
* `embedding_text` is an exact prefix of `full_text` for every card; the excluded character ranges are stored in each unit (`embedding_text_spec`). Nothing was rewritten or generated.

## 6-10. Embedding collection

| Item | Value |
|---|---|
| embedding model | `all-MiniLM-L6-v2` |
| vector dimensions | **384** |
| collection name | `sap_m2c_card_v1` (new; the legacy `sap_docs` collection was not touched) |
| vector store directory | `data/vector_store` (separate from the legacy `chroma_db/`, git-ignored, rebuilt by script) |
| vector count | **29** |
| distance space / normalisation | cosine / normalised embeddings |
| document embedded | `embedding_text` |
| created (UTC) | 2026-09-30T14:22:20+00:00 |
| source corpus file sha256 | `0ee5cb8bda192250a14acdde95617e15b71f6fd803847fe25bae9999ea7e9e76` |
| source corpus content fingerprint | `8eed668f4ac4cf951bd41df5ff94688abb7331bd05e283da1045abd1eb017cda` |
| retrieval units file sha256 | `f5e9b908c9b7374ffab5adbc6f8afb9b5597de91cb50ec3fea8b9b3db2d3ff21` |
| token statistics file sha256 | `e5213166b4178f8c3d3dc8e52e7e9438abf881e0ae7564045079955e4d3b051c` |
| embeddings (float32) sha256 | `0d80d10bb4e22f9311e346fd9c01b2216a2a720b08ebbb6411909c6577aecc0a` (this machine only) |
| chromadb | 1.5.9 |
| rebuild | `python scripts/build_retrieval_units.py && python scripts/validate_token_lengths.py && python scripts/build_card_collection.py --rebuild` |

Each vector record holds the embedded text plus readable metadata: retrieval_unit_id, source_id, source_number, title, category, filename, source_url, source_status, source_url_status, has_source_correction, citation, sha256, corpus_document, page_start/page_end, embedding_text_sha256 and full_text_sha256. Before inserting, the script verified the collection was new and empty, and afterwards that it held 29 vectors.

## 11-15. Evaluation

* evaluation set: **50 questions** in `data/evaluation/card_retrieval_questions.json` (sha256 `530f2d96cb644518fcbe20b0082870b01a08fd4bc524c10d208fd9c72c1ceb36`), written by hand from the card text before any retrieval was run; every expected source has a verbatim evidence quote from that card. No LLM was used.
* a question is a **hit@k** if any expected source is among the top k of the 29 cards; MRR uses the rank of the first expected source.

| Metric | All questions | Unambiguous only | Ambiguous only |
|---|--:|--:|--:|
| questions | 50 | 32 | 18 |
| recall@1 | 0.92 | 0.9062 | 0.9444 |
| recall@3 | 0.96 | 0.9375 | 1.0 |
| recall@5 | 1.0 | 1.0 | 1.0 |
| mrr | 0.95 | 0.9375 | 0.9722 |

**Recall@1 = 0.92**, **Recall@3 = 0.96**, **Recall@5 = 1.0**, **MRR = 0.95** (46 of 50 questions have the expected card at rank 1).

By question type:

| Type | Questions | Recall@1 | Recall@3 | Recall@5 | MRR | Mean share of expected cards found in top 3 |
|---|--:|--:|--:|--:|--:|--:|
| ambiguous | 7 | 0.8571 | 1.0 | 1.0 | 0.9286 | 1.0 |
| category | 4 | 1.0 | 1.0 | 1.0 | 1.0 | 0.9375 |
| distinctive_term | 8 | 0.75 | 0.75 | 1.0 | 0.8125 | 0.75 |
| exact_title | 11 | 0.9091 | 1.0 | 1.0 | 0.9545 | 1.0 |
| m2c_relevance | 10 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| semantic | 10 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |

How to read this: the set is small (one question moves Recall@1 by 2 points), and many questions reuse wording from the cards, so the numbers describe retrieval over card text, not over real user phrasing. Chance level on 29 cards is about 3% for Recall@1 and 17% for Recall@5 for a single expected card. This is not a claim that retrieval is 'good'; it is a measurement.

### Control: boilerplate included (in memory, nothing stored)

| Text embedded | Recall@1 | Recall@3 | Recall@5 | MRR |
|---|--:|--:|--:|--:|
| embedding_text (evaluated collection) | 0.92 | 0.96 | 1.0 | 0.95 |
| full_text (control, not a collection) | 0.88 | 0.98 | 0.98 | 0.9262 |

The two rows differ by a few questions in either direction, which this set is too small to call a difference. The control shows that excluding the boilerplate did not cost measurable retrieval here; it does not prove it helps.

## 16. Per-question results

Rank = position of the first expected source among all 29 cards. Retrieved = top 3 as `source id title (cosine similarity)`.

| ID | Type | Question | Expected | Rank | Top-1 retrieved | Top-2 | Top-3 | Amb. |
|---|---|---|---|--:|---|---|---|---|
| Q01 | exact_title | Move-In Process | M2C-03 | 1 | M2C-03 Move-In Process (0.4779) | M2C-04 Move-Out Process (0.3997) | M2C-10 Meter Reading Data During Move-In (0.2931) |  |
| Q02 | exact_title | Move-Out Process | M2C-04 | 1 | M2C-04 Move-Out Process (0.4914) | M2C-03 Move-In Process (0.4148) | M2C-02 Move-In/Out Overview (0.2939) |  |
| Q03 | exact_title | Automatic Billing | M2C-12 | 1 | M2C-12 Automatic Billing (0.5091) | M2C-13 Budget Billing Plan (0.3788) | M2C-11 SAP Utilities Billing Procedure (0.3672) |  |
| Q04 | exact_title | Budget Billing Plan | M2C-13 | 1 | M2C-13 Budget Billing Plan (0.5675) | M2C-15 Processing Budget Billing Plans (0.5006) | M2C-11 SAP Utilities Billing Procedure (0.4317) | yes |
| Q05 | exact_title | Clearing Types | M2C-21 | 1 | M2C-21 Clearing Types (0.4988) | M2C-20 Clearing Control in Incoming Payments (0.3482) | M2C-19 Analyze Incoming Payments (0.2415) |  |
| Q06 | exact_title | FI-CA Dunning | M2C-26 | 1 | M2C-26 FI-CA Dunning (0.3749) | M2C-18 Contract Account Business Object (0.2631) | M2C-28 Collection Agency APIs and Enterprise Services (0.2572) |  |
| Q07 | exact_title | Installment Plan Overview | M2C-23 | **2** | M2C-24 Creating Installment Plans (0.6323) | M2C-23 Installment Plan Overview (0.6299) | M2C-25 Displaying and Changing Installment Plans (0.5647) |  |
| Q08 | exact_title | Collection Agency APIs and Enterprise Services | M2C-28 | 1 | M2C-28 Collection Agency APIs and Enterprise Services (0.6103) | M2C-27 Submission of Receivables to Collection Agency (0.5201) | M2C-17 Contract Accounts Overview (0.3817) |  |
| Q09 | exact_title | Reading Meters | M2C-06 | 1 | M2C-06 Reading Meters (0.4908) | M2C-08 Meter Reading Estimation (0.4504) | M2C-07 Monitoring Meter Reading Results (0.4272) |  |
| Q10 | exact_title | Contract Accounts Overview | M2C-17 | 1 | M2C-17 Contract Accounts Overview (0.5963) | M2C-18 Contract Account Business Object (0.5824) | M2C-24 Creating Installment Plans (0.3787) | yes |
| Q11 | exact_title | Disconnection/Reconnection of a Utility Installation | M2C-29 | 1 | M2C-29 Disconnection/Reconnection of a Utility Installation (0.6246) | M2C-03 Move-In Process (0.254) | M2C-02 Move-In/Out Overview (0.2248) |  |
| Q12 | semantic | Which reference explains how billing results become invoices, print documents and postings in FI-CA? | M2C-14 | 1 | M2C-14 SAP Utilities Invoicing Procedure (0.7217) | M2C-11 SAP Utilities Billing Procedure (0.5306) | M2C-15 Processing Budget Billing Plans (0.5289) |  |
| Q13 | semantic | What explains estimating a reading when the meter reading is missing or unavailable? | M2C-08 | 1 | M2C-08 Meter Reading Estimation (0.6888) | M2C-07 Monitoring Meter Reading Results (0.447) | M2C-06 Reading Meters (0.4436) | yes |
| Q14 | semantic | How are incoming payment amounts assigned to open items? | M2C-20 | 1 | M2C-20 Clearing Control in Incoming Payments (0.5745) | M2C-19 Analyze Incoming Payments (0.3786) | M2C-11 SAP Utilities Billing Procedure (0.3606) |  |
| Q15 | semantic | Which topic covers releasing, submitting, processing and recalling receivables handled by collection agencies? | M2C-27 | 1 | M2C-27 Submission of Receivables to Collection Agency (0.6878) | M2C-26 FI-CA Dunning (0.45) | M2C-28 Collection Agency APIs and Enterprise Services (0.4435) |  |
| Q16 | semantic | How are source receivables redistributed into scheduled installment receivables? | M2C-23 | 1 | M2C-23 Installment Plan Overview (0.5436) | M2C-27 Submission of Receivables to Collection Agency (0.5262) | M2C-24 Creating Installment Plans (0.3681) |  |
| Q17 | semantic | Temporary interruption and restoration of utility supply for collection or technical reasons | M2C-29 | 1 | M2C-29 Disconnection/Reconnection of a Utility Installation (0.4875) | M2C-27 Submission of Receivables to Collection Agency (0.3139) | M2C-02 Move-In/Out Overview (0.2917) |  |
| Q18 | semantic | How are notifications of incoming payments from external cash desks integrated into FI-CA? | M2C-22 | 1 | M2C-22 Processing Incoming Payments from External Cash Desks (0.7249) | M2C-20 Clearing Control in Incoming Payments (0.4759) | M2C-28 Collection Agency APIs and Enterprise Services (0.4272) |  |
| Q19 | semantic | Which source lists Business Partner, Contract Account, Contract, Point of Delivery, Connection Object, Premise, Device Location, Installation and Device? | M2C-01 | 1 | M2C-01 Utilities Master Data (0.5117) | M2C-17 Contract Accounts Overview (0.4589) | M2C-18 Contract Account Business Object (0.4518) |  |
| Q20 | semantic | What covers the creation of the customer-service relationship for a utility installation? | M2C-03 | 1 | M2C-03 Move-In Process (0.5287) | M2C-02 Move-In/Out Overview (0.4142) | M2C-29 Disconnection/Reconnection of a Utility Installation (0.4066) | yes |
| Q21 | semantic | What covers the termination of the customer-service relationship and related final processing? | M2C-04 | 1 | M2C-04 Move-Out Process (0.5789) | M2C-03 Move-In Process (0.4482) | M2C-02 Move-In/Out Overview (0.427) |  |
| Q22 | m2c_relevance | Which source is important for estimated-bill and catch-up-bill reasoning? | M2C-08 | 1 | M2C-08 Meter Reading Estimation (0.5027) | M2C-13 Budget Billing Plan (0.483) | M2C-15 Processing Budget Billing Plans (0.4469) |  |
| Q23 | m2c_relevance | Which reference is critical for distinguishing billing document, invoicing result, customer bill and FI-CA document? | M2C-14 | 1 | M2C-14 SAP Utilities Invoicing Procedure (0.6783) | M2C-15 Processing Budget Billing Plans (0.4968) | M2C-16 Periodic Billing and Invoicing Analysis (0.4882) |  |
| Q24 | m2c_relevance | Which source teaches that payment receipt and open-item clearing are distinct steps? | M2C-20 | 1 | M2C-20 Clearing Control in Incoming Payments (0.6449) | M2C-19 Analyze Incoming Payments (0.4865) | M2C-21 Clearing Types (0.4683) |  |
| Q25 | m2c_relevance | Which source is the core reference for collections escalation logic within Meter-to-Cash? | M2C-26 | 1 | M2C-26 FI-CA Dunning (0.6206) | M2C-27 Submission of Receivables to Collection Agency (0.6119) | M2C-28 Collection Agency APIs and Enterprise Services (0.5669) |  |
| Q26 | m2c_relevance | Why can interim or budget amounts affect the customer balance independently of final consumption billing? | M2C-13 | 1 | M2C-13 Budget Billing Plan (0.5608) | M2C-15 Processing Budget Billing Plans (0.4377) | M2C-16 Periodic Billing and Invoicing Analysis (0.3941) | yes |
| Q27 | m2c_relevance | Which card preserves the distinction between delinquency and disconnect eligibility? | M2C-29 | 1 | M2C-29 Disconnection/Reconnection of a Utility Installation (0.3929) | M2C-04 Move-Out Process (0.2127) | M2C-24 Creating Installment Plans (0.1923) |  |
| Q28 | m2c_relevance | Which source covers modern API and service integration beyond file-based exchanges? | M2C-28 | 1 | M2C-28 Collection Agency APIs and Enterprise Services (0.5423) | M2C-02 Move-In/Out Overview (0.3796) | M2C-01 Utilities Master Data (0.3634) |  |
| Q29 | m2c_relevance | Which source is useful for differentiating payment-lot, cash-desk, account-maintenance and payment-run clearing contexts? | M2C-21 | 1 | M2C-21 Clearing Types (0.5898) | M2C-19 Analyze Incoming Payments (0.5187) | M2C-13 Budget Billing Plan (0.5018) |  |
| Q30 | m2c_relevance | Which source is useful for operational monitoring, KPIs and exception-management of periodic billing and invoicing? | M2C-16 | 1 | M2C-16 Periodic Billing and Invoicing Analysis (0.6763) | M2C-07 Monitoring Meter Reading Results (0.4998) | M2C-15 Processing Budget Billing Plans (0.4958) | yes |
| Q31 | m2c_relevance | Which source helps with exception monitoring and support or troubleshooting scenarios for meter-reading results? | M2C-07 | 1 | M2C-07 Monitoring Meter Reading Results (0.6785) | M2C-06 Reading Meters (0.6067) | M2C-08 Meter Reading Estimation (0.5425) | yes |
| Q32 | category | Which card is in the Disconnection & Reconnection category? | M2C-29 | 1 | M2C-29 Disconnection/Reconnection of a Utility Installation (0.5048) | M2C-04 Move-Out Process (0.283) | M2C-02 Move-In/Out Overview (0.2556) |  |
| Q33 | category | Which cards belong to the Dunning & Collections category? | M2C-26, M2C-27, M2C-28 | 1 | M2C-26 FI-CA Dunning (0.4342) | M2C-27 Submission of Receivables to Collection Agency (0.354) | M2C-28 Collection Agency APIs and Enterprise Services (0.3301) | yes |
| Q34 | category | Which cards belong to Payment Arrangements / Installment Plans? | M2C-23, M2C-24, M2C-25 | 1 | M2C-23 Installment Plan Overview (0.478) | M2C-24 Creating Installment Plans (0.474) | M2C-25 Displaying and Changing Installment Plans (0.4032) | yes |
| Q35 | category | Which cards are in the Payments & Clearing category? | M2C-19, M2C-20, M2C-21, M2C-22 | 1 | M2C-21 Clearing Types (0.4925) | M2C-20 Clearing Control in Incoming Payments (0.4923) | M2C-19 Analyze Incoming Payments (0.4363) | yes |
| Q36 | distinctive_term | extrapolation and interpolation | M2C-09 | 1 | M2C-09 Estimation Procedure Details (0.2443) | M2C-08 Meter Reading Estimation (0.1254) | M2C-10 Meter Reading Data During Move-In (0.094) |  |
| Q37 | distinctive_term | installation, rate type, schema, operand and price | M2C-12 | 1 | M2C-12 Automatic Billing (0.3644) | M2C-24 Creating Installment Plans (0.343) | M2C-11 SAP Utilities Billing Procedure (0.3291) |  |
| Q38 | distinctive_term | dunning notices and dunning activities for overdue items | M2C-26 | 1 | M2C-26 FI-CA Dunning (0.5317) | M2C-27 Submission of Receivables to Collection Agency (0.4091) | M2C-08 Meter Reading Estimation (0.2913) |  |
| Q39 | distinctive_term | payment clarification | M2C-19 | **4** | M2C-20 Clearing Control in Incoming Payments (0.3839) | M2C-23 Installment Plan Overview (0.3827) | M2C-24 Creating Installment Plans (0.3713) |  |
| Q40 | distinctive_term | monitoring meter-reading results across business objects and organizational criteria | M2C-07 | 1 | M2C-07 Monitoring Meter Reading Results (0.6602) | M2C-06 Reading Meters (0.5762) | M2C-10 Meter Reading Data During Move-In (0.552) |  |
| Q41 | distinctive_term | parent topic for devices and technical installations | M2C-05 | 1 | M2C-05 Device Management Overview (0.2722) | M2C-01 Utilities Master Data (0.2442) | M2C-03 Move-In Process (0.2055) |  |
| Q42 | distinctive_term | subledger processing | M2C-17 | **4** | M2C-15 Processing Budget Billing Plans (0.2484) | M2C-03 Move-In Process (0.2414) | M2C-04 Move-Out Process (0.2372) |  |
| Q43 | distinctive_term | control role of the contract account for postings, payments and dunning | M2C-18 | 1 | M2C-18 Contract Account Business Object (0.547) | M2C-17 Contract Accounts Overview (0.4832) | M2C-20 Clearing Control in Incoming Payments (0.3798) | yes |
| Q44 | ambiguous | How does meter reading data take part in the move-in process? | M2C-10 | 1 | M2C-10 Meter Reading Data During Move-In (0.6751) | M2C-06 Reading Meters (0.4849) | M2C-03 Move-In Process (0.4684) | yes |
| Q45 | ambiguous | How are budget billing plans treated in invoicing? | M2C-15 | 1 | M2C-15 Processing Budget Billing Plans (0.6631) | M2C-14 SAP Utilities Invoicing Procedure (0.5118) | M2C-13 Budget Billing Plan (0.5009) | yes |
| Q46 | ambiguous | Explain the estimation procedure for meter readings | M2C-08, M2C-09 | 1 | M2C-08 Meter Reading Estimation (0.5716) | M2C-09 Estimation Procedure Details (0.5275) | M2C-06 Reading Meters (0.4315) | yes |
| Q47 | ambiguous | Overview of starting and ending utility service | M2C-02 | 1 | M2C-02 Move-In/Out Overview (0.5611) | M2C-03 Move-In Process (0.4718) | M2C-04 Move-Out Process (0.4423) | yes |
| Q48 | ambiguous | How are installment plans created? | M2C-24 | 1 | M2C-24 Creating Installment Plans (0.6078) | M2C-23 Installment Plan Overview (0.5887) | M2C-25 Displaying and Changing Installment Plans (0.5092) | yes |
| Q49 | ambiguous | What is needed for final billing when a customer moves out? | M2C-04 | **2** | M2C-02 Move-In/Out Overview (0.4415) | M2C-04 Move-Out Process (0.4335) | M2C-03 Move-In Process (0.3794) | yes |
| Q50 | ambiguous | How does a collection agency get involved when receivables stay unpaid? | M2C-27, M2C-28 | 1 | M2C-27 Submission of Receivables to Collection Agency (0.5757) | M2C-23 Installment Plan Overview (0.3284) | M2C-28 Collection Agency APIs and Enterprise Services (0.3252) | yes |

## 17. Failed cases

* not at rank 1 (failed@1): Q07, Q39, Q42, Q49
* not in top 3 (failed@3): Q39, Q42
* not in top 5 (failed@5): none
* questions labelled ambiguous before the run: Q04, Q10, Q13, Q20, Q26, Q30, Q31, Q33, Q34, Q35, Q43, Q44, Q45, Q46, Q47, Q48, Q49, Q50 (18)

These notes were written after the evaluation ran, from the retrieved results in `data/evaluation/card_retrieval_results.json` and the card texts in `data/retrieval_units.json`. No question, label, threshold or text was changed after seeing the results. Four of the 50 questions missed at rank 1, and two of those also missed at rank 3.

| Question | Expected | What was retrieved (cosine similarity) | Reading of the retrieved text |
|---|---|---|---|
| Q07 "Installment Plan Overview" (exact title) | M2C-23 at rank 2 | rank 1 M2C-24 "Creating Installment Plans" 0.6323; rank 2 M2C-23 0.6299 | Near-tie (difference 0.0024) inside one card family. Cards 23, 24 and 25 share the category line "Payment Arrangements / Installment Plans" and the words "installment plans" in their text, so a title query does not single out one card. Card 24 is a related card, not an unrelated one. |
| Q39 "payment clarification" | M2C-19 at rank 4 | rank 1 M2C-20 "Clearing Control in Incoming Payments" 0.3839; rank 2 M2C-23 0.3827; rank 3 M2C-24 0.3713 | Two-word query with weak signal: every similarity is below 0.39. The tokenizer splits "clarification" into `cl ##ari ##fication`, and the model matched on "payment" in general. Card 19 contains the phrase ("analysis of incoming payments and payment clarification") but the phrase is only a small part of its embedded text. |
| Q42 "subledger processing" | M2C-17 at rank 4 | rank 1 M2C-15 0.2484; rank 2 M2C-03 0.2414; rank 3 M2C-04 0.2372 | Rare single term with almost no signal: the top similarities are all near 0.25 and the retrieved cards (budget billing, move-in, move-out) are unrelated to the query. The tokenizer splits "subledger" into `sub ##led ##ger`, so the model cannot match the word as a term. This is the clearest failure. In the full-text control, M2C-17 ranks 7th. |
| Q49 "What is needed for final billing when a customer moves out?" (ambiguous) | M2C-04 at rank 2 | rank 1 M2C-02 "Move-In/Out Overview" 0.4415; rank 2 M2C-04 0.4335 | Near-tie. Card 02's Meter-to-Cash line also mentions "final billing" ("connecting customer/service setup to billing eligibility and final billing"), so the retrieved card is plausibly relevant. The question was labelled ambiguous before the run, with M2C-02 listed as also relevant. The result is reported as a miss at rank 1, not relabelled. |

What these cases suggest, without changing anything:
- The misses are (a) near-ties between neighbouring cards in one family (Q07, Q49) and (b) very short queries built from a rare or single term, which dense retrieval handles poorly (Q39, Q42).
- For a 29-card collection Recall@5 is lenient: the top 5 covers 17% of the cards. The more informative numbers are Recall@1 and MRR.
- Rank-1 differences of a few thousandths decide some results (Q07, Q49), so a change in wording or in the model can flip them.
- A keyword or hybrid component would address (b). That is a later design decision and was not tried here.

## 18. Provenance validation

* every retrieval unit resolves to exactly one original PDF: `retrieval_unit_id` = `source_id` -> `data/source_corpus.json#<source_id>` -> `filename` + `sha256` (equal to the manifest hash and, in the tests, to the current hash of the PDF in the repository).
* all 29 units have distinct filenames and distinct sha256 values; page range is 1-1 for all cards.
* every vector record carries the same identifiers and hashes as its unit, and the stored document equals the unit's `embedding_text` (checked before evaluating; evaluation aborts otherwise).
* PDFs, `source_manifest.json` and `source_corpus.json` were not modified (hash-checked in the tests).
* no SAP page was externally verified; `verified` still means only what Phase 1 defined. Unresolved items #05, #14, #18 and #23 are carried unchanged in `source_status`, `source_url_status`, `review_reasons` and `source_correction`.

## 19. Tests

pytest tests: **219 passed**, 0 failed = 192 from Phases 1-3 (156 original + 15 source-corpus + 21 chunk-candidate) + 12 new in `tests/test_retrieval_units.py` + 15 new in `tests/test_card_retrieval_eval.py`. The collection, tokenizer and re-run tests skip automatically when chromadb, transformers or the local model files are absent.

## 20. Recommendation for the next phase

1. Review this report, in particular the four rank-1 misses and the evaluation set, before wiring anything into the application.
2. Enlarge the evaluation set with independently written queries (for example short keyword queries and natural user phrasing) before drawing conclusions; 50 questions over 29 cards cannot separate small differences.
3. Decide how to handle short rare-term queries (Q39, Q42): a keyword/hybrid component is the natural candidate and should be tested on the same set. It was not implemented here.
4. Only after that, plan the integration into the RAG pipeline as a separate, reviewed step (prompt, retrieval threshold, citation format), and add SAP page content as its own phase. The card collection describes what each topic covers; it does not contain the SAP answers.
5. Keep `sap_docs` and the protected RAG scripts untouched until that integration is approved.
