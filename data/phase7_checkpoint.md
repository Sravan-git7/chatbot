# Phase 7 checkpoint (taken at the start of Phase 7A, before any Phase 7A file was written)

This is a record of the repository state. Nothing was reverted, deleted, committed or pushed to produce it.
**Ownership is not claimed:** git cannot show who made the working-tree changes (the checkout is a fresh clone with one commit and no stash, and file timestamps carry no information), so none of the changes below is attributed to the user or to an earlier agent turn.

## 1. Git state

| Item | Value |
| --- | --- |
| Branch | `arena/01a0ed60-chatbot` |
| HEAD | `d85c31e0594b472e852ea9e06e32e6eba7138747` (the only commit; equal to `main`) |
| Commits since HEAD | none |
| Tracked files modified vs HEAD | 9 |
| Untracked entries (`git status --short`) | 72 top-level entries (207 files with `-uall`) |

### 1.1 Tracked files modified against HEAD (`git diff --stat`)

| File | Lines changed |
| --- | --- |
| `.gitignore` | 5 |
| `data/retrieval_results.json` | 701 |
| `scripts/audit_corpus.py` | 791 |
| `scripts/chunk_pages.py` | 6 |
| `scripts/clean_sap_pages.py` | 6 |
| `scripts/create_embeddings.py` | 29 |
| `scripts/evaluate_retrieval.py` | 398 |
| `scripts/rag_chat.py` | 493 |
| `scripts/retrieve.py` | 168 |

Total: 988 insertions, 1609 deletions. Details and per-file judgement: `data/phase6_repository_audit.md`.

### 1.2 Untracked files relevant to Phases 1-6

Nothing from Phases 1-5 is tracked: `git ls-files` lists none of the following.

| Group | Paths |
| --- | --- |
| Legacy app refactor companions | `scripts/rag_core.py`, `scripts/evaluate_answers.py`, `data/answer_quality_questions.json`, `data/retrieval_results_improved.json`, `README.md`, `requirements.txt` |
| Phase 1 (source manifest) | `scripts/inspect_pdf_cards.py`, `scripts/build_source_manifest.py`, `data/source_manifest.json`, `data/source_manifest.csv`, `data/source_inventory.md`, `data/source_validation_report.md` |
| Phase 2 (source corpus) | `scripts/build_source_corpus.py`, `data/source_corpus.json`, `data/source_corpus.md`, `data/source_corpus_validation_report.md`, `data/topic_corrections.json` |
| Phase 3 (chunk candidates) | `scripts/build_chunk_candidates.py`, `data/chunk_candidates/` |
| Phase 4 (retrieval units, card collection) | `scripts/m2c_common.py`, `scripts/build_retrieval_units.py`, `scripts/validate_token_lengths.py`, `scripts/build_card_eval_questions.py`, `scripts/build_card_collection.py`, `scripts/evaluate_card_retrieval.py`, `scripts/build_phase4_report.py`, `data/retrieval_units.json`, `data/retrieval_token_stats.json`, `data/card_collection_manifest.json`, `data/retrieval_phase4_report.md`, `data/evaluation/` (Phase 4 and Phase 5 files) |
| Phase 5 (independent evaluation) | `scripts/build_independent_queries.py`, `scripts/phase5_retrievers.py`, `scripts/evaluate_phase5.py`, `scripts/build_phase5_report.py`, `data/retrieval_phase5_report.md` |
| Page-ingestion pipeline and its data | `sap_resolver/`, `scripts/build_corpus.py`, `scripts/guide_intake.py`, `scripts/capture_responses.py`, `scripts/compare_with_legacy.py`, `scripts/resolve_topics.py`, `scripts/repair_captured_response.py`, `scripts/forensic_search.py`, `scripts/corpus_audit.py`, `captured_responses/`, `data/sap_help/`, `data/sap_help_e2e/`, `data/toc/`, `data/forensics/`, `data/logs/`, `data/topic_manifest.json`, `data/topic_resolution.json`, `data/guide_registry.json`, `data/guide_registrations.json`, `data/final_corpus_manifest.*`, `data/corpus_manifest.*`, `data/corpus_audit.*`, `data/ingest_*.json`, `data/captured_url_mapping.*`, `data/captured_pagecontent_urls.txt` |
| Tests | `tests/` (11 files; 260 tests) |
| Phase 6 documents | `data/phase6_repository_audit.md`, `data/phase6_retrieval_integration_map.md`, `data/phase6_next_phase_spec.md` |

## 2. Dependencies and conflicts that matter

* **`scripts/rag_core.py` is required by the modified RAG scripts.** `rag_chat.py`, `retrieve.py`, `evaluate_retrieval.py` and `create_embeddings.py` all `from rag_core import ...`, and `rag_core.py` is **untracked**. Committing only the tracked changes would leave those four scripts unable to import their configuration.
* **`scripts/audit_corpus.py` differs from HEAD and is potentially conflicting.** HEAD holds the Phase 0 PDF audit (667 lines, produced `audit_out/*`); the working tree holds an unrelated 150-line audit of `data/sap_help/`, which `tests/test_corpus_pipeline.py` executes. The Phase 0 tool is recoverable with `git show HEAD:scripts/audit_corpus.py`. It is left as it is (Phase 6 action: investigate; do not revert).
* `data/vector_store/` (card collection) and `chroma_db/` (legacy collection) are gitignored and **absent** in this checkout.

## 3. Current test result

**253 passed, 7 skipped, 0 failed** (`python -m pytest tests -q`, 260 tests collected; reproduced again at the start of Phase 7A, before any Phase 7A file existed).

The 7 skips, all from `pytest.skip` guards on the absent card store `data/vector_store/` (collection `sap_m2c_card_v1`), which Phase 6/7A must not rebuild:

| Test file:line | Reason given |
| --- | --- |
| `tests/test_card_retrieval_eval.py:148`, `:158`, `:172`, `:186` | needs the built `sap_m2c_card_v1` store |
| `tests/test_card_retrieval_eval.py:238` | needs the store and model |
| `tests/test_phase5.py:376`, `:387` | needs the store and model |

"260 passed" is reachable only after the card store is rebuilt with `scripts/build_card_collection.py --rebuild`.

Environment note: the virtual environment used for the tests lives in `/tmp/av` and is not persisted between sessions. It had to be recreated at the start of Phase 7A (PyPI downloads of test tooling only: `pytest pypdf beautifulsoup4 requests numpy chromadb sentence-transformers gt-all-minilm-l6-v2`; no SAP request and no embedding was made). The count depends on the environment: without `sentence-transformers` / the local weights package, the same suite reports 243 passed / 17 skipped, and with `sentence-transformers` but without the weights package 251 passed / 9 skipped, because further guards skip on missing dependencies rather than on the store.

## 4. Commands to reproduce the current state

Linux / macOS shell, from the repository root (`chatbot/`):

```bash
git rev-parse HEAD                      # d85c31e0594b472e852ea9e06e32e6eba7138747
git status --short                      # 9 modified tracked files + untracked entries listed above
git diff --stat                         # 9 files changed, 988 insertions(+), 1609 deletions(-)
python3 -m venv /tmp/av
/tmp/av/bin/pip install pytest pypdf beautifulsoup4 requests numpy chromadb sentence-transformers gt-all-minilm-l6-v2
PYTHONDONTWRITEBYTECODE=1 /tmp/av/bin/python -m pytest tests -q -p no:cacheprovider -rs
# expected before Phase 7A files exist: 253 passed, 7 skipped
```

Windows PowerShell:

```powershell
git rev-parse HEAD
git status --short
git diff --stat
py -3.11 -m venv .venv-test
.\.venv-test\Scripts\pip install pytest pypdf beautifulsoup4 requests numpy chromadb sentence-transformers gt-all-minilm-l6-v2
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv-test\Scripts\python -m pytest tests -q -p no:cacheprovider -rs
```

Verify the protected set against this checkpoint (POSIX): `sed -n '/^<!-- sha256-begin/,/^<!-- sha256-end/p' data/phase7_checkpoint.md | grep -v -e '^<!--' -e '^```' | sha256sum -c -`. The same check runs in `tests/test_phase7a.py::ProtectedArtifactTests`.

## 5. Protected set: SHA-256 at checkpoint time

222 files: the 29 PDFs; `data/source_*`, `data/retrieval_units.json`, `data/retrieval_token_stats.json`, `data/card_collection_manifest.json`, `data/chunk_candidates/*`, `data/evaluation/*`, the Phase 4/5 reports and Phase 6 documents; all existing `scripts/*.py` and `tests/*.py` (Phase 1-6 scripts and tests, legacy app scripts including the modified ones, `rag_core.py`); `sap_resolver/`; `sap_pages/`; `chunks.json`, `cleaned_pages.json`, `.gitignore`, `README.md`, `requirements.txt`, the legacy result and question files; and the local page corpus read by the page join (`data/sap_help/**`). Files created in Phase 7A (`scripts/m2c_router.py`, `scripts/m2c_page_join.py`, `scripts/m2c_orchestrator.py`, `tests/test_phase7a.py`, `data/phase7_checkpoint.md`, `data/phase7A_report.md`) are not in the list.

Absent at checkpoint time: `data/vector_store/`, `chroma_db/` (not hashed; existence is checked by the tests).

<!-- sha256-begin -->
```
3d9fc8507faceada20b17f48bb67a811c279255e0641052749730ecbb8070e81  .gitignore
c4aecd08f56a9cfda1dd8b10914e341478bb2f76f68c2e6f669a7c31266fce40  01_Utilities_Master_Data.pdf
80c862abcf09508bd079014fb7ae1463d49dbe9e7901c5a59b2e781ad2620f04  02_Move_In_Out_Overview.pdf
a360a36d72d1c8bf0ac9de392ad28c9f4a976ea2b619f91723d0f2a5730a93f0  03_Move_In_Process.pdf
2f06b2544b60e7f8e8200d2935dc4975f9528effc756bdce1745e85459f96745  04_Move_Out_Process.pdf
34c7b911e61c2ded45ff0d86b179d24b56d1818a64ed989ea7f496ac557ef6d3  05_Device_Management_Overview.pdf
7b2fbc621ab30b94c45acf3f5e93f13cd9706dc9126ef9640702072b8f0bc245  06_Reading_Meters.pdf
1e5c1ca1c2b882afaa888bfb08170deebd6dc7dec8e8f2cadb3c65995ea37ffd  07_Monitoring_Meter_Reading_Results.pdf
602af6717cf73977c8e1d01f0bccad5d634856df54bf42e26af8bffa3da40532  08_Meter_Reading_Estimation.pdf
e10bdb4dd6e295b4dd7d8be40193f30ba5f05eea41ccd77a73059cea36fc24db  09_Estimation_Procedure_Details.pdf
a0acaa1f1a625505bae741d5ac8d04960c386914f97a2382a6ba7b3185133c9f  10_Meter_Reading_Data_During_Move_In.pdf
b2381818bd893be3217aa562e94639741223cbb98244c008bd7e77432e009579  11_SAP_Utilities_Billing_Procedure.pdf
f8e3ce1a07ed48b0f3b84fe4f323177a58f0ff85c07c34e2f71b980f239cb628  12_Automatic_Billing.pdf
679da0708a9e35159e40aef0e4bafaa6b97c925751f6d7726a37fc37a6c25a3c  13_Budget_Billing_Plan.pdf
ff53f87e163f55f3a5807fc9ababbdb157e0ce28cf278cf433552b6b1e74b8d1  14_SAP_Utilities_Invoicing_Procedure.pdf
ac9f2c91a9064e47fbd4983278f92a6f7498bac863a98c676998228cd1f162f5  15_Processing_Budget_Billing_Plans.pdf
5c91543689208443f5f2bedb19a5584d31ac2400b5c3ee5db569ba3fc2d51232  16_Periodic_Billing_and_Invoicing_Analysis.pdf
0b07f58bc21c42dd9380e5ff0362c3cc609afa7e92fd890b55a469ebd29eb5e1  17_Contract_Accounts_Overview.pdf
36b4c4ac10ac684edbf63899161d03fb64f172e876aa53b3ca27229af1881203  18_Contract_Account_Business_Object.pdf
eb1e19ef4d803f4198719e94e0fb23fb5c7166240eafec145f046b4530f6877b  19_Analyze_Incoming_Payments.pdf
9d03fe95450dd7cc0289d4af9c50ea0ce131d7243cf5690fb84d177685c32199  20_Clearing_Control_in_Incoming_Payments.pdf
66173bede3f79219fbd8b75ca75443c782370f9e5cb7483d4c867dbbaaee6c07  21_Clearing_Types.pdf
3168dba2c1c0a49d9796c6595940e88f0b81193d319d4c5a22fb189dc80fff2d  22_Processing_Incoming_Payments_from_External_Cash_Desks.pdf
5fc82f433e51e612e5fe78e47d1cfb47c5d40fc2bfecb00ac8086009193a9d3b  23_Installment_Plan_Overview.pdf
bf7eb138905ead845cc1471d9aa7d1ea384ac9cdabe95f5d95ed0be739344863  24_Creating_Installment_Plans.pdf
eead43bd7c78f6a4c54a8804db73673e2bfc68ce0f84cac9f2174551e300adb4  25_Displaying_and_Changing_Installment_Plans.pdf
253fe0f03b875557018379d0e55f56b2ce90dd90b4702e96630a9625bfdaec46  26_FI_CA_Dunning.pdf
9ec0594c2ce2ee45bb0fb5f631b7527daa0b5f6a6bd67d44bb97d9fc6c3835ac  27_Submission_of_Receivables_to_Collection_Agency.pdf
521d033f5916316b87f0b94537584c1d40a81a6b8f3153a00233d2c316a178bd  28_Collection_Agency_APIs_and_Enterprise_Services.pdf
07dada4a63ff2ff0f5631f23f01ed42c14916ff0701da8f1e44ae71745145851  29_Disconnection_Reconnection_of_a_Utility_Installation.pdf
406aa51c9c7c8c1e710dbd36f7363e6604551ee7413ad27f2d85b8acb7a1b220  README.md
f5b41a584513c1a8f131495537b68bae98e7c187a4318a37794a686c28633960  chunks.json
9e4b615c34da6acdcf98b59951ee20429162e888b1387f67b5ff614c1014fca0  cleaned_pages.json
7f3cebc62c88eeb718e4041b66aecb021a96b894f017f473e3027ec5003121ab  data/answer_quality_questions.json
5b3a5c30bc637c8b61573983a16cf252f7899d2c279eae3895e06476482d2731  data/card_collection_manifest.json
409884eed5cd10a5dcd9da7ef6b21c3a97cb8023a9739fee41bba0bbac9e1f68  data/chunk_candidates/bounded_sections.json
6737c9b40687891e826e7ca99dafdbed5cebb5c8d3829c92d29547b5c0db0961  data/chunk_candidates/chunk_candidate_report.md
08f19746ecec6df56e3a07d989df5597215886fd0e0689603ca4e9be15469a18  data/chunk_candidates/section_based.json
6ef7069e1a85962ff77ab8ca8e73176d094caa724e5a258b94ef874244c33913  data/chunk_candidates/whole_document.json
c6e6f48680d22ba209e2d8fb76c2e5f3dc42d1c9017f7d814ade73e63a2786f1  data/evaluation/card_retrieval_failure_analysis.md
530f2d96cb644518fcbe20b0082870b01a08fd4bc524c10d208fd9c72c1ceb36  data/evaluation/card_retrieval_questions.json
c1b0459779eeb0ac0f4dbf26c6e128302c91ad7be0aa75db6a2d657e45c49206  data/evaluation/card_retrieval_results.json
1ce1306db646981b68245d75a1a912310ad3d760d90593bd005dfcc3500956e4  data/evaluation/independent_queries.json
a2af755532d9264538a307a8c343a3f929c586f924745295dfa38a6e42128560  data/evaluation/phase5_failure_analysis.md
2ca554287c9c2397f125e086cd121e5bd67983588bf798011e0298b286f0ef6d  data/evaluation/phase5_results.json
dc0801cce3ec63e176062ea46914500169b5cfd8c8a1f2991b060edb3108a674  data/evaluation_questions.json
77ad52cce25deb7aa5b4e44169d2efd087bb864fd1ffa9185bfd92138e979dbc  data/final_corpus_manifest.json
3ce74f9747c73f0a2cb24b0cb6c1073d71c4d2b22ff8fee00203ffd99151d01b  data/guide_registry.json
cba50d5ce435005b873ddd43fa5b37a3fe557c3aebd6b45e9a139fec6a6ff3d2  data/phase6_next_phase_spec.md
6bf4901e71167a7f0d5bc5731ff57f89de1ae0c97edc10b2d8a8dfe3d2cf186d  data/phase6_repository_audit.md
7a0203b22e76adcaffe49ccb0802d398463858380142765fe4f13abcc8f5f795  data/phase6_retrieval_integration_map.md
824fd05e94d2cd2654ad97485710559c6bb969e6586a85948d1cbd06c773c604  data/retrieval_phase4_report.md
ac4e4d034cfe3077d643be978081b9140f50cb8574ef0928a62d92b7cf0ae18b  data/retrieval_phase5_report.md
8edaa6cea367cc814c5ed5de550e061220a7231893c2f702b499b2d89f3de063  data/retrieval_results.json
322f3f34916c81689fbf0b9a0475f5fa6819b91e722099d2a05d0d531020945c  data/retrieval_results_improved.json
e5213166b4178f8c3d3dc8e52e7e9438abf881e0ae7564045079955e4d3b051c  data/retrieval_token_stats.json
f5e9b908c9b7374ffab5adbc6f8afb9b5597de91cb50ec3fea8b9b3db2d3ff21  data/retrieval_units.json
19ca34a6222a65c148293202cc40a52890fcc677852de22851bf2af2772d7c52  data/sap_help/CORPUS.json
5558cf02918cc71af96d88968dc19a2c91d7efffd306cf9e91ad489d02ce05a6  data/sap_help/audit.json
9c75e98df87dff0bc1f6eb499f2e812c8d8f19ee0b67c16c20c81665eb126db3  data/sap_help/audit.md
0f4dfaf8f9a72192090e71464253c5d3b53e858b3cd2ff595d053c61b273b08b  data/sap_help/chunks/chunks.jsonl
5ba3852f889f5521aebc5b0c8433b08c8ab2a84a0ff191dcf1965742df1dedb7  data/sap_help/chunks/embedding_input.jsonl
8ba53455b18f7f2bf3fca435f66711ea93295dc30ae7292c7cb9f6d776b9335f  data/sap_help/comparison_with_legacy.json
1929d41ab76b11fefa45bfab76fc253ab489fbf675beeea4bec58b25e923c05f  data/sap_help/comparison_with_legacy.md
42148bd1eba7ebdf73dcdccc4561c4adbfcac8e3f9d82c005ed843d7aded6608  data/sap_help/corpus_stats.json
63bcfca6f7d3bdabb087539c50fb597e26d5627a0a356b308cc90fe12a28c7ef  data/sap_help/logs/build.jsonl
648fe4b1e28249841dc0be8442a78cd31632934c59d547306cff8a926ace9e59  data/sap_help/pages/e52c8ee6197147ec97dfc2eb8c46a3ad/0bfcc5536a51204be10000000a174cb4.json
a837aac1710897f98143cc61ceb8a2f02ed655dda8f18dd76d013fdbdf97c4e4  data/sap_help/raw/e52c8ee6197147ec97dfc2eb8c46a3ad/0bfcc5536a51204be10000000a174cb4.json
0ee5cb8bda192250a14acdde95617e15b71f6fd803847fe25bae9999ea7e9e76  data/source_corpus.json
08ad208c0187e935377c828faef36ec9fe077704cd580bb38004356f51b740b1  data/source_manifest.json
936500096311853a69c9100aca155f5fed4c352f3b2a74ec4d2fe54f78ee08f6  data/topic_manifest.json
f349fdf470ad4f04e76f0af06b90f71c93fb2bf1e0927d05483c404987619fc7  data/topic_resolution.json
c4ef4516e0d1f574b28877da7e4124ccefcefa34291d45d629703c7aadab4574  extract_toc.py
ae5f50d37a8d838a5c59df2aaac7a183c1f6b67c3ceffc1119d3bafe1f726f4b  fetch_sap_pages.py
e700a061480050b9bdcd7ea9a3a7b85a610a282400f47a5898bdd2c0a9d7e032  master_data.json
44ed868b1492e6d9e9976582afe291a74c5c20f1c7a4699b8b97c84fe16434a2  processed_pages.json
0c9fa3a98b42f8f5181e8921d0468e20e4764581ac3464d533d52df15e65098b  requirements.txt
70c5b19af8a2abae593ab12bfd1ef440882ef6a798e7ee629b1941ddc58eeb63  sap_pages/001.json
f684a43004836ded1459d7e69ab84d34ad9241c10d0c8ecc664456b5e78729a1  sap_pages/002.json
6f36f303c3d9f9e83197d611dba22859801b78fe9efae5443af07ec6dacfea05  sap_pages/003.json
de4333ba68763bb90be2bbd2e9884c80e5efce5ccfbf4078511b8ba41d81157c  sap_pages/004.json
1a84a1cedb5703d9d05ddb030f2430087be46ff386c2c702f9beb505d0044be6  sap_pages/005.json
ebe3d6dc975b521026887539c2ebd6baacc66b23100340f813ec783705009a92  sap_pages/006.json
cb977e1e5c356cc183a76b56cf5b097af170188978768a4811150976fb44dff4  sap_pages/007.json
d37ce3a21401b270f929818ed22a26d982181cd04b4b21f56b42dc9ad2ee4dc7  sap_pages/008.json
b28f2ac5501f6c4c25116b200cfe20715dddb8bfb6dd5209be8dfcfa9b52302e  sap_pages/009.json
9eb8f691f890d0944777c6ac110e0326bf61aefc2a720f238bb6520c70e084a6  sap_pages/010.json
943eaee582fd3788821c18593299e334f3f62f7ef4096c167ec3114d47a735dc  sap_pages/011.json
46d0a84c7ba6cccbfa722a35ff7f4fe902c56f0739453ea8c68d4a16bef850e6  sap_pages/012.json
a7b350b662f1da713a94253d6b7af07b1a574ef2e3b51489463cc943370e475c  sap_pages/013.json
3352211171606ad48b08f51155ba2d6ef93a583c72098e03aba638252a54f138  sap_pages/014.json
506b309cb1d978d894e323cd15f17064d4bb6478b69a810adb378c4f859add50  sap_pages/015.json
5d53d08673325e493cd2faf32e44e84791de6295b2893f05ed869335a02e29f2  sap_pages/016.json
879c07d4fe6600a4d0bf4a968661cb21eb038a4ae93d583fd53d486d5848936a  sap_pages/017.json
2028570f49cdce071a853136717f5dcc5f42a96788c5ec09fb387c2dfa63365a  sap_pages/018.json
21db7a55af0571c840a3633520f3e5d5c6f39379e20bb12b686235b3f0af0a83  sap_pages/019.json
287aeacf63135175466bf358d1cc0dc3946716ce1a1917b9ab5f4cbcc1136ee4  sap_pages/020.json
acdfb3786b4e8a71101e5e29eae2bcd7e8006e229b03941d640668a2c2db2d2b  sap_pages/021.json
0404e7673cf7ada2c32e309dd721055d206a8bf98ae019fdb8546904dbe92b16  sap_pages/022.json
b633e88aa07b6f3a7f891cd563c0493426d09cfe57df4c0ddcc19efd7ee57997  sap_pages/023.json
9ff1c2ea0990c4756aff125f75142cf082acd0e56ba0276750c2ec2eaf9a8910  sap_pages/024.json
394825c24daba8bc6a34ecb2f06bc16660a5b1794da22b2b7be958b0bb44855b  sap_pages/025.json
c09c4a974e58bc9e1550fceddf6a48a0f0c9d98a42e324074a87e23ebb54cea2  sap_pages/026.json
5d3a5701af7536bc0f098b256e95074fa04b30ecdc5cb016201609df0d9cc037  sap_pages/027.json
bc8bc4472e5417479e530c126a04bcd3995a61b1f9c3ab351a65babed2841623  sap_pages/028.json
54ae1b4e084341827780bedcbc8b256a21c68ec58bd18f9398479070f16594dd  sap_pages/029.json
ad436b8bc76d793695f0a848da7f177f5b87af2f20fb55e0127441fdaefeff14  sap_pages/030.json
976d87c377ed9b2ae0be4f9834e78fb3d08fe059a130c886dcd21e2de66207c7  sap_pages/031.json
7c2458cd1eac56199570eb47d80e41bbf744d6704849993dce8302952337ca0f  sap_pages/032.json
4aeca3ce470546cc92f7a096166077511f2614e82dbb93b36c142e46d66bee26  sap_pages/033.json
57cd138d1019ab0e1a9653d91ff9a19a3f8a8d0f26fb80034d89203dc07a704b  sap_pages/034.json
5e5302f205d4e968da52aebfe932e7602b3a207670d33bbc9271441544f0d4b9  sap_pages/035.json
db61f2dde5768ada24d3023fccee6f2118b84b3dcd488d9bec856d48ad8be218  sap_pages/036.json
215a95ef33386ece83e05e3614b9253eaa3955c817cf352fd6340ca96a8d2468  sap_pages/037.json
2c28e6abcbca650f11054f16a43efe8fc24dbfea11de1617d1521360225cefdc  sap_pages/038.json
1af3bd04660ae2971f60b55d22660ea9116099763e699903c279a7b717e14673  sap_pages/039.json
2bf03d3c98d2dd08ff8f79bb79b746db889a8e7b2eea505fbdcc55eb857e638e  sap_pages/040.json
130dbbcede6a6d5fb4ae2c97215a22df43e3e686f6393b6bf243dd17e9115960  sap_pages/041.json
0c622eab1d931fe4af177bfac90a385cad2219d8b45cddc14a8d151353c3143c  sap_pages/042.json
ed529263aa5e9734dcc8a45848d335664b6ca9f34097250d6dd80ea68c47b587  sap_pages/043.json
41af7db12d3d178d77b143117cb5db8499fb3e9990d99a752be7c8fd3dcc9f33  sap_pages/044.json
cc3f8741147825b2ece604b3bd22211ded9846ef23b6d916561bcf10eadf0c02  sap_pages/045.json
a7d1ff1a380a9d18b1a2e75578c28d5c3e7f92a4b0c86ba3e8751803f9e7233a  sap_pages/046.json
c463d5019c7dcedb90fcdb194e8c784de7700f36f722a8db4a949480cf88fbc2  sap_pages/047.json
e78ed4523af870b04294d057ddc01aa39215ed02001e7e0f8a0c1c4a0ebb7286  sap_pages/048.json
3a592cd15121441c7b1a420dcd4347fce12f14193a0fd36518ba0c2d6956b781  sap_pages/049.json
201c0c51c253801803f27395e09a3472a9cfda415f7d56cb2cd44fb5dd6b9535  sap_pages/050.json
cf06830257271a5eff24c276c3844e15e1fb59f6a4aea30e6d15915ea1a4610f  sap_pages/051.json
f03b9b6568a73a1b9380e4a3e3f98cfca6c39f89d28b7f93a275ff43a3c9fbe9  sap_pages/052.json
0dcb56654369c0141cb42f714b8904ead01f33a5c8385c9165e84610ccec92da  sap_pages/053.json
997658ad048368c55c9fc2dddd488f882e2bdfc911a4c3b2d6d358d512d92943  sap_pages/054.json
127b46f1879854dd8eb379f1150c9d348f6c977a2a5171b05d202bbe78778551  sap_pages/055.json
94665dfd7bc22343c107f4a24875fd2f49de07ba3979f76a8e9ea244273a2a7c  sap_pages/056.json
74144fceeb346d97a156a03b73b0bd6a58f817fb38233ba56333cd7241fae58b  sap_pages/057.json
b909ce80f5aa35a6c87775701f774f674ce526ccb82c2256ebf27894bac8c98e  sap_pages/058.json
5e819a7711ff8e6489604871a1201a92b42444f74d1e13cfb69d168aed72b1e7  sap_pages/059.json
9d3c940d2a05d7210ede17f038ed480e62ac2a381412feb2e0b3850984b7f2c5  sap_pages/060.json
b607b1bcafe26a6378743e011473d265456b08ee532273f5212144270cecbc06  sap_pages/061.json
09270b83b344f27d926ad9cb6141c257d2d90f100038403cba7c533633ec78ed  sap_pages/062.json
034dad24bb229e3c1c00035130c91be0c22761757a5f7d09ac2ea6f941589ef4  sap_pages/063.json
f0ff150d5dd1d75c8421b427eed826f642627f8789ed9cfcc9966361298f22ca  sap_pages/064.json
0715fdcb889a29c5e9707c008119b6ea55697c12f1b2f2723f6803a33fd25ed0  sap_pages/065.json
410f1d556809e254dfcbd84c4f8f4f5ef073fa3c17aea8d07998ee8bfb2d8d4c  sap_pages/066.json
c2bfa8c549f3b688d469878559c3a6d272261d0379691ecea4cebe5138f9fdcf  sap_pages/067.json
a288b1edf5bd20fb27364da5d7b48256ea354195fd4e8734341bf4bef3bd63fd  sap_pages/068.json
61219d65862ab1482efd4ff6d6bbe3e4f8ba268a3640d48721215571155fd687  sap_pages/069.json
3cbaba17ed0813fc84214ca09d680244b823c9924f9ad449277a846341e8559c  sap_pages/070.json
8f533ac93a1a0dba03098f1567ac285f561acb6b9504636e07dcb2243ef48608  sap_pages/071.json
538368a5a906d73807b3fa66da7e651c913f49be3657661f0979205f0f7612c9  sap_pages/072.json
c2e671d7e83953ce5c68f67d9c6cc82991625a3df28f83782b68ee31c0a00c2f  sap_pages/073.json
bbfff583c455500aeb39c6ea8f22ad70b70c9f692f8d04b12f107cd6c4f96132  sap_pages/074.json
64ef8998154a6899c8422d0713d0c1fdfbaa3b6949b02e53a208b2554a32b4d8  sap_pages/075.json
d17cac15005c4b93624016ccc72fc1707a6cb087b491510fe2c537b595269fe6  sap_pages/076.json
cfe6ba82b1f0edd2e3f2ac422207b43400672b47fc1d34a54e01d59c59644ff3  sap_pages/077.json
4ecca9e925075d4e4a64dd3bf06049b8c42d16ed760ad2cd794da7fd2272d853  sap_pages/078.json
1b00fb60c4b44730e6c5c7c4b22017fb3739c0f7da99532292ef99b8e2901889  sap_pages/079.json
f8dd57f1e7be3cf1668d0e15b66eda842db43e938ba925a23b5545e0b4f1a555  sap_pages/080.json
c01e5bed55bce5dab078e2a63aea83af710c7999cfd59a9b1b2b47486154444e  sap_pages/081.json
9e019ba8e5a8e663c0ce72ff1a70582cdb47fa6ee7783aac4afb5e49169a0bbe  sap_resolver/__init__.py
c8fe8374c116dd1e16f5bc250f7b85a2bebfdfd786e5d79efdb910674ec936c2  sap_resolver/chunk.py
2f9cf568e99c4a0b30633b213e5aa6369b0a777ae6a66a95452c707b916bc802  sap_resolver/clean.py
a725a43e69a2b1b9a276b1b9c347cb1483d9c9cb9efa8cc4b9412a46812c35af  sap_resolver/corrections.py
821894383f753626f23bcfee404874049cbe4d78fa7b6009118f012bede89dee  sap_resolver/dedupe.py
7b448c10cdf2f9fc546f601c2ed3ebe423da464ccd54d2c8d99f62dd75b40648  sap_resolver/events.py
6a98d4386f5ae3a63bb07ace7185d9afabc4fe5beece20d4ddc8115a3f104a40  sap_resolver/fetch.py
f5a5c56949cbfe859b59712400419fb63a58df3aaab27f9e089bad595eb14f29  sap_resolver/intake.py
bfd50083ed2b75aba0d4ebf42d8e06140692228d59836ae9e49bbb9a93dbebef  sap_resolver/pdf_cards.py
899b711483298806c32cad83d2a39df8eeeb0f25ccf91d5ac66027f72cb2ca8f  sap_resolver/pipeline.py
4107f43d6b7724b3c1501be017e9343dfc68308a74dc4453011ef9e5816e37ce  sap_resolver/plan.py
7e9b5e0c58bd8682808288047fa98e8410ed8ad7199d75ffa848b87a8fed858e  sap_resolver/registry.py
00078dee132ae08a5bf4a3a9ed61b18088167abe9912932b3f11ed1bf7c41c49  sap_resolver/repair.py
a1ce2d6863764adfbe7aa668a74cff1f601501d578d154d4aaa8d40235bc206e  sap_resolver/resolver.py
f4675db79360e19b80d2124f569a8ee40d3b3af8fd13636ceaa3ff496090665f  sap_resolver/schema.py
aa2e82c303ecefe6c0420936219ffe4cbcca16bb98d16055e6f30281fd25b747  sap_resolver/toc.py
0d209c4cdd5d111ca024b9c48e64aadaf98d629f3479d943f998998bc9c3afb2  sap_resolver/urls.py
88a171912dc8d618cb6e21bc94319df75f89503db132ddc320eb3818cc6b3b30  scripts/audit_corpus.py
39381b1ec959f1100e6d49404878d5f457c5fce74cc36b5ac558da40a9089233  scripts/build_card_collection.py
fddd7f977d58fd796b991c160279418241113dd66d3fc41b3b0639fa9982a347  scripts/build_card_eval_questions.py
225ba3781ba4d18a2f80bf1e9d87ada9440cd900cc51f15a7a330ea07df571d1  scripts/build_chunk_candidates.py
741f3a55dd041d39d48bef1e1177795076ebfb5a622cf45a511a7a7487c8d269  scripts/build_corpus.py
6fa45e111a0583914b54a8f6a2e48f77938e959f5db7e591b9132953b2fbf428  scripts/build_independent_queries.py
799032adee5c2ce05d157cdb02ee02d98169f397fc681c5ce1789a3bc88907c3  scripts/build_phase4_report.py
1180b9dbc1d6c8ddd8cf91c8ef2842610876ec1619161a26e4fcd7bdc6a1a5c1  scripts/build_phase5_report.py
bcfc54380394cf7443ab659c7820e4f466fdcda8e5c2bde6bd0a2ddf7021fad2  scripts/build_retrieval_units.py
d02fe5f29cf52796731d2c8caf4ff2c8a38e36d8ae1d67c308ff93ac59397215  scripts/build_source_corpus.py
31cc0a60d4f85edd09dc1a5a07f0c0957b290b3efdc4ebbd3c8445e17d4d69e3  scripts/build_source_manifest.py
368b068d1f1261a7e9ee641cf4068f8b76c4a72c0b4e476b04f0938b30f953e9  scripts/capture_responses.py
d0d3c9df3de2a8ca1b5c33b31f5e787a0ff3093b4dd17e4a52b21aa6e4bdc01d  scripts/chunk_pages.py
4ad4b47e7dd18219114da2e0c0f5399f6b589023c3c6c43171ae5488893199b2  scripts/clean_sap_pages.py
9395963f3e826163ab56b7a31f072d5c63d4d4043fb4f9192f93d6772b7fe6c0  scripts/compare_with_legacy.py
8464fd5acfb30a0913ef537eb02746a8e2b1cbaa4a8eab6e9fed325d1e8752dd  scripts/corpus_audit.py
2e00072b1a9863a848b13d3ff6f088b10837446521c12793c5c6d5eee2923144  scripts/create_embeddings.py
48c871089de8f03735f5ced8ee604001a0f3c4880fcb713740172830ee01e1d9  scripts/evaluate_answers.py
b73fef91daa6da83eab0b70a775d8955633da3b84c0ebe13e050498de167c6d5  scripts/evaluate_card_retrieval.py
f5f4df96296802e98dfa0786d6c55569720af9fcb5be7b2db8dd0eb77ae8b179  scripts/evaluate_phase5.py
6275a670ab3d274ed862479f9b2a7ac6f2be88153f44440e59bc9b984b10621d  scripts/evaluate_retrieval.py
f3943f322ceedd93b77192cd0ec3e170723f0d0c1a089cc4fd80d18e2a08b823  scripts/forensic_search.py
52446312bb67419110e0e3ee98d2d554b0c3f629cadeb2c400d67c364653800e  scripts/guide_intake.py
e37d9fee4d03e2f17c341f660625318347d15ce49fb7bd3c47c5bc6e44c560c4  scripts/inspect_pdf_cards.py
4d25dc1436c3465a55babdbe79ee7bce66f93d66049de21c7ba66fe483abea40  scripts/m2c_common.py
0ec1e9e8d34a09425eecf1bf14cdafcfe4cd7781128bf7f83b395ad8c1d4f14a  scripts/phase5_retrievers.py
a7a8d6fd5cc7b63ccdbbcd50c72ec238eac278fad0ab25fd56e73aa25c1fac66  scripts/process_sap_pages.py
e862ce38d06e2ef74f39e366a5a8b65948ba03f00dfab5baa0c61bc281673a15  scripts/rag_chat.py
881316e4f9f2c164b2109f416b2a309f8ab829f185d231b09990274f56567b2c  scripts/rag_core.py
fedc259b2a79d2f0f4cbd0384dcf0f2db2ed858063f0f9df8d53d29d7985c55b  scripts/repair_captured_response.py
0d26e9d488413ea5475ed6d77b060823ddd344c3c0b74986aec5025c093bdb51  scripts/resolve_topics.py
a7c878955709e5b1a1630d70b7f48993b2ee97602bdfdb899f5f70c986cda260  scripts/retrieve.py
e8a67a748bb05fb9304bc7170435b9538de3912c4825904fc2c91812564f385c  scripts/test_retrieval.py
dfe916b60e9a5d82a3da43394e0434854b385e4141d082e2ddfef4955fa6f7e7  scripts/test_search.py
70943bc8ff0ddfdb54c7783518213298e811832605495e62888ee0709c80a29e  scripts/validate_token_lengths.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  tests/__init__.py
47121824e46129849ac36d0c3f95a73dae7e915bebd0391c08f7092117784fbc  tests/test_card_retrieval_eval.py
8b0a4eb24bd8340098bce54bb3413eb49a97702de39c328dc99682cf52c6e5a0  tests/test_chunk_candidates.py
04158c62ba54cbe3a6823f8e812960f3478c96c0a1d78f2dfff86578ea64cb98  tests/test_corpus_pipeline.py
de5015fe749833162c210d5aa20a107d6d90e4df423367772d5856d50cfa0bae  tests/test_corrections.py
5f1d9d7bc395cfee61656cd192688b3c55815a8b1c6c0481df6a16dd47664be7  tests/test_phase5.py
5c554be78356a840940dc498ab3e5e44fc0c88ac79e5b9feeea7713833654fad  tests/test_repair_response.py
108b15431642f62f0c37e2030025409b0b0f7ec42a491747e07a743598db022f  tests/test_retrieval_units.py
27b8f52cc4a2d323580ae4e3e568ff641ad0d91a488e87b4e20a6d685ec7563d  tests/test_sap_resolver.py
45917b40c72ca4d1c71bdaa56b46a331b1e2191887fe0535b6a5d8c95e0d35aa  tests/test_source_corpus.py
e573df34fe9638d0f062a48a4fa69e1af334716bf32e8f410eccd7b0892f7541  tests/test_source_manifest.py
c0d6d67ddbdcdaf039137743677325b6d8c398eda6eee2b3320721fdfbaec69e  validate_corpus.py
```
<!-- sha256-end -->
