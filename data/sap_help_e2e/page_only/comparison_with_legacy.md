# Comparison with legacy corpus: `data/sap_help_e2e/page_only`

* pages in new corpus: **1**, matched to legacy `sap_pages/` by `file_path`: **1** (041.json … 041.json)
* raw text identical to legacy `sap_pages` text: **1/1**
* cleaned text has the same letters/digits as legacy `cleaned_pages.json`: **1/1** (after collapsing the legacy doubled page title; whitespace and punctuation joins ignored)
* cleaned characters legacy → new: 2706 → 2683
* chunks legacy → new: 3 → 4
* chunk chars legacy: {'n': 3, 'avg': 901.3, 'median': 932, 'min': 812, 'max': 960}
* chunk chars new: {'n': 4, 'avg': 674.5, 'median': 814.5, 'min': 72, 'max': 997}

| page | legacy file | raw identical | legacy chunks | new chunks |
|---|---|---|---|---|
| Contract Accounts | 041.json | True | 3 | 4 |
