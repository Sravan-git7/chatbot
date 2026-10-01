# Comparison with legacy corpus: `data/sap_help_e2e/page_and_descendants`

* pages in new corpus: **22**, matched to legacy `sap_pages/` by `file_path`: **22** (041.json … 062.json)
* raw text identical to legacy `sap_pages` text: **22/22**
* cleaned text has the same letters/digits as legacy `cleaned_pages.json`: **22/22** (after collapsing the legacy doubled page title; whitespace and punctuation joins ignored)
* cleaned characters legacy → new: 37049 → 36175
* chunks legacy → new: 50 → 51
* chunk chars legacy: {'n': 50, 'avg': 740.4, 'median': 814.5, 'min': 143, 'max': 999}
* chunk chars new: {'n': 51, 'avg': 713.1, 'median': 815, 'min': 72, 'max': 999}


## Corpus level

```
{
 "legacy": {
  "pages": 81,
  "unique_pages_by_text": 75,
  "duplicate_pages": 6,
  "chunks": 310,
  "unique_chunks": 287,
  "duplicate_chunks": 23,
  "chunk_chars": {
   "n": 310,
   "avg": 795.8,
   "median": 892.0,
   "min": 45,
   "max": 1046
  },
  "guides_covered": [
   "40374631"
  ],
  "topics_covered_by_target_cards": [
   17
  ]
 },
 "new": {
  "pages": 22,
  "unique_canonical_pages": 22,
  "duplicate_content_pages": 0,
  "chunks": 51,
  "unique_chunks": 51,
  "duplicate_chunks": 0,
  "chunk_chars": {
   "n": 51,
   "avg": 713.1,
   "median": 815,
   "min": 72,
   "max": 999
  },
  "guides_covered": [
   "e52c8ee6197147ec97dfc2eb8c46a3ad"
  ],
  "topics_resolved": 1,
  "topics_total": 29,
  "corpus_complete": false
 },
 "legacy_pages_not_in_new_corpus": 59,
 "legacy_pages_not_in_new_corpus_note": "pages of the legacy scrape that no target topic (under the chosen scope) asks for - the noise the new corpus leaves out"
}
```

| page | legacy file | raw identical | legacy chunks | new chunks |
|---|---|---|---|---|
| Selecting Addresses for Business Partners | 052.json | True | 2 | 2 |
| Contract Accounts | 041.json | True | 3 | 4 |
| Displaying or Editing Other Business Partners | 051.json | True | 1 | 1 |
| Contract Account Category | 042.json | True | 2 | 2 |
| Contract Account | 043.json | True | 3 | 3 |
| Automatic Master Data Transfer | 047.json | True | 1 | 1 |
| Link: Contract Account - Business Partner | 045.json | True | 2 | 2 |
| Creating, Changing, and Displaying Contract Accounts | 048.json | True | 2 | 2 |
| Assigning Additional Business Partners | 050.json | True | 1 | 1 |
| Link Between Contract Accounts and Contracts (IS-U) | 059.json | True | 1 | 1 |
| Logging of Changes to Contract Account | 046.json | True | 2 | 2 |
| Contracts (IS-U) | 057.json | True | 1 | 1 |
| Manage Contract Accounts | 054.json | True | 2 | 2 |
| Controlling Specifications in Contract Accounts | 044.json | True | 7 | 6 |
| Correspondence for Master Data Changes | 055.json | True | 7 | 8 |
| Loans (IS-U) | 062.json | True | 4 | 4 |
| Contract Account and Contract Special Features for IS-U | 056.json | True | 1 | 1 |
| Creating, Changing and Displaying Locks | 053.json | True | 2 | 2 |
| Controlling Specifications in Contract Accounts (IS-U) | 058.json | True | 2 | 2 |
| Transferring Master Data Automatically (IS-U) | 060.json | True | 1 | 1 |
| Assigning Contracts to Contract Accounts (IS-U) | 061.json | True | 1 | 1 |
| Creating Contract Accounts | 049.json | True | 2 | 2 |
