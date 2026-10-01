# Comparison with legacy corpus: `data/sap_help`

* pages in new corpus: **1**, matched to legacy `sap_pages/` by `file_path`: **1** (041.json … 041.json)
* raw text identical to legacy `sap_pages` text: **1/1**
* cleaned text has the same letters/digits as legacy `cleaned_pages.json`: **1/1** (after collapsing the legacy doubled page title; whitespace and punctuation joins ignored)
* cleaned characters legacy → new: 2706 → 2683
* chunks legacy → new: 3 → 4
* chunk chars legacy: {'n': 3, 'avg': 901.3, 'median': 932, 'min': 812, 'max': 960}
* chunk chars new: {'n': 4, 'avg': 674.5, 'median': 814.5, 'min': 72, 'max': 997}


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
  "pages": 1,
  "unique_canonical_pages": 1,
  "duplicate_content_pages": 0,
  "chunks": 4,
  "unique_chunks": 4,
  "duplicate_chunks": 0,
  "chunk_chars": {
   "n": 4,
   "avg": 674.5,
   "median": 814.5,
   "min": 72,
   "max": 997
  },
  "guides_covered": [
   "e52c8ee6197147ec97dfc2eb8c46a3ad"
  ],
  "topics_resolved": null,
  "topics_total": null,
  "corpus_complete": null
 },
 "legacy_pages_not_in_new_corpus": 80,
 "legacy_pages_not_in_new_corpus_note": "pages of the legacy scrape that no target topic (under the chosen scope) asks for - the noise the new corpus leaves out"
}
```

| page | legacy file | raw identical | legacy chunks | new chunks |
|---|---|---|---|---|
| Contract Accounts | 041.json | True | 3 | 4 |
